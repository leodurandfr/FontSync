"""Tests du router stats (`backend/routers/stats.py`).

Vérifie l'agrégation portable SQLite (total, format, classification, script),
y compris l'exclusion des fonts soft-deleted et la robustesse de l'agrégation
applicative des scripts.
"""

import pytest

from backend.routers.stats import get_stats
from backend.services.font_importer import import_font


@pytest.mark.asyncio
async def test_stats_empty_library(db) -> None:
    """Bibliothèque vide : tout à zéro."""
    stats = await get_stats(db)
    assert stats.total_fonts == 0
    assert stats.by_classification == []
    assert stats.by_format == []
    assert stats.by_script == []


@pytest.mark.asyncio
async def test_stats_counts_and_groups(db, storage, font_factory) -> None:
    """Total, regroupement par format, classification et script."""
    sans1 = font_factory(family="Acme Grotesk", subfamily="Regular")
    sans2 = font_factory(family="Acme Grotesk", subfamily="Bold", weight_class=700)
    mono = font_factory(family="Code Mono", subfamily="Regular", monospace=True)

    await import_font("sans1.ttf", sans1, storage, db)
    await import_font("sans2.ttf", sans2, storage, db)
    await import_font("mono.ttf", mono, storage, db)

    stats = await get_stats(db)

    assert stats.total_fonts == 3

    by_format = {f.format: f.count for f in stats.by_format}
    assert by_format == {"ttf": 3}

    by_classification = {c.classification: c.count for c in stats.by_classification}
    assert by_classification.get("sans-serif") == 2
    assert by_classification.get("monospace") == 1

    # Les trois fonts couvrent l'alphabet latin → script « latin ».
    by_script = {s.script: s.count for s in stats.by_script}
    assert by_script.get("latin") == 3


@pytest.mark.asyncio
async def test_stats_excludes_soft_deleted(db, storage, font_factory) -> None:
    """Une font soft-deleted ne compte plus dans les stats."""
    from datetime import datetime, timezone

    keep = font_factory(family="Keep", subfamily="Regular")
    drop = font_factory(family="Drop", subfamily="Regular")
    await import_font("keep.ttf", keep, storage, db)
    dropped, _ = await import_font("drop.ttf", drop, storage, db)

    dropped.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    stats = await get_stats(db)
    assert stats.total_fonts == 1
