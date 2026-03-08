"""Router WebSocket pour les connexions temps réel."""

import json
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

    # Notifier les clients frontend de la connexion
    await ws_manager.broadcast_to_clients({
        "type": "device.connected",
        "data": {"deviceId": device_id},
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("type")

            if msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat.ack"})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

        # Notifier les clients frontend de la déconnexion
        await ws_manager.broadcast_to_clients({
            "type": "device.disconnected",
            "data": {"deviceId": device_id},
        })
