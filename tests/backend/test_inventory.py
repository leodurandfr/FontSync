"""Réconciliation de `device_fonts` avec la déclaration d'un appareil (L1).

Ces tests suivent §7.2 de `docs/PLAN-ETATS-FONTS.md` : arrivées, départs, et le
domaine que la réconciliation ne touche jamais (les polices actives, terrain
exclusif de `detect_local_deletions`).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.schemas.sync import DeviceFontEntry
from backend.services.deletion_propagation import detect_local_deletions
from backend.services.font_importer import import_font
from backend.services.inventory import reconcile_inventory
from backend.services.sync_manager import compute_delta, register_device_font


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


async def _association(db, device_id, font_id) -> DeviceFont | None:
    result = await db.execute(
        select(DeviceFont).where(
            DeviceFont.device_id == device_id, DeviceFont.font_id == font_id
        )
    )
    return result.scalar_one_or_none()


# =====================================================================
# Arrivées
# =====================================================================


@pytest.mark.asyncio
async def test_declared_font_without_association_gets_one(
    db, storage, font_factory
) -> None:
    """Une police déjà connue mais jamais transférée (le trou d'`already_synced`)
    obtient enfin son association."""
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Already")
    await db.commit()
    assert await _association(db, device.id, font.id) is None

    stats = await reconcile_inventory(
        device.id,
        [DeviceFontEntry(hash=font.file_hash, filename="Already.ttf")],
        db,
    )

    assert stats.arrivals == 1
    association = await _association(db, device.id, font.id)
    assert association is not None
    assert association.ingestible is True
    assert association.local_path == "Already.ttf"
    # Borne inférieure vraie, pas « maintenant » : l'association existait déjà
    # en pratique, on ne fait que la rendre visible au registre.
    assert association.installed_at == font.created_at


@pytest.mark.asyncio
async def test_declared_tombstone_gets_its_association(
    db, storage, font_factory
) -> None:
    """Une pierre tombale déclarée obtient une association — le geste qui
    protège son fichier tant que cette machine le détient encore."""
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Tombstone")
    font.deleted_at = datetime.now(timezone.utc)
    font.deletion_confirmed = True
    await db.commit()

    stats = await reconcile_inventory(
        device.id,
        [DeviceFontEntry(hash=font.file_hash, filename="Tombstone.ttf")],
        db,
    )

    assert stats.arrivals == 1
    assert await _association(db, device.id, font.id) is not None


# =====================================================================
# Départs
# =====================================================================


@pytest.mark.asyncio
async def test_undeclared_tombstone_loses_its_association(
    db, storage, font_factory
) -> None:
    """Une pierre tombale non déclarée perd son association — sans quarantaine
    ni notification, il n'y a rien à quarantiner : elle est déjà hors
    bibliothèque."""
    device = await _make_device(db)
    gone = await _make_font(db, storage, font_factory, "Gone")
    kept = await _make_font(db, storage, font_factory, "Kept")
    await register_device_font(device.id, gone.id, "Gone.ttf", db)
    await register_device_font(device.id, kept.id, "Kept.ttf", db)
    gone.deleted_at = datetime.now(timezone.utc)
    gone.deletion_confirmed = True
    await db.commit()

    stats = await reconcile_inventory(
        device.id,
        [DeviceFontEntry(hash=kept.file_hash, filename="Kept.ttf")],
        db,
    )

    assert stats.departs == 1
    assert await _association(db, device.id, gone.id) is None
    assert await _association(db, device.id, kept.id) is not None


@pytest.mark.asyncio
async def test_active_undeclared_font_is_untouched(db, storage, font_factory) -> None:
    """Une police ACTIVE non déclarée n'est jamais touchée par la
    réconciliation : c'est le domaine exclusif de `detect_local_deletions`,
    avec son seuil et sa quarantaine."""
    device = await _make_device(db)
    active = await _make_font(db, storage, font_factory, "Active")
    other = await _make_font(db, storage, font_factory, "Other")
    await register_device_font(device.id, active.id, "Active.ttf", db)
    await db.commit()

    stats = await reconcile_inventory(
        device.id,
        [DeviceFontEntry(hash=other.file_hash, filename="Other.ttf")],
        db,
    )

    assert stats.departs == 0
    assert await _association(db, device.id, active.id) is not None


# =====================================================================
# Mise à jour et déduplication
# =====================================================================


@pytest.mark.asyncio
async def test_existing_association_is_updated_in_place(
    db, storage, font_factory
) -> None:
    """`local_path`/`ingestible` divergents sont mis à jour, sans recréer la
    ligne (et donc sans toucher `installed_at`)."""
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Moved")
    await register_device_font(device.id, font.id, "/old/Moved.ttf", db)
    await db.commit()
    original_installed_at = (await _association(db, device.id, font.id)).installed_at

    stats = await reconcile_inventory(
        device.id,
        [
            DeviceFontEntry(
                hash=font.file_hash,
                filename="Moved.ttf",
                local_path="/new/Moved.ttf",
                ingestible=False,
            )
        ],
        db,
    )

    assert stats.updates == 1
    assert stats.arrivals == 0
    association = await _association(db, device.id, font.id)
    assert association.local_path == "/new/Moved.ttf"
    assert association.ingestible is False
    assert association.installed_at == original_installed_at


@pytest.mark.asyncio
async def test_duplicate_hash_ingestible_wins(db, storage, font_factory) -> None:
    """Une police installée à la fois pour l'utilisateur et pour tous produit
    deux entrées du même hash — `ingestible=True` doit toujours l'emporter,
    quel que soit l'ordre de déclaration."""
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Both")
    await db.commit()

    stats = await reconcile_inventory(
        device.id,
        [
            DeviceFontEntry(hash=font.file_hash, filename="Both.ttf", ingestible=True),
            DeviceFontEntry(
                hash=font.file_hash,
                filename="Both.ttf",
                local_path="/Library/Fonts/Both.ttf",
                ingestible=False,
            ),
        ],
        db,
    )

    assert stats.arrivals == 1
    association = await _association(db, device.id, font.id)
    assert association.ingestible is True


# =====================================================================
# Commutativité avec la détection
# =====================================================================


@pytest.mark.asyncio
async def test_reconciliation_and_detection_are_commutative(
    db, storage, font_factory
) -> None:
    """Le même scénario, dans les deux ordres, donne le même état final.

    `detect_local_deletions` ne touche que (associée ∧ active ∧ non
    déclarée), `reconcile_inventory` n'insère que du déclaré et ne supprime
    que du tombé : ensembles disjoints par construction. Une réconciliation
    placée avant la détection élaguerait les associations que la détection
    doit lire — la propagation des suppressions mourrait en silence.
    """

    async def _run(order: str) -> tuple[bool, bool]:
        device = await _make_device(db, hostname=f"mac-{order}")
        disappearing = await _make_font(db, storage, font_factory, f"Vanish-{order}")
        tombstone = await _make_font(db, storage, font_factory, f"Tomb-{order}")
        tombstone.deleted_at = datetime.now(timezone.utc)
        tombstone.deletion_confirmed = True
        kept = await _make_font(db, storage, font_factory, f"Kept-{order}")
        await register_device_font(device.id, disappearing.id, "Vanish.ttf", db)
        await register_device_font(device.id, kept.id, "Kept.ttf", db)
        await db.commit()

        declared = {kept.file_hash, tombstone.file_hash}
        entries = [
            DeviceFontEntry(hash=kept.file_hash, filename="Kept.ttf"),
            DeviceFontEntry(hash=tombstone.file_hash, filename="Tomb.ttf"),
        ]

        if order == "detect-first":
            await detect_local_deletions(device.id, declared, db)
            await reconcile_inventory(device.id, entries, db)
        else:
            await reconcile_inventory(device.id, entries, db)
            await detect_local_deletions(device.id, declared, db)
        await db.commit()

        vanished_quarantined = (
            await _association(db, device.id, disappearing.id)
        ) is None
        tombstone_associated = (
            await _association(db, device.id, tombstone.id)
        ) is not None
        return vanished_quarantined, tombstone_associated

    assert await _run("detect-first") == await _run("reconcile-first")


# =====================================================================
# Asymétrie `ingestible` dans `compute_delta`
# =====================================================================


@pytest.mark.asyncio
async def test_non_ingestible_hash_never_offered_for_push(
    db, storage, font_factory
) -> None:
    """`ingestible=False` retire une police inconnue du serveur de
    `unknown_to_server` — mais seulement de là : elle reste déclarée, donc ne
    tombe ni dans `missing_on_device` ni dans une détection de suppression."""
    entries = [
        DeviceFontEntry(hash="a" * 64, filename="system.ttf", ingestible=False),
        DeviceFontEntry(hash="b" * 64, filename="user.ttf", ingestible=True),
    ]

    delta = await compute_delta(entries, db)

    assert delta.unknown_to_server == ["b" * 64]
    assert delta.missing_on_device == []
