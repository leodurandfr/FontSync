"""Router pour la gestion des devices."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.schemas.device import (
    DeviceMerge,
    DeviceMergeResponse,
    DeviceRegister,
    DeviceResponse,
    DeviceUpdate,
)
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


async def _get_device_or_404(device_id: uuid.UUID, db: AsyncSession) -> Device:
    """Récupère un device par ID ou lève 404."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trouvé.")
    return device


def _to_response(device: Device) -> DeviceResponse:
    """Sérialise un device en y injectant la présence « en ligne ».

    Le statut online n'est pas une colonne : il vient des connexions SSE
    `listen` actives (`ws_manager`). L'exposer dans le REST permet au frontend
    d'afficher le bon état **dès le chargement**, sans dépendre uniquement des
    événements WebSocket `device.connected` (qui ne rejouent pas l'historique).
    """
    resp = DeviceResponse.model_validate(device)
    resp.is_online = str(device.id) in ws_manager.connected_sse_devices
    return resp


@router.post("/register", response_model=DeviceResponse, status_code=201)
async def register_device(
    body: DeviceRegister,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Enregistre un device ou met à jour un existant.

    L'identité vient d'abord du `device_id` que l'agent persiste depuis son
    premier enregistrement, et seulement à défaut du hostname. Ce n'est pas un
    raffinement : macOS change de hostname selon le réseau (`.local` en Bonjour,
    `.home` en DHCP), et un upsert par hostname créait une ligne par variante.
    Trois lignes pour un même Mac mini, et toute règle « quelles machines
    détiennent cette police » devient fausse.

    Un `device_id` inconnu du serveur (base repartie de zéro, appareil supprimé
    depuis l'interface) retombe sur le hostname : l'agent se ré-enregistre au
    lieu d'échouer.
    """
    device: Device | None = None
    if body.device_id is not None:
        result = await db.execute(select(Device).where(Device.id == body.device_id))
        device = result.scalar_one_or_none()

    if device is None:
        result = await db.execute(
            select(Device).where(Device.hostname == body.hostname)
        )
        device = result.scalar_one_or_none()

    if device is not None:
        # Le hostname est une donnée mouvante, pas une clé : on le rafraîchit.
        device.hostname = body.hostname
        # Mise à jour du device existant (sans écraser auto_pull/auto_push ni
        # propagate_deletions, qui sont gérés côté serveur via le frontend)
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
    return _to_response(device)


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    db: AsyncSession = Depends(get_db),
) -> list[DeviceResponse]:
    """Liste tous les devices enregistrés."""
    result = await db.execute(select(Device).order_by(Device.created_at.desc()))
    devices = result.scalars().all()
    return [_to_response(d) for d in devices]


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
    return _to_response(device)


@router.post("/{device_id}/merge", response_model=DeviceMergeResponse)
async def merge_devices(
    device_id: uuid.UUID,
    body: DeviceMerge,
    db: AsyncSession = Depends(get_db),
) -> DeviceMergeResponse:
    """Absorbe des appareils en double dans celui-ci, puis les supprime.

    Fusionner plutôt que supprimer, parce que le registre `device_fonts` est
    réparti entre les doublons. Supprimer les lignes en trop laisserait la
    survivante avec un registre partiel : la détection des suppressions locales
    serait aveugle sur ces polices-là, et le resterait — une police déjà
    synchronisée ne repasse jamais par un transfert qui recréerait l'association.

    Les associations que la cible possède déjà sont retirées du doublon sans
    être recréées (la clé primaire est le couple appareil/police).
    """
    target = await _get_device_or_404(device_id, db)

    sources: list[Device] = []
    for source_id in dict.fromkeys(body.source_device_ids):
        if source_id == target.id:
            raise HTTPException(
                status_code=400,
                detail="Un appareil ne peut pas se fusionner en lui-même.",
            )
        sources.append(await _get_device_or_404(source_id, db))

    known = await db.execute(
        select(DeviceFont.font_id).where(DeviceFont.device_id == target.id)
    )
    target_font_ids = set(known.scalars().all())

    moved = 0
    for source in sources:
        rows = await db.execute(
            select(DeviceFont).where(DeviceFont.device_id == source.id)
        )
        for row in rows.scalars().all():
            if row.font_id not in target_font_ids:
                db.add(
                    DeviceFont(
                        device_id=target.id,
                        font_id=row.font_id,
                        local_path=row.local_path,
                        activated=row.activated,
                        installed_at=row.installed_at,
                    )
                )
                target_font_ids.add(row.font_id)
                moved += 1
            await db.delete(row)
        # Les associations partent avant l'appareil : `PRAGMA foreign_keys=ON`.
        await db.flush()
        await db.delete(source)

    await db.commit()
    await db.refresh(target)

    logger.info(
        "Fusion dans %s : %d association(s) réaffectée(s), %d appareil(s) supprimé(s).",
        target.id,
        moved,
        len(sources),
    )
    return DeviceMergeResponse(
        device=_to_response(target), fonts_moved=moved, devices_removed=len(sources)
    )


@router.post("/{device_id}/rescan", status_code=202)
async def rescan_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Signale à l'appareil de se re-synchroniser (SSE).

    Passait auparavant par `send_to_agent` (WebSocket agent), canal mort depuis
    la bascule de l'agent en SSE : l'endpoint répondait 503 en permanence.

    Best-effort, comme `/fonts/{id}/install/{device_id}` : si aucun process
    `listen` n'est abonné, le signal est ignoré — l'appareil se resynchronise de
    toute façon périodiquement et sur `WatchPaths`.
    """
    await _get_device_or_404(device_id, db)
    await ws_manager.signal_sync(str(device_id))
    return {"status": "resync_requested"}


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprime un device et ses associations.

    Les lignes `device_fonts` sont retirées explicitement : elles portent le
    device dans leur clé primaire, donc SQLAlchemy ne peut pas les dissocier et
    la suppression échouait sur la contrainte de clé étrangère (`PRAGMA
    foreign_keys=ON`) dès que l'appareil avait transféré la moindre police —
    c'est-à-dire toujours. Les polices, elles, restent : le serveur est la
    source de vérité, retirer une machine n'ampute pas la bibliothèque.
    """
    device = await _get_device_or_404(device_id, db)
    await db.execute(delete(DeviceFont).where(DeviceFont.device_id == device.id))
    await db.delete(device)
    await db.commit()
