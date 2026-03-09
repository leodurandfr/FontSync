"""Client de synchronisation avec le serveur FontSync.

Combine un client HTTP (httpx) pour les opérations REST
et un client WebSocket (websockets) pour les notifications temps réel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from agent.config import AGENT_VERSION, AgentConfig
from agent.scanner import ScannedFont

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 120.0

# Backoff exponentiel pour la reconnexion WebSocket
WS_INITIAL_DELAY = 1.0
WS_MAX_DELAY = 60.0
WS_BACKOFF_FACTOR = 2.0


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

    def delta_sync(
        self, device_id: str, fonts: list[ScannedFont]
    ) -> dict[str, Any]:
        """Envoie les hashes locaux au serveur pour comparaison.

        POST /api/sync/delta
        Retourne : unknown_to_server, missing_on_device, already_synced
        """
        return self.delta_sync_hashes(
            device_id,
            [{"hash": f.file_hash, "filename": f.filename} for f in fonts],
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
                logger.error("Erreur push %s : HTTP %d", font.filename, e.response.status_code)
                errors += 1
            except Exception:
                logger.exception("Erreur push %s", font.filename)
                errors += 1

            if on_progress:
                on_progress(i + 1, total)

        return pushed, duplicates, errors

    # ---- Pull ----

    def pull_font(self, font_id: str) -> tuple[str, bytes]:
        """Télécharge une font depuis le serveur.

        GET /api/sync/pull/{font_id}
        Retourne (filename, data).
        """
        resp = self._client.get(
            f"{self.base_url}/api/sync/pull/{font_id}",
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


# ---------------------------------------------------------------------------
# Client WebSocket pour les notifications temps réel
# ---------------------------------------------------------------------------


class WebSocketClient:
    """Connexion WebSocket persistante avec le serveur FontSync.

    Reconnexion automatique avec backoff exponentiel en cas de perte.
    Quand la connexion est rétablie, déclenche un delta sync pour rattraper
    les changements manqués.
    """

    def __init__(
        self,
        config: AgentConfig,
        device_id: str,
        on_font_available: Callable[[dict[str, Any]], Any] | None = None,
        on_sync_request: Callable[[], Any] | None = None,
        on_connected: Callable[[], Any] | None = None,
        on_disconnected: Callable[[], Any] | None = None,
    ) -> None:
        self._config = config
        self._device_id = device_id
        self._on_font_available = on_font_available
        self._on_sync_request = on_sync_request
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        # Construire l'URL WebSocket
        base = config.server_url.rstrip("/")
        scheme = "wss" if base.startswith("https") else "ws"
        host = base.replace("https://", "").replace("http://", "")
        self._ws_url = f"{scheme}://{host}/ws/agent/{device_id}"

        self._running = False
        self._ws: ClientConnection | None = None

    async def run(self) -> None:
        """Boucle de connexion WebSocket avec reconnexion automatique."""
        self._running = True
        delay = WS_INITIAL_DELAY

        while self._running:
            try:
                logger.info("WebSocket : connexion à %s...", self._ws_url)
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    delay = WS_INITIAL_DELAY  # Reset du backoff
                    logger.info("WebSocket : connecté")

                    if self._on_connected:
                        await self._on_connected()

                    await self._listen(ws)

            except websockets.ConnectionClosed as e:
                logger.warning("WebSocket : connexion fermée (code=%s)", e.code)
            except OSError as e:
                logger.warning("WebSocket : erreur réseau — %s", e)
            except Exception:
                logger.exception("WebSocket : erreur inattendue")
            finally:
                self._ws = None
                if self._running and self._on_disconnected:
                    try:
                        await self._on_disconnected()
                    except Exception:
                        logger.debug("Erreur callback on_disconnected")

            if not self._running:
                break

            logger.info("WebSocket : reconnexion dans %.0fs...", delay)
            await asyncio.sleep(delay)
            delay = min(delay * WS_BACKOFF_FACTOR, WS_MAX_DELAY)

    async def _listen(self, ws: ClientConnection) -> None:
        """Écoute les messages du serveur."""
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("WebSocket : message non-JSON ignoré")
                continue

            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "font.available":
                logger.info(
                    "WebSocket : nouvelle font disponible — %s",
                    data.get("originalFilename", "?"),
                )
                if self._on_font_available:
                    await self._on_font_available(data)

            elif msg_type == "sync.request":
                logger.info("WebSocket : re-scan demandé par le serveur")
                if self._on_sync_request:
                    await self._on_sync_request()

            elif msg_type == "heartbeat.ack":
                logger.debug("WebSocket : heartbeat ACK")

            else:
                logger.debug("WebSocket : message ignoré (type=%s)", msg_type)

    async def send_heartbeat(self) -> None:
        """Envoie un heartbeat au serveur."""
        await self.send_message({"type": "heartbeat"})

    async def send_message(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON au serveur."""
        if self._ws:
            try:
                await self._ws.send(json.dumps(message))
            except Exception:
                logger.debug("WebSocket : impossible d'envoyer %s", message.get("type"))

    async def stop(self) -> None:
        """Arrête la boucle de reconnexion et ferme la connexion WebSocket."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Erreur lors de la fermeture du WebSocket")
