"""Gestionnaire des canaux temps réel.

Maintient :
- les connexions WebSocket des clients frontend et des agents (legacy) ;
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
    """Gère les connexions WebSocket des clients/agents et les abonnements SSE."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._agents: dict[str, WebSocket] = {}
        # Abonnements SSE par device_id : une queue par connexion `listen`.
        self._sse_subscribers: dict[str, set[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()

    async def connect_client(self, websocket: WebSocket) -> None:
        """Accepte et enregistre une connexion client (frontend)."""
        await websocket.accept()
        self._clients.append(websocket)
        logger.info("Client WebSocket connecté (%d actifs)", len(self._clients))

    async def connect_agent(self, websocket: WebSocket, device_id: str) -> None:
        """Accepte et enregistre une connexion agent identifiée par device_id.

        À la reconnexion d'un device déjà connu, l'ancien socket est évincé
        (fermé) pour éviter une connexion fantôme côté serveur.
        """
        await websocket.accept()
        old = self._agents.get(device_id)
        if old is not None and old is not websocket:
            try:
                await old.close()
            except Exception:
                pass
            logger.info("Ancien socket agent évincé: %s", device_id)
        self._agents[device_id] = websocket
        logger.info(
            "Agent WebSocket connecté: %s (%d actifs)", device_id, len(self._agents)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Déconnecte un client ou agent."""
        if websocket in self._clients:
            self._clients.remove(websocket)
            logger.info("Client WebSocket déconnecté (%d actifs)", len(self._clients))
            return

        for device_id, ws in list(self._agents.items()):
            if ws is websocket:
                del self._agents[device_id]
                logger.info(
                    "Agent WebSocket déconnecté: %s (%d actifs)",
                    device_id,
                    len(self._agents),
                )
                return

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

    async def broadcast_to_agents(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les agents connectés (WebSocket)."""
        async with self._lock:
            stale: list[str] = []
            for device_id, ws in self._agents.items():
                try:
                    await ws.send_json(message)
                except Exception:
                    stale.append(device_id)
            for device_id in stale:
                del self._agents[device_id]

    async def send_to_agent(self, device_id: str, message: dict[str, Any]) -> bool:
        """Envoie un message à un agent spécifique. Retourne False si non connecté."""
        async with self._lock:
            ws = self._agents.get(device_id)
            if ws is None:
                return False
            try:
                await ws.send_json(message)
                return True
            except Exception:
                del self._agents[device_id]
                return False

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
    def agent_count(self) -> int:
        return len(self._agents)

    @property
    def connected_agents(self) -> list[str]:
        return list(self._agents.keys())


# Singleton global
ws_manager = WebSocketManager()
