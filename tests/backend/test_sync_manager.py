"""Tests de la sémantique de delta-sync (`backend/services/sync_manager.py`).

Vérifie les trois ensembles (`unknown_to_server`, `missing_on_device`,
`already_synced`) et le fait que `compute_delta` est une **lecture pure** :
aucune association `device_fonts` n'est créée (régression A4).
"""

import hashlib

import pytest
from sqlalchemy import func, select

from backend.models.device_font import DeviceFont
from backend.schemas.sync import DeviceFontEntry
from backend.services.font_importer import import_font
from backend.services.sync_manager import compute_delta


def _fake_hash(seed: str) -> str:
    """Hash 64 caractères déterministe pour une font absente du serveur."""
    return hashlib.sha256(seed.encode()).hexdigest()


@pytest.mark.asyncio
async def test_compute_delta_three_sets(db, storage, font_factory) -> None:
    """Un hash commun, un hash serveur-only, un hash device-only."""
    shared = font_factory(family="Shared", subfamily="Regular")
    server_only = font_factory(family="ServerOnly", subfamily="Regular")

    shared_font, _ = await import_font("shared.ttf", shared, storage, db)
    server_font, _ = await import_font("server.ttf", server_only, storage, db)

    device_only_hash = _fake_hash("device-only")
    device_fonts = [
        DeviceFontEntry(hash=shared_font.file_hash, filename="shared.ttf"),
        DeviceFontEntry(hash=device_only_hash, filename="local.ttf"),
    ]

    delta = await compute_delta(device_fonts, db)

    # Device-only → à pusher vers le serveur.
    assert delta.unknown_to_server == [device_only_hash]
    # Server-only → à puller sur le device.
    assert [ref.file_hash for ref in delta.missing_on_device] == [server_font.file_hash]
    assert delta.missing_on_device[0].original_filename == "server.ttf"
    # Hash commun → déjà synchronisé.
    assert delta.already_synced == 1


@pytest.mark.asyncio
async def test_compute_delta_is_read_only(db, storage, font_factory) -> None:
    """compute_delta ne doit créer aucune association device_fonts (A4)."""
    data = font_factory(family="Solo", subfamily="Regular")
    font, _ = await import_font("solo.ttf", data, storage, db)

    await compute_delta([DeviceFontEntry(hash=font.file_hash, filename="solo.ttf")], db)

    count = await db.execute(select(func.count()).select_from(DeviceFont))
    assert (count.scalar() or 0) == 0


@pytest.mark.asyncio
async def test_compute_delta_ignores_soft_deleted(db, storage, font_factory) -> None:
    """Une font serveur soft-deleted ne doit pas apparaître dans missing_on_device."""
    from datetime import datetime, timezone

    data = font_factory(family="Gone", subfamily="Regular")
    font, _ = await import_font("gone.ttf", data, storage, db)
    font.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    delta = await compute_delta([], db)

    assert delta.missing_on_device == []
    assert delta.unknown_to_server == []
    assert delta.already_synced == 0


@pytest.mark.asyncio
async def test_compute_delta_empty_server(db, font_factory) -> None:
    """Serveur vide : toutes les fonts du device sont inconnues."""
    h = _fake_hash("only-on-device")
    delta = await compute_delta([DeviceFontEntry(hash=h, filename="x.ttf")], db)

    assert delta.unknown_to_server == [h]
    assert delta.missing_on_device == []
    assert delta.already_synced == 0
