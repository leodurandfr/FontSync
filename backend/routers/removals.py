"""Mes polices retirées : `/api/me/removals`.

Une police supprimée sur un de mes Mac est un retrait **personnel** : mes Mac
ne la réinstallent plus, ceux qui l'acceptent la désinstallent, et personne
d'autre n'est concerné (cf. `services/deletion_propagation.py`). Chaque compte
ne voit et ne gère que les siens — l'admin compris : il n'y a pas de route pour
agir sur les retraits d'un autre.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import Principal, require_auth
from backend.database import get_db
from backend.models.device import Device
from backend.models.font import Font
from backend.models.font_removal import FontRemoval, removal_scope
from backend.schemas.removals import FontRemovalResponse, RemovalsConfirmed
from backend.services.ws_manager import ws_manager

router = APIRouter(prefix="/api/me/removals", tags=["removals"])


@router.get("", response_model=list[FontRemovalResponse])
async def list_my_removals(
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[FontRemovalResponse]:
    """Les polices que j'ai retirées de mes Mac, les plus récentes d'abord.

    Le token d'instance hérité voit le groupe des appareils sans compte.
    """
    rows = await db.execute(
        select(FontRemoval, Font, Device.name)
        .join(Font, Font.id == FontRemoval.font_id)
        .outerjoin(Device, Device.id == FontRemoval.source_device_id)
        .where(removal_scope(principal.user_id))
        .order_by(FontRemoval.removed_at.desc())
    )
    return [
        FontRemovalResponse(
            font_id=font.id,
            family_name=font.family_name,
            full_name=font.full_name,
            original_filename=font.original_filename,
            removed_at=removal.removed_at,
            confirmed=removal.confirmed,
            source_device_name=device_name,
        )
        for removal, font, device_name in rows.all()
    ]


@router.post("/confirm", response_model=RemovalsConfirmed)
async def confirm_my_removals(
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> RemovalsConfirmed:
    """Confirme mes retraits en attente : mes Mac qui l'acceptent désinstallent."""
    result = await db.execute(
        update(FontRemoval)
        .where(removal_scope(principal.user_id), FontRemoval.confirmed.is_(False))
        .values(confirmed=True)
    )
    await db.commit()
    count = result.rowcount or 0
    if count:
        await ws_manager.broadcast_sync()
    return RemovalsConfirmed(confirmed=count)


@router.delete("/{font_id}", status_code=204)
async def undo_my_removal(
    font_id: uuid.UUID,
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Annule un retrait : mes Mac peuvent de nouveau l'installer (`auto_pull`)."""
    removal = (
        await db.execute(
            select(FontRemoval).where(
                removal_scope(principal.user_id), FontRemoval.font_id == font_id
            )
        )
    ).scalar_one_or_none()
    if removal is None:
        raise HTTPException(status_code=404, detail="Retrait introuvable.")
    await db.delete(removal)
    await db.commit()
    await ws_manager.broadcast_sync()
