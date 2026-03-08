"""Router pour les statistiques globales."""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.font import Font
from backend.schemas.font import (
    ClassificationStat,
    FormatStat,
    ScriptStat,
    StatsResponse,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Statistiques globales de la bibliothèque de fonts."""
    base_filter = Font.deleted_at.is_(None)

    # Total
    total_result = await db.execute(
        select(func.count(Font.id)).where(base_filter)
    )
    total_fonts = total_result.scalar() or 0

    # Par classification
    classif_result = await db.execute(
        select(Font.classification, func.count(Font.id))
        .where(base_filter)
        .group_by(Font.classification)
        .order_by(func.count(Font.id).desc())
    )
    by_classification = [
        ClassificationStat(classification=row[0], count=row[1])
        for row in classif_result.all()
    ]

    # Par format
    format_result = await db.execute(
        select(Font.file_format, func.count(Font.id))
        .where(base_filter)
        .group_by(Font.file_format)
        .order_by(func.count(Font.id).desc())
    )
    by_format = [
        FormatStat(format=row[0], count=row[1])
        for row in format_result.all()
    ]

    # Par script (dénormalisation du JSONB supported_scripts)
    script_result = await db.execute(
        select(
            func.jsonb_array_elements_text(Font.supported_scripts).label("script"),
            func.count(Font.id),
        )
        .where(base_filter, Font.supported_scripts.isnot(None))
        .group_by("script")
        .order_by(func.count(Font.id).desc())
    )
    by_script = [
        ScriptStat(script=row[0], count=row[1])
        for row in script_result.all()
    ]

    return StatsResponse(
        total_fonts=total_fonts,
        by_classification=by_classification,
        by_format=by_format,
        by_script=by_script,
    )
