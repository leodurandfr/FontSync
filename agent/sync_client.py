"""Client HTTP synchrone pour les opérations REST avec le serveur FontSync.

`sync` étant une commande courte (pas d'event loop), un client `httpx`
**synchrone** suffit : le bug historique de blocage de l'event loop disparaît
par construction. Le canal temps réel serveur→agent passe par SSE (process
`listen`, cf. PLAN.md B4) ; il n'y a plus de client WebSocket persistant.

Conventions HTTP (cf. CLAUDE.md) : le serveur sérialise ses réponses JSON en
**camelCase** — toutes les lectures de réponse ci-dessous utilisent donc des
clés camelCase (`fontId`, `isDuplicate`, …).

Robustesse : un client unique avec `base_url`, timeouts explicites et en-têtes
par défaut ; les erreurs réseau **transitoires** sont réessayées un nombre borné
de fois. Toutes les opérations REST de l'agent étant idempotentes côté serveur
(register = upsert par hostname, delta = lecture pure, push = dédup par hash,
pull = GET), un réessai ne peut pas dupliquer d'effet.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import unquote

import httpx

from agent.config import AGENT_VERSION, AgentConfig
from agent.scanner import ScannedFont

logger = logging.getLogger(__name__)

# Timeouts explicites (connect/read/write/pool) plutôt qu'un float global :
# une connexion lente à établir et un transfert lent sont des problèmes
# distincts qu'on veut borner séparément.
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
# Upload/download de fichiers : lecture/écriture potentiellement longues.
TRANSFER_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)

# Réessais bornés sur erreurs réseau transitoires (NAS brièvement injoignable,
# coupure réseau passagère). On ne réessaie **que** les erreurs de transport,
# pas les erreurs HTTP applicatives (4xx/5xx) qui remontent telles quelles.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0

_TRANSIENT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class SyncClientError(Exception):
    """Échec d'une requête HTTP après réessais (serveur réseau injoignable)."""


class SyncClient:
    """Client HTTP pour communiquer avec le serveur FontSync."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=config.server_url.rstrip("/"),
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": f"fontsync-agent/{AGENT_VERSION}",
                "Accept": "application/json",
            },
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ---- Envoi avec réessais ----

    def _send(
        self, build: Callable[[], httpx.Response], *, what: str
    ) -> httpx.Response:
        """Exécute une requête avec réessais bornés sur erreurs transitoires.

        `build()` (re)construit **et envoie** la requête à chaque tentative : il
        doit être ré-exécutable (ré-ouvrir un fichier pour un upload, etc.). Une
        réponse HTTP d'erreur (4xx/5xx) lève `HTTPStatusError` sans réessai ; une
        erreur de transport est réessayée puis, épuisée, levée en
        `SyncClientError`.
        """
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = build()
                resp.raise_for_status()
                return resp
            except _TRANSIENT_ERRORS as e:
                last_exc = e
                if attempt < MAX_ATTEMPTS:
                    delay = RETRY_BACKOFF_SECONDS * attempt
                    logger.warning(
                        "%s : erreur réseau (tentative %d/%d), réessai dans %.0fs : %s",
                        what,
                        attempt,
                        MAX_ATTEMPTS,
                        delay,
                        e,
                    )
                    self._sleep(delay)
        raise SyncClientError(
            f"{what} : serveur injoignable après {MAX_ATTEMPTS} tentatives : {last_exc}"
        ) from last_exc

    # ---- Enregistrement du device ----

    def register_device(self) -> dict[str, Any]:
        """Enregistre ce device auprès du serveur.

        POST /api/devices/register
        Retourne la réponse complète du serveur (avec l'id du device).
        """
        payload = {
            "name": self.config.get_device_name(),
            "hostname": self.config.get_hostname(),
            "os": "macos",
            "os_version": self.config.get_os_version(),
            "agent_version": AGENT_VERSION,
            "font_directories": self.config.directories,
            "auto_pull": self.config.auto_pull,
            "auto_push": self.config.auto_push,
        }

        resp = self._send(
            lambda: self._client.post("/api/devices/register", json=payload),
            what="register_device",
        )
        data = resp.json()
        logger.info("Device enregistré : %s (id=%s)", data["name"], data["id"])
        return data

    # ---- Delta sync ----

    def delta_sync(self, device_id: str, fonts: list[ScannedFont]) -> dict[str, Any]:
        """Envoie les hashes locaux au serveur pour comparaison.

        POST /api/sync/delta
        Retourne : unknownToServer, missingOnDevice, alreadySynced
        """
        return self.delta_sync_hashes(
            device_id,
            [
                {
                    "hash": f.file_hash,
                    "filename": f.filename,
                    "localPath": str(f.path),
                }
                for f in fonts
            ],
        )

    def delta_sync_hashes(
        self, device_id: str, font_entries: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Envoie des entrées {hash, filename} au serveur pour comparaison."""
        payload = {
            "device_id": device_id,
            "fonts": font_entries,
        }

        resp = self._send(
            lambda: self._client.post("/api/sync/delta", json=payload),
            what="delta_sync",
        )
        return resp.json()

    # ---- Push ----

    def push_font(self, device_id: str, font: ScannedFont) -> dict[str, Any]:
        """Push une font vers le serveur.

        POST /api/sync/push (multipart form)
        """

        def build() -> httpx.Response:
            # Le fichier est ré-ouvert à chaque tentative : `build` doit pouvoir
            # être rejoué tel quel par `_send` en cas de réessai.
            with open(font.path, "rb") as f:
                files = {"file": (font.filename, f, "application/octet-stream")}
                data = {
                    "device_id": device_id,
                    "local_path": str(font.path),
                }
                return self._client.post(
                    "/api/sync/push",
                    files=files,
                    data=data,
                    timeout=TRANSFER_TIMEOUT,
                )

        resp = self._send(build, what=f"push {font.filename}")
        result = resp.json()
        logger.debug(
            "Push %s → %s (duplicate=%s)",
            font.filename,
            result.get("fontId"),
            result.get("isDuplicate"),
        )
        return result

    def push_fonts(
        self,
        device_id: str,
        fonts: list[ScannedFont],
        hashes_to_push: set[str],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int, int]:
        """Push les fonts dont les hashes sont dans hashes_to_push.

        Retourne (pushed, duplicates, errors).
        """
        seen_hashes: set[str] = set()
        to_push: list[ScannedFont] = []
        for f in fonts:
            if f.file_hash in hashes_to_push and f.file_hash not in seen_hashes:
                to_push.append(f)
                seen_hashes.add(f.file_hash)
        pushed = 0
        duplicates = 0
        errors = 0
        total = len(to_push)

        for i, font in enumerate(to_push):
            try:
                result = self.push_font(device_id, font)
                if result.get("isDuplicate"):
                    duplicates += 1
                else:
                    pushed += 1
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Erreur push %s : HTTP %d", font.filename, e.response.status_code
                )
                errors += 1
            except Exception:
                logger.exception("Erreur push %s", font.filename)
                errors += 1

            if on_progress:
                on_progress(i + 1, total)

        return pushed, duplicates, errors

    # ---- Pull ----

    def pull_font(
        self, font_id: str, device_id: str | None = None
    ) -> tuple[str, bytes]:
        """Télécharge une font depuis le serveur.

        GET /api/sync/pull/{font_id}
        Retourne (filename, data).
        """
        params = {}
        if device_id:
            params["device_id"] = device_id
        resp = self._send(
            lambda: self._client.get(
                f"/api/sync/pull/{font_id}",
                params=params,
                timeout=TRANSFER_TIMEOUT,
            ),
            what=f"pull {font_id}",
        )

        return _filename_from_disposition(
            resp.headers.get("content-disposition", "")
        ), resp.content


def _filename_from_disposition(cd: str) -> str:
    """Extrait le nom de fichier d'un en-tête `Content-Disposition`.

    Gère la forme RFC 5987 (`filename*=UTF-8''nom%20encodé`) prioritairement,
    puis la forme simple (`filename="nom"`). Défaut : `unknown.ttf`.
    """
    if "filename*=" in cd:
        raw = cd.split("filename*=")[-1]
        # Retirer le préfixe d'encodage (UTF-8'')
        if "''" in raw:
            raw = raw.split("''", 1)[-1]
        return unquote(raw)
    if "filename=" in cd:
        return cd.split("filename=")[-1].strip('"')
    return "unknown.ttf"
