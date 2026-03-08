"""Gestionnaire de connexions WebSocket.

Maintient les connexions des clients frontend et des agents,
et permet le broadcast de messages en temps réel.
"""

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Gère les connexions WebSocket des clients et agents."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._agents: dict[str, WebSocket] = {}

    async def connect_client(self, websocket: WebSocket) -> None:
        """Accepte et enregistre une connexion client (frontend)."""
        await websocket.accept()
        self._clients.append(websocket)
        logger.info("Client WebSocket connecté (%d actifs)", len(self._clients))

    async def connect_agent(self, websocket: WebSocket, device_id: str) -> None:
        """Accepte et enregistre une connexion agent identifiée par device_id."""
        await websocket.accept()
        self._agents[device_id] = websocket
        logger.info("Agent WebSocket connecté: %s (%d actifs)", device_id, len(self._agents))

    def disconnect(self, websocket: WebSocket) -> None:
        """Déconnecte un client ou agent."""
        if websocket in self._clients:
            self._clients.remove(websocket)
            logger.info("Client WebSocket déconnecté (%d actifs)", len(self._clients))
            return

        for device_id, ws in list(self._agents.items()):
            if ws is websocket:
                del self._agents[device_id]
                logger.info("Agent WebSocket déconnecté: %s (%d actifs)", device_id, len(self._agents))
                return

    async def broadcast_to_clients(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les clients frontend connectés."""
        stale: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def broadcast_to_agents(self, message: dict[str, Any]) -> None:
        """Envoie un message JSON à tous les agents connectés."""
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
        ws = self._agents.get(device_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            del self._agents[device_id]
            return False

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
