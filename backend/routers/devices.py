"""Router pour la gestion des devices."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.schemas.device import DeviceRegister, DeviceResponse, DeviceUpdate
from backend.services.ws_manager import ws_manager

router = APIRouter(prefix="/api/devices", tags=["devices"])


async def _get_device_or_404(device_id: uuid.UUID, db: AsyncSession) -> Device:
    """Récupère un device par ID ou lève 404."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trouvé.")
    return device


@router.post("/register", response_model=DeviceResponse, status_code=201)
async def register_device(
    body: DeviceRegister,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Enregistre un device ou met à jour un existant (upsert par hostname)."""
    result = await db.execute(
        select(Device).where(Device.hostname == body.hostname)
    )
    device = result.scalar_one_or_none()

    if device is not None:
        # Mise à jour du device existant (sans écraser auto_pull/auto_push
        # qui sont gérés côté serveur via le frontend)
        device.name = body.name
        device.os = body.os
        device.os_version = body.os_version
        device.agent_version = body.agent_version
        device.font_directories = body.font_directories
        device.last_seen_at = datetime.now(timezone.utc)
    else:
        device = Device(
            name=body.name,
            hostname=body.hostname,
            os=body.os,
            os_version=body.os_version,
            agent_version=body.agent_version,
            font_directories=body.font_directories,
            auto_pull=body.auto_pull,
            auto_push=body.auto_push,
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(device)

    await db.commit()
    await db.refresh(device)
    return DeviceResponse.model_validate(device)


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
) -> list[DeviceResponse]:
    """Liste tous les devices enregistrés."""
    result = await db.execute(
        select(Device).order_by(Device.created_at.desc())
    )
    devices = result.scalars().all()
    return [DeviceResponse.model_validate(d) for d in devices]


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Met à jour un device."""
    device = await _get_device_or_404(device_id, db)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier.")
    for field, value in update_data.items():
        setattr(device, field, value)
    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(device)
    return DeviceResponse.model_validate(device)


@router.post("/{device_id}/rescan", status_code=202)
async def rescan_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Demande un re-scan de fonts à l'agent via WebSocket."""
    device = await _get_device_or_404(device_id, db)
    sent = await ws_manager.send_to_agent(
        str(device_id), {"type": "sync.request"}
    )
    if not sent:
        raise HTTPException(
            status_code=503,
            detail="L'agent n'est pas connecté.",
        )

    # L'agent enverra sync.status scanning/idle via WebSocket

    return {"status": "requested"}


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprime un device et ses associations."""
    device = await _get_device_or_404(device_id, db)
    await db.delete(device)
    await db.commit()
