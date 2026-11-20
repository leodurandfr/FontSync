"""Router WebSocket pour les connexions temps réel."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from backend.auth import verify_websocket_token
from backend.config import settings
from backend.host_guard import origin_is_allowed
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/client")
async def ws_client(websocket: WebSocket) -> None:
    """Connexion WebSocket pour les clients frontend."""
    # Origin (P1-5f) : une page d'un autre site ne peut pas ouvrir ce WebSocket,
    # même si elle connaissait le token. Absent (client hors navigateur) : admis.
    origins = websocket.headers.getlist("origin")
    host = websocket.headers.get("host")
    if len(origins) > 1 or not origin_is_allowed(
        origins[0] if origins else None,
        host,
        settings.allowed_hosts,
        settings.allowed_origins,
    ):
        # Côté navigateur, ce refus (403 au handshake) ressemble à un mauvais
        # token : le journal est le seul endroit qui dit pourquoi. %r échappe
        # une Origin forgée ; le token (query) n'y figure jamais.
        logger.warning(
            "WebSocket refusé : Origin %r non admise pour Host %r "
            "(ALLOWED_HOSTS / ALLOWED_ORIGINS)",
            origins if len(origins) > 1 else origins[0],
            host,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Auth par token (P1) : le handshake navigateur ne peut pas poser d'en-tête,
    # donc le token arrive en query param. On refuse avant `accept`.
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
