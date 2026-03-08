"""Router WebSocket pour les connexions temps réel."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/client")
async def ws_client(websocket: WebSocket) -> None:
    """Connexion WebSocket pour les clients frontend."""
    await ws_manager.connect_client(websocket)
    try:
        while True:
            # Maintient la connexion ouverte, ignore les messages entrants
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@router.websocket("/ws/agent/{device_id}")
async def ws_agent(websocket: WebSocket, device_id: str) -> None:
    """Connexion WebSocket pour un agent identifié par device_id."""
    await ws_manager.connect_agent(websocket, device_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
