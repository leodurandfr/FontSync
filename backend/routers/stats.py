"""Router pour les statistiques globales."""

from collections import Counter

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
    total_result = await db.execute(select(func.count(Font.id)).where(base_filter))
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
    by_format = [FormatStat(format=row[0], count=row[1]) for row in format_result.all()]

    # Par script (dénormalisation du JSON supported_scripts).
    # Agrégation applicative : portable SQLite, robuste aux valeurs non-tableaux.
    scripts_result = await db.execute(
        select(Font.supported_scripts).where(
            base_filter, Font.supported_scripts.isnot(None)
        )
    )
    script_counter: Counter[str] = Counter()
    for (scripts,) in scripts_result.all():
        if isinstance(scripts, list):
            script_counter.update(s for s in scripts if isinstance(s, str))
    by_script = [
        ScriptStat(script=script, count=count)
        for script, count in script_counter.most_common()
    ]

    return StatsResponse(
        total_fonts=total_fonts,
        by_classification=by_classification,
        by_format=by_format,
        by_script=by_script,
    )
