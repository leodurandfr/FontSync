"""Router WebSocket pour les connexions temps réel."""

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.future import select

from backend.database import async_session
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/client")
async def ws_client(websocket: WebSocket) -> None:
    """Connexion WebSocket pour les clients frontend."""
    await ws_manager.connect_client(websocket)

    # Envoyer la liste des agents actuellement connectés
    for agent_id in ws_manager.connected_agents:
        await websocket.send_json({
            "type": "device.connected",
            "data": {"deviceId": agent_id},
        })

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

            elif msg_type == "font.uninstalled":
                # L'agent confirme la désinstallation d'une font
                font_id_str = message.get("data", {}).get("fontId")
                if font_id_str:
                    try:
                        font_uuid = uuid.UUID(font_id_str)
                    except ValueError:
                        continue
                    async with async_session() as db:
                        df_result = await db.execute(
                            select(DeviceFont).where(
                                DeviceFont.font_id == font_uuid,
                                DeviceFont.device_id == uuid.UUID(device_id),
                            )
                        )
                        df = df_result.scalar_one_or_none()
                        if df:
                            await db.delete(df)
                            await db.commit()
                    # Notifier les clients frontend
                    await ws_manager.broadcast_to_clients({
                        "type": "font.uninstalled",
                        "data": {"fontId": font_id_str, "deviceId": device_id},
                    })

            elif msg_type in ("font.activated", "font.deactivated"):
                # L'agent confirme l'activation/désactivation d'une font
                font_id_str = message.get("data", {}).get("fontId")
                if font_id_str:
                    try:
                        font_uuid = uuid.UUID(font_id_str)
                    except ValueError:
                        continue
                    activated = msg_type == "font.activated"
                    async with async_session() as db:
                        df_result = await db.execute(
                            select(DeviceFont).where(
                                DeviceFont.font_id == font_uuid,
                                DeviceFont.device_id == uuid.UUID(device_id),
                            )
                        )
                        df = df_result.scalar_one_or_none()
                        if df:
                            df.activated = activated
                            await db.commit()
                    await ws_manager.broadcast_to_clients({
                        "type": msg_type,
                        "data": {"fontId": font_id_str, "deviceId": device_id, "activated": activated},
                    })

            elif msg_type == "sync.status":
                new_status = message.get("status", "idle")
                async with async_session() as db:
                    result = await db.execute(
                        select(Device).where(Device.id == uuid.UUID(device_id))
                    )
                    device = result.scalar_one_or_none()
                    if device:
                        device.sync_status = new_status
                        if new_status == "idle":
                            device.last_sync_at = datetime.now(timezone.utc)
                        await db.commit()
                await ws_manager.broadcast_to_clients({
                    "type": "device.updated",
                    "data": {"deviceId": device_id, "syncStatus": new_status},
                })

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

        # Remettre le syncStatus à idle si l'agent se déconnecte en plein scan/sync
        async with async_session() as db:
            result = await db.execute(
                select(Device).where(Device.id == uuid.UUID(device_id))
            )
            device = result.scalar_one_or_none()
            if device and device.sync_status != "idle":
                device.sync_status = "idle"
                await db.commit()

        # Notifier les clients frontend de la déconnexion
        await ws_manager.broadcast_to_clients({
            "type": "device.disconnected",
            "data": {"deviceId": device_id},
        })
        # Aussi envoyer un device.updated pour reset le syncStatus côté frontend
        await ws_manager.broadcast_to_clients({
            "type": "device.updated",
            "data": {"deviceId": device_id, "syncStatus": "idle"},
        })
