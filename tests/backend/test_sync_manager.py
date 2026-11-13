"""Tests de la sémantique de delta-sync (`backend/services/sync_manager.py`).

Vérifie les trois ensembles (`unknown_to_server`, `missing_on_device`,
`already_synced`) et le fait que `compute_delta` est une **lecture pure** :
aucune association `device_fonts` n'est créée (régression A4).
"""

import hashlib
import uuid

import pytest
from sqlalchemy import func, select

from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.schemas.sync import DeviceFontEntry
from backend.services.font_importer import import_font
from backend.services.sync_manager import compute_delta

# Appareil quelconque : la plupart des tests ci-dessous ne portent pas sur
# to_deactivate (qui exige une ligne device_fonts réelle) et n'ont besoin que
# d'un device_id syntaxiquement valide.
_DEVICE_ID = uuid.uuid4()


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

    delta = await compute_delta(device_fonts, db, device_id=_DEVICE_ID)

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

    await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="solo.ttf")],
        db,
        device_id=_DEVICE_ID,
    )

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

    delta = await compute_delta([], db, device_id=_DEVICE_ID)

    assert delta.missing_on_device == []
    assert delta.unknown_to_server == []
    assert delta.already_synced == 0


@pytest.mark.asyncio
async def test_compute_delta_empty_server(db, font_factory) -> None:
    """Serveur vide : toutes les fonts du device sont inconnues."""
    h = _fake_hash("only-on-device")
    delta = await compute_delta(
        [DeviceFontEntry(hash=h, filename="x.ttf")], db, device_id=_DEVICE_ID
    )

    assert delta.unknown_to_server == [h]
    assert delta.missing_on_device == []
    assert delta.already_synced == 0


# ---------- to_deactivate : état désiré device_fonts.active ----------


async def _register(
    db, device_id: uuid.UUID, font_id: uuid.UUID, *, active: bool
) -> None:
    db.add(Device(id=device_id, name="Test", hostname="test", os="macos"))
    db.add(
        DeviceFont(
            device_id=device_id,
            font_id=font_id,
            local_path="x.ttf",
            active=active,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_to_deactivate_includes_inactive_declared_font(
    db, storage, font_factory
) -> None:
    """Une police désactivée sur CET appareil (active=False) et toujours
    déclarée par lui doit apparaître dans to_deactivate."""
    data = font_factory(family="Muted", subfamily="Regular")
    font, _ = await import_font("muted.ttf", data, storage, db)
    device_id = uuid.uuid4()
    await _register(db, device_id, font.id, active=False)

    delta = await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="muted.ttf")],
        db,
        device_id=device_id,
    )

    assert [ref.file_hash for ref in delta.to_deactivate] == [font.file_hash]


@pytest.mark.asyncio
async def test_to_deactivate_excludes_active_font(db, storage, font_factory) -> None:
    """Une police active (le défaut) n'a rien à faire dans to_deactivate."""
    data = font_factory(family="Loud", subfamily="Regular")
    font, _ = await import_font("loud.ttf", data, storage, db)
    device_id = uuid.uuid4()
    await _register(db, device_id, font.id, active=True)

    delta = await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="loud.ttf")],
        db,
        device_id=device_id,
    )

    assert delta.to_deactivate == []


@pytest.mark.asyncio
async def test_to_deactivate_scoped_to_own_device(db, storage, font_factory) -> None:
    """L'état désactivé d'un AUTRE appareil ne doit jamais fuiter ici."""
    data = font_factory(family="Elsewhere", subfamily="Regular")
    font, _ = await import_font("elsewhere.ttf", data, storage, db)
    other_device_id = uuid.uuid4()
    await _register(db, other_device_id, font.id, active=False)

    delta = await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="elsewhere.ttf")],
        db,
        device_id=uuid.uuid4(),
    )

    assert delta.to_deactivate == []


@pytest.mark.asyncio
async def test_to_deactivate_gated_by_device_hashes(db, storage, font_factory) -> None:
    """Une police active=False mais que le device ne déclare plus n'a pas à
    ressortir ici — même gating que to_uninstall, par symétrie."""
    data = font_factory(family="Gone", subfamily="Regular")
    font, _ = await import_font("gone.ttf", data, storage, db)
    device_id = uuid.uuid4()
    await _register(db, device_id, font.id, active=False)

    delta = await compute_delta([], db, device_id=device_id)

    assert delta.to_deactivate == []


def _flavored(ttf: bytes, flavor: str | None) -> bytes:
    """Re-encode a generated TTF (WOFF via zlib; None keeps the sfnt)."""
    import io

    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(ttf))
    font.flavor = flavor
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _collection(*ttfs: bytes) -> bytes:
    """Build a real TrueType collection (.ttc) from generated TTFs."""
    import io

    from fontTools.ttLib import TTFont
    from fontTools.ttLib.ttCollection import TTCollection

    collection = TTCollection()
    collection.fonts = [TTFont(io.BytesIO(data)) for data in ttfs]
    out = io.BytesIO()
    collection.save(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_missing_on_device_never_offers_web_fonts(
    db, storage, font_factory
) -> None:
    """WOFF/WOFF2 are stored and previewable, never offered for installation."""
    woff = _flavored(font_factory(family="WebOnly"), "woff")
    # No brotli in the test venv: a WOFF2 header is enough, the importer keeps
    # malformed fonts with partial metadata.
    woff2 = b"wOF2" + hashlib.sha256(b"woff2").digest() * 4
    ttf = font_factory(family="Desk")
    otf_named = font_factory(family="DeskOtf")
    ttc = _collection(font_factory(family="CollA"), font_factory(family="CollB"))

    imported = {}
    for name, data in (
        ("web.woff", woff),
        ("web.woff2", woff2),
        ("desk.ttf", ttf),
        ("desk.otf", otf_named),
        ("coll.ttc", ttc),
    ):
        font, _ = await import_font(name, data, storage, db)
        imported[font.file_format] = font.file_hash

    delta = await compute_delta([], db, device_id=_DEVICE_ID)

    offered = {ref.file_hash for ref in delta.missing_on_device}
    assert imported["woff"] not in offered
    assert imported["woff2"] not in offered
    assert {imported["ttf"], imported["otf"], imported["ttc"]} <= offered


# ---------- Couche non gérée : jamais dans toUninstall ni au push (P1-3c) ----------


@pytest.mark.asyncio
async def test_to_uninstall_skips_non_ingestible_only_holder(
    db, storage, font_factory
) -> None:
    from datetime import datetime, timezone

    data = font_factory(family="Gone Shared")
    font, _ = await import_font("gone.ttf", data, storage, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deletion_confirmed = True
    await db.commit()

    delta = await compute_delta(
        [
            DeviceFontEntry(
                hash=font.file_hash,
                filename="gone.ttf",
                local_path="/Library/Fonts/gone.ttf",
                ingestible=False,
            )
        ],
        db,
        device_id=uuid.uuid4(),
        propagate_deletions=True,
    )

    assert delta.to_uninstall == []


async def _post_delta(api_client, device_id: str, fonts: list[dict]) -> dict:
    from tests.backend.conftest import AUTH_HEADERS

    resp = await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={"deviceId": device_id, "fonts": fonts},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _new_device(api_client) -> str:
    from tests.backend.conftest import AUTH_HEADERS

    resp = await api_client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac", "hostname": f"mac-{uuid.uuid4().hex[:6]}", "os": "macos"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_legacy_agent_library_fonts_not_offered_for_push(api_client) -> None:
    """Agent pré-L3 : pas de champ `ingestible`. Ce qu'il déclare sous
    /Library/Fonts ou /System/Library n'est jamais proposé au push."""
    device = await _new_device(api_client)

    delta = await _post_delta(
        api_client,
        device,
        [
            {
                "hash": "a" * 64,
                "filename": "u.ttf",
                "localPath": "/Library/Fonts/u.ttf",
            },
            {
                "hash": "b" * 64,
                "filename": "s.ttf",
                "localPath": "/System/Library/Fonts/s.ttf",
            },
            {
                "hash": "d" * 64,
                "filename": "m.ttf",
                "localPath": "/Users/x/Library/Fonts/m.ttf",
            },
        ],
    )

    assert delta["unknownToServer"] == ["d" * 64]


@pytest.mark.asyncio
async def test_legacy_agent_library_fonts_association_stays_ingestible(
    db, storage, font_factory
) -> None:
    """La réconciliation garde `entry.ingestible` (défaut True) pour un agent
    pré-L3 : la protection des tombes qu'il détient reste intacte."""
    from sqlalchemy import select

    from backend.models.device_font import DeviceFont
    from backend.services.inventory import reconcile_inventory

    font, _ = await import_font(
        "known.ttf", font_factory(family="Legacy Known"), storage, db
    )
    device_id = uuid.uuid4()
    db.add(Device(id=device_id, name="Mac", hostname="legacy", os="macos"))
    await db.flush()
    entry = DeviceFontEntry.model_validate(
        {
            "hash": font.file_hash,
            "filename": "known.ttf",
            "localPath": "/Library/Fonts/known.ttf",
        }
    )

    await reconcile_inventory(device_id, [entry], db)

    row = (
        await db.execute(
            select(DeviceFont.ingestible).where(
                DeviceFont.device_id == device_id, DeviceFont.font_id == font.id
            )
        )
    ).scalar_one()
    assert row is True


@pytest.mark.asyncio
async def test_explicit_ingestible_library_fonts_still_offered(api_client) -> None:
    device = await _new_device(api_client)

    delta = await _post_delta(
        api_client,
        device,
        [
            {
                "hash": "c" * 64,
                "filename": "u.ttf",
                "localPath": "/Library/Fonts/u.ttf",
                "ingestible": True,
            }
        ],
    )

    assert delta["unknownToServer"] == ["c" * 64]


@pytest.mark.asyncio
async def test_to_uninstall_keeps_hash_also_held_in_managed_layer(
    db, storage, font_factory
) -> None:
    """Même police dans ~/Library/Fonts ET /Library/Fonts : la copie gérée reste
    à désinstaller (l'agent ne touche que ~/Library/Fonts et disabled/)."""
    from datetime import datetime, timezone

    font, _ = await import_font("both.ttf", font_factory(family="Both"), storage, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deletion_confirmed = True
    await db.commit()

    delta = await compute_delta(
        [
            DeviceFontEntry(
                hash=font.file_hash,
                filename="both.ttf",
                local_path="/Library/Fonts/both.ttf",
                ingestible=False,
            ),
            DeviceFontEntry(
                hash=font.file_hash,
                filename="both.ttf",
                local_path="/Users/x/Library/Fonts/both.ttf",
                ingestible=True,
            ),
        ],
        db,
        device_id=uuid.uuid4(),
        propagate_deletions=True,
    )

    assert [ref.file_hash for ref in delta.to_uninstall] == [font.file_hash]
