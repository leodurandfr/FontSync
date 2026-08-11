"""Router WebSocket pour les connexions temps réel."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from backend.auth import verify_websocket_token
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/client")
async def ws_client(websocket: WebSocket) -> None:
    """Connexion WebSocket pour les clients frontend."""
    # Auth par token (P1) : le handshake navigateur ne peut pas poser d'en-tête,
    # donc le token arrive en query param (ou cookie). On refuse avant `accept`.
    if not verify_websocket_token(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect_client(websocket)

    # Envoyer la liste des agents actuellement connectés (présence SSE `listen`).
    for agent_id in ws_manager.connected_sse_devices:
        await websocket.send_json(
            {
                "type": "device.connected",
                "data": {"deviceId": agent_id},
            }
        )

    try:
        while True:
            # Maintient la connexion ouverte, ignore les messages entrants
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
