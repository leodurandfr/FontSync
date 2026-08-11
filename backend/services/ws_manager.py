"""Gestionnaire des canaux temps réel.

Maintient :
- les connexions WebSocket des clients frontend ;
- les abonnements SSE des agents (process `listen`), à qui on pousse un simple
  signal « re-sync » quand une font devient disponible.

Les broadcasts sont sérialisés par un `asyncio.Lock` afin d'éviter
l'entrelacement de deux `send_json` concurrents sur un même socket.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Gère les connexions WebSocket des clients et les abonnements SSE."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        # Abonnements SSE par device_id : une queue par connexion `listen`.
        self._sse_subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()

    async def connect_client(self, websocket: WebSocket) -> None:
        """Accepte et enregistre une connexion client (frontend)."""
        await websocket.accept()
        self._clients.append(websocket)
        logger.info("Client WebSocket connecté (%d actifs)", len(self._clients))

    def disconnect(self, websocket: WebSocket) -> None:
        """Déconnecte un client."""
        if websocket in self._clients:
            self._clients.remove(websocket)
            logger.info("Client WebSocket déconnecté (%d actifs)", len(self._clients))

    async def broadcast_to_clients(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les clients frontend connectés."""
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._clients:
                try:
                    await ws.send_json(message)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self.disconnect(ws)

    # ---------- Canal SSE (process `listen` des agents) ----------

    def subscribe_agent_events(self, device_id: str) -> "asyncio.Queue[str]":
        """Abonne une connexion `listen` au canal SSE d'un device.

        Retourne une queue dans laquelle sont déposés les signaux « sync ».
        """
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._sse_subscribers.setdefault(device_id, set()).add(queue)
        logger.info(
            "Agent SSE abonné: %s (%d connexions)",
            device_id,
            len(self._sse_subscribers[device_id]),
        )
        return queue

    def unsubscribe_agent_events(
        self, device_id: str, queue: "asyncio.Queue[str]"
    ) -> None:
        """Désabonne une connexion `listen` du canal SSE d'un device."""
        subs = self._sse_subscribers.get(device_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            del self._sse_subscribers[device_id]
        logger.info("Agent SSE désabonné: %s", device_id)

    async def signal_sync(self, device_id: str) -> None:
        """Pousse un signal « re-sync » aux connexions SSE d'un device."""
        for queue in self._sse_subscribers.get(device_id, set()):
            queue.put_nowait("sync")

    async def broadcast_sync(self, exclude_device_id: str | None = None) -> None:
        """Pousse un signal « re-sync » à tous les devices abonnés en SSE.

        `exclude_device_id` permet d'éviter de re-signaler le device à
        l'origine du changement (il a déjà la font).
        """
        for device_id, subs in self._sse_subscribers.items():
            if device_id == exclude_device_id:
                continue
            for queue in subs:
                queue.put_nowait("sync")

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def connected_sse_devices(self) -> list[str]:
        """Device_ids ayant au moins une connexion SSE `listen` active.

        Source de présence « en ligne » depuis la migration de l'agent
        WebSocket → SSE : un `listen` connecté = device joignable. Les sets
        vides sont supprimés à la désinscription, donc une clé présente ⇔
        au moins un abonné actif.
        """
        return list(self._sse_subscribers.keys())


# Singleton global
ws_manager = WebSocketManager()
