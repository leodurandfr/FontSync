"""Client HTTP synchrone pour les opérations REST avec le serveur FontSync.

Le canal temps réel serveur→agent passe désormais par SSE (process `listen`,
cf. PLAN.md B4) ; il n'y a plus de client WebSocket persistant côté agent.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from agent.config import AGENT_VERSION, AgentConfig
from agent.scanner import ScannedFont

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 120.0


class SyncClient:
    """Client HTTP pour communiquer avec le serveur FontSync."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.base_url = config.server_url.rstrip("/")
        self._client = httpx.Client(timeout=REQUEST_TIMEOUT)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SyncClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

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

        resp = self._client.post(f"{self.base_url}/api/devices/register", json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Device enregistré : %s (id=%s)", data["name"], data["id"])
        return data

    # ---- Delta sync ----

    def delta_sync(self, device_id: str, fonts: list[ScannedFont]) -> dict[str, Any]:
        """Envoie les hashes locaux au serveur pour comparaison.

        POST /api/sync/delta
        Retourne : unknown_to_server, missing_on_device, already_synced
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

        resp = self._client.post(f"{self.base_url}/api/sync/delta", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ---- Push ----

    def push_font(self, device_id: str, font: ScannedFont) -> dict[str, Any]:
        """Push une font vers le serveur.

        POST /api/sync/push (multipart form)
        """
        with open(font.path, "rb") as f:
            files = {"file": (font.filename, f, "application/octet-stream")}
            data = {
                "device_id": device_id,
                "local_path": str(font.path),
            }
            resp = self._client.post(
                f"{self.base_url}/api/sync/push",
                files=files,
                data=data,
                timeout=UPLOAD_TIMEOUT,
            )
        resp.raise_for_status()
        result = resp.json()
        logger.debug(
            "Push %s → %s (duplicate=%s)",
            font.filename,
            result.get("font_id"),
            result.get("is_duplicate"),
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
        resp = self._client.get(
            f"{self.base_url}/api/sync/pull/{font_id}",
            params=params,
            timeout=UPLOAD_TIMEOUT,
        )
        resp.raise_for_status()

        # Extraire le nom de fichier du header Content-Disposition
        cd = resp.headers.get("content-disposition", "")
        filename = "unknown.ttf"
        if "filename*=" in cd:
            # RFC 5987: filename*=UTF-8''encoded_name
            from urllib.parse import unquote

            raw = cd.split("filename*=")[-1]
            # Strip encoding prefix (UTF-8'')
            if "''" in raw:
                raw = raw.split("''", 1)[-1]
            filename = unquote(raw)
        elif "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('"')

        return filename, resp.content
