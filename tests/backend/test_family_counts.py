"""Tests de `GET /api/font-families/counts` (compteurs de la barre latérale)."""

import pytest

from backend.routers.font_families import count_families
from backend.services.font_importer import import_font


@pytest.mark.asyncio
async def test_counts_empty_library(db) -> None:
    """Bibliothèque vide : aucun compteur."""
    counts = await count_families(db)
    assert counts.total == 0
    assert counts.by_classification == {}


@pytest.mark.asyncio
async def test_counts_families_not_styles(db, storage, font_factory) -> None:
    """On compte des familles : deux styles d'une même famille comptent pour un."""
    await import_font(
        "a.ttf", font_factory(family="Acme Grotesk", subfamily="Regular"), storage, db
    )
    await import_font(
        "b.ttf",
        font_factory(family="Acme Grotesk", subfamily="Bold", weight_class=700),
        storage,
        db,
    )
    await import_font(
        "c.ttf",
        font_factory(family="Code Mono", subfamily="Regular", monospace=True),
        storage,
        db,
    )

    counts = await count_families(db)

    assert counts.total == 2
    assert counts.by_classification.get("sans-serif") == 1
    assert counts.by_classification.get("monospace") == 1
