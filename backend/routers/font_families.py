"""Router pour les familles de polices."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.font_family import RegroupStats
from backend.services.family_grouper import regroup_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/font-families", tags=["font-families"])


@router.post("/regroup", response_model=RegroupStats)
async def regroup_fonts(
    db: AsyncSession = Depends(get_db),
) -> RegroupStats:
    """Regroupe toutes les fonts en familles.

    Utile après la migration initiale ou pour recalculer les familles
    après un import massif.
    """
    stats = await regroup_all(db)
    await db.commit()
    return RegroupStats(**stats)
