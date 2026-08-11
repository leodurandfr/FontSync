"""Récolte des pierres tombales — version INERTE de L1/L2 (aperçu, aucune suppression).

Cf. `docs/PLAN-ETATS-FONTS.md` §3.4 pour la condition complète et ses neuf
garde-fous ; cette version n'en mesure que les cinq déjà disponibles avant
l'activation de la récolte en L5 (G3, G4, G5, G6, G7).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.device import Device
from backend.models.font import DELETION_MANUAL, DELETION_PENDING, Font
from backend.services.font_importer import import_font
from backend.services.harvest import harvest_tombstones
from backend.services.sync_manager import register_device_font


async def _make_device(db, *, hostname: str = "mac") -> Device:
    device = Device(name="Mac", hostname=hostname, os="macos")
    db.add(device)
    await db.flush()
    return device


async def _make_font(db, storage, font_factory, family: str) -> Font:
    font, _ = await import_font(
        f"{family}.ttf", font_factory(family=family), storage, db
    )
    return font


async def _make_tombstone(
    db, storage, font_factory, family: str, *, confirmed: bool = True
) -> Font:
    font = await _make_font(db, storage, font_factory, family)
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL if confirmed else DELETION_PENDING
    font.deletion_confirmed = confirmed
    font.purged_at = datetime.now(timezone.utc)
    return font


@pytest.mark.asyncio
async def test_harvest_never_deletes_anything(db, storage, font_factory) -> None:
    """La version L1 est un aperçu : quel que soit le résultat, aucune ligne
    `fonts` ne disparaît."""
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "Ripe")
    # G7 exige une déclaration APRÈS la suppression, pas avant.
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    count = await harvest_tombstones(db)

    assert count == 1
    assert await db.get(Font, tomb.id) is not None


@pytest.mark.asyncio
async def test_ingestible_holder_blocks_the_count(db, storage, font_factory) -> None:
    """G6 : un détenteur ingestible protège la tombe."""
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "Protected")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await register_device_font(device.id, tomb.id, "Protected.ttf", db)
    await db.commit()

    assert await harvest_tombstones(db) == 0


@pytest.mark.asyncio
async def test_undeclared_live_device_blocks_the_count(
    db, storage, font_factory
) -> None:
    """G7 : tant qu'un appareil vivant n'a pas redéclaré depuis la suppression,
    rien n'est récoltable — il pourrait encore détenir le fichier."""
    await _make_device(db)  # last_declaration_at reste NULL
    await _make_tombstone(db, storage, font_factory, "Waiting")
    await db.commit()

    assert await harvest_tombstones(db) == 0


@pytest.mark.asyncio
async def test_unconfirmed_deletion_blocks_the_count(db, storage, font_factory) -> None:
    """G4 : une quarantaine en attente n'est jamais candidate."""
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "Pending", confirmed=False)
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    assert await harvest_tombstones(db) == 0


@pytest.mark.asyncio
async def test_not_yet_purged_blocks_the_count(db, storage, font_factory) -> None:
    """G3 : le fichier doit avoir quitté le stockage — sinon récolter la ligne
    abandonnerait le blob."""
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "StillStored")
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    font.deletion_confirmed = True
    # `purged_at` volontairement absent.
    device.last_declaration_at = font.deleted_at + timedelta(seconds=1)
    await db.commit()

    assert await harvest_tombstones(db) == 0


@pytest.mark.asyncio
async def test_no_live_device_blocks_the_count(db, storage, font_factory) -> None:
    """G5 : sur un serveur sans appareil vivant, G6/G7 seraient vrais par
    vacuité — rien ne doit partir."""
    await _make_tombstone(db, storage, font_factory, "Orphan")
    await db.commit()

    assert await harvest_tombstones(db) == 0
