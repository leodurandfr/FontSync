"""Client de synchronisation avec le serveur FontSync."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
        payload = {
            "device_id": device_id,
            "fonts": [
                {"hash": f.file_hash, "filename": f.filename} for f in fonts
            ],
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
        on_progress: callable | None = None,
    ) -> tuple[int, int, int]:
        """Push les fonts dont les hashes sont dans hashes_to_push.

        Retourne (pushed, duplicates, errors).
        """
        to_push = [f for f in fonts if f.file_hash in hashes_to_push]
        pushed = 0
        duplicates = 0
        errors = 0
        total = len(to_push)

        for i, font in enumerate(to_push):
            try:
                result = self.push_font(device_id, font)
                if result.get("is_duplicate"):
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
