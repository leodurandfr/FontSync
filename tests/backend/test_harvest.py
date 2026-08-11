"""Récolte des pierres tombales.

Cf. `docs/PLAN-ETATS-FONTS.md` §3.4 pour la condition complète et ses neuf
garde-fous. Le premier bloc couvre la version INERTE de L1/L2 (aperçu, aucune
suppression, flag éteint — cinq garde-fous mesurables : G3, G4, G5, G6, G7).
Le second bloc (« L5 ») couvre la récolte réellement activée : G1-G9 au
complet, §7.4 items 22-31.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.config import settings
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.models.font_family import FontFamily, FontFamilyMember
from backend.schemas.sync import DeviceFontEntry
from backend.services.font_importer import import_font
from backend.services.harvest import harvest_tombstones
from backend.services.inventory import reconcile_inventory
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


# ---------- L5 — récolte activée (§7.4, items 22-31) ----------
#
# `db.get()` consulte d'abord l'identity map de la session (`expire_on_commit`
# vaut `False`, cf. `conftest.py`) : après une suppression faite au niveau Core
# (`delete()`, pas `db.delete(obj)`), il renverrait l'instance périmée au lieu
# de `None`. `_font_exists`/`_family_exists` forcent un aller-retour SQL réel.


def _enable_harvest(
    monkeypatch, *, grace_hours: float = 0, max_per_pass: int = 5
) -> None:
    monkeypatch.setattr(settings, "tombstone_harvest_enabled", True)
    monkeypatch.setattr(settings, "tombstone_harvest_grace_hours", grace_hours)
    monkeypatch.setattr(settings, "tombstone_harvest_max_per_pass", max_per_pass)


async def _font_exists(db, font_id) -> bool:
    result = await db.execute(select(Font.id).where(Font.id == font_id))
    return result.scalar_one_or_none() is not None


async def _family_exists(db, family_id) -> bool:
    result = await db.execute(select(FontFamily.id).where(FontFamily.id == family_id))
    return result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_l5_ingestible_holder_blocks_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G6 : un détenteur ingestible protège la tombe — jamais candidate, donc
    jamais récoltée, même le flag activé."""
    _enable_harvest(monkeypatch)
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "L5Ingestible")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await register_device_font(device.id, tomb.id, "L5Ingestible.ttf", db)
    await db.commit()

    assert await harvest_tombstones(db) == 0
    await db.refresh(tomb)
    assert tomb.harvest_candidate_since is None
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_non_ingestible_only_holder_is_harvestable(
    db, storage, font_factory, monkeypatch
) -> None:
    """Le pendant de G6 : un détenteur NON ingestible (ex. `/Library/Fonts`) ne
    protège pas — la tombe reste récoltable."""
    _enable_harvest(monkeypatch)
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "L5NonIngestible")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    db.add(
        DeviceFont(
            device_id=device.id,
            font_id=tomb.id,
            local_path="L5NonIngestible.ttf",
            ingestible=False,
        )
    )
    await db.commit()

    assert await harvest_tombstones(db) == 1
    assert not await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_undeclared_live_device_blocks_candidacy(
    db, storage, font_factory, monkeypatch
) -> None:
    """G7 : tant qu'un appareil vivant n'a pas redéclaré depuis la
    suppression, la candidature ne s'ouvre même pas."""
    _enable_harvest(monkeypatch)
    await _make_device(db)  # last_declaration_at reste NULL
    tomb = await _make_tombstone(db, storage, font_factory, "L5Undeclared")
    await db.commit()

    assert await harvest_tombstones(db) == 0
    await db.refresh(tomb)
    assert tomb.harvest_candidate_since is None
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_not_purged_blocks_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G3 : le fichier doit avoir quitté le stockage — sinon récolter la ligne
    abandonnerait le blob."""
    _enable_harvest(monkeypatch)
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "L5StillStored")
    font.deleted_at = datetime.now(timezone.utc)
    font.deletion_confirmed = True
    # `purged_at` volontairement absent.
    device.last_declaration_at = font.deleted_at + timedelta(seconds=1)
    await db.commit()

    assert await harvest_tombstones(db) == 0
    assert await _font_exists(db, font.id)


@pytest.mark.asyncio
async def test_l5_unconfirmed_deletion_blocks_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G4 : une quarantaine en attente n'est jamais candidate."""
    _enable_harvest(monkeypatch)
    device = await _make_device(db)
    tomb = await _make_tombstone(
        db, storage, font_factory, "L5Pending", confirmed=False
    )
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    assert await harvest_tombstones(db) == 0
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_no_live_device_blocks_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G5 : sur un serveur sans appareil vivant, G6/G7 seraient vrais par
    vacuité — rien ne doit partir."""
    _enable_harvest(monkeypatch)
    tomb = await _make_tombstone(db, storage, font_factory, "L5Orphan")
    await db.commit()

    assert await harvest_tombstones(db) == 0
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_max_per_pass_caps_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G9 : la récolte ne dépasse jamais le plafond par passe, même avec plus
    de candidats mûrs — il en faut plusieurs cycles pour tout drainer."""
    _enable_harvest(monkeypatch, max_per_pass=2)
    device = await _make_device(db)
    tombs = [
        await _make_tombstone(db, storage, font_factory, f"L5Capped{i}")
        for i in range(4)
    ]
    device.last_declaration_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    await db.commit()

    assert await harvest_tombstones(db) == 2
    survivors = [t for t in tombs if await _font_exists(db, t.id)]
    assert len(survivors) == 2

    # Deuxième passe : draine le reste (candidature déjà ouverte pour tous en
    # phase 1 de la première passe, seule la phase 2 était plafonnée).
    assert await harvest_tombstones(db) == 2
    assert not any([await _font_exists(db, t.id) for t in tombs])


@pytest.mark.asyncio
async def test_l5_grace_period_blocks_harvest(
    db, storage, font_factory, monkeypatch
) -> None:
    """G8 : la candidature s'ouvre, mais tant que le délai de grâce n'est pas
    écoulé, rien n'est récolté."""
    _enable_harvest(monkeypatch, grace_hours=24)
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "L5Grace")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    # Premier cycle : ouvre la candidature, ne récolte rien (délai non écoulé).
    assert await harvest_tombstones(db) == 0
    await db.refresh(tomb)
    assert tomb.harvest_candidate_since is not None
    assert await _font_exists(db, tomb.id)

    # Second cycle immédiat : aucune heure ne s'est écoulée, toujours rien.
    assert await harvest_tombstones(db) == 0
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_redeclaration_after_omission_is_never_harvested(
    db, storage, font_factory, monkeypatch
) -> None:
    """G8, le test le plus important du lot : une tombe dont l'unique
    détenteur ingestible omet UNE déclaration puis la reprend n'est jamais
    récoltée — quand bien même le délai de grâce de la candidature ouverte
    entre-temps finirait par s'écouler."""
    _enable_harvest(monkeypatch, grace_hours=24)
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "L5Redeclare")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    # Cycle d'omission : aucun détenteur ingestible déclaré → la candidature
    # s'ouvre, mais le délai de grâce (24h) n'est pas encore écoulé.
    assert await harvest_tombstones(db) == 0
    await db.refresh(tomb)
    assert tomb.harvest_candidate_since is not None

    # Le même appareil redéclare le hash : la réconciliation recrée
    # l'association ET remet la candidature à zéro (`services/inventory.py`).
    await reconcile_inventory(
        device.id,
        [
            DeviceFontEntry(
                hash=tomb.file_hash, filename="L5Redeclare.ttf", ingestible=True
            )
        ],
        db,
    )
    device.last_declaration_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tomb)
    assert tomb.harvest_candidate_since is None

    # Récolte rejouée : la tombe survit, protégée par le détenteur ingestible
    # retrouvé (G6) — plus aucune candidature à faire mûrir (G8).
    assert await harvest_tombstones(db) == 0
    assert await _font_exists(db, tomb.id)


@pytest.mark.asyncio
async def test_l5_harvest_cleans_up_empty_auto_grouped_family(
    db, storage, font_factory, monkeypatch
) -> None:
    """Nettoyage : `font_family_members` retiré, `style_count` recalé, et la
    famille auto-groupée devenue vide disparaît avec sa tombe — sans violer
    aucune contrainte de clé étrangère (`PRAGMA foreign_keys=ON` en test,
    cf. `conftest.py`)."""
    _enable_harvest(monkeypatch)
    device = await _make_device(db)
    tomb = await _make_tombstone(db, storage, font_factory, "L5FamilyCleanup")
    device.last_declaration_at = tomb.deleted_at + timedelta(seconds=1)
    await db.commit()

    member_result = await db.execute(
        select(FontFamilyMember).where(FontFamilyMember.font_id == tomb.id)
    )
    member = member_result.scalar_one()
    family_id = member.family_id
    family = await db.get(FontFamily, family_id)
    assert family is not None
    assert family.is_auto_grouped is True
    assert family.style_count == 1

    assert await harvest_tombstones(db) == 1

    assert not await _font_exists(db, tomb.id)
    remaining_member = await db.execute(
        select(FontFamilyMember).where(FontFamilyMember.font_id == tomb.id)
    )
    assert remaining_member.scalar_one_or_none() is None
    assert not await _family_exists(db, family_id)
