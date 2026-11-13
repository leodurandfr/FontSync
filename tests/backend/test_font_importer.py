"""Tests du pipeline d'import (`backend/services/font_importer.py`).

Couvre : dédup/idempotence sur le hash, résurrection d'une font soft-deleted,
et la robustesse « une font malformée est stockée, jamais rejetée » (CLAUDE.md).
"""

import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.services.deletion_propagation import detect_local_deletions
from backend.services.font_importer import FontImportError, import_font
from backend.services.sync_manager import register_device_font


async def _count_fonts(db) -> int:
    result = await db.execute(select(func.count(Font.id)))
    return result.scalar() or 0


@pytest.mark.asyncio
async def test_import_real_font_parses_metadata(db, storage, font_factory) -> None:
    """Une vraie TTF est stockée avec ses métadonnées et le fichier sur disque."""
    data = font_factory(family="Acme Grotesk", subfamily="Bold", weight_class=700)

    font, is_duplicate = await import_font("Acme-Bold.ttf", data, storage, db)

    assert is_duplicate is False
    assert font.family_name == "Acme Grotesk"
    assert font.weight_class == 700
    assert font.file_format == "ttf"
    assert font.file_hash == hashlib.sha256(data).hexdigest()
    assert font.source == "upload"
    assert await storage.exists(font.file_hash, "ttf") is True


@pytest.mark.asyncio
async def test_import_is_idempotent_on_hash(db, storage, font_factory) -> None:
    """Réimporter un contenu identique → doublon, et une seule ligne en base."""
    data = font_factory(family="Inter", subfamily="Regular")

    font1, dup1 = await import_font("inter.ttf", data, storage, db)
    font2, dup2 = await import_font("inter-copy.ttf", data, storage, db)

    assert dup1 is False
    assert dup2 is True
    assert font2.id == font1.id
    assert await _count_fonts(db) == 1


@pytest.mark.asyncio
async def test_distinct_content_creates_distinct_fonts(
    db, storage, font_factory
) -> None:
    """Deux contenus différents → deux fonts (hash différent)."""
    a = font_factory(family="Alpha", subfamily="Regular")
    b = font_factory(family="Beta", subfamily="Regular")

    await import_font("a.ttf", a, storage, db)
    await import_font("b.ttf", b, storage, db)

    assert await _count_fonts(db) == 2


@pytest.mark.asyncio
async def test_reimport_revives_soft_deleted_font(db, storage, font_factory) -> None:
    """Réimporter une font soft-deleted la ressuscite (deleted_at → None).

    Réveil ⇒ `is_duplicate=False` : la question posée est « était-elle déjà dans
    la bibliothèque ? », et la réponse est non. C'est ce qui fait émettre à
    l'appelant l'événement d'ajout et le signal « re-sync » — sans quoi le seul
    chemin de retour après un vidage de corbeille resterait invisible.
    """
    data = font_factory(family="Phoenix", subfamily="Regular")
    font, _ = await import_font("phoenix.ttf", data, storage, db)

    from datetime import datetime, timezone

    font.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    revived, is_duplicate = await import_font("phoenix.ttf", data, storage, db)

    assert is_duplicate is False
    assert revived.id == font.id
    assert revived.deleted_at is None
    assert await _count_fonts(db) == 1


@pytest.mark.asyncio
async def test_malformed_font_is_stored_not_rejected(db, storage) -> None:
    """Magic TTF valide mais corps illisible : stockée avec métadonnées vides."""
    # Magic bytes TTF corrects, contenu volontairement non parsable.
    data = b"\x00\x01\x00\x00" + b"\xde\xad\xbe\xef" * 64

    font, is_duplicate = await import_font("broken.ttf", data, storage, db)

    assert is_duplicate is False
    assert font.family_name is None
    assert font.glyph_count is None
    assert font.classification is None
    # Le fichier doit bien avoir été persisté malgré l'échec de parsing.
    assert await storage.exists(font.file_hash, "ttf") is True
    assert await _count_fonts(db) == 1


@pytest.mark.asyncio
async def test_unsupported_extension_is_rejected(db, storage) -> None:
    """Une extension hors liste blanche lève FontImportError."""
    with pytest.raises(FontImportError):
        await import_font("notes.txt", b"hello world", storage, db)


@pytest.mark.asyncio
async def test_wrong_magic_bytes_is_rejected(db, storage) -> None:
    """Extension .ttf mais contenu qui n'est pas une font → FontImportError."""
    with pytest.raises(FontImportError):
        await import_font("fake.ttf", b"this is not a font at all", storage, db)


@pytest.mark.asyncio
async def test_web_reupload_clears_stale_associations(
    db, storage, font_factory
) -> None:
    """M-51 : B détenait X en corbeille puis l'a désinstallée ; l'utilisateur la
    ré-uploade. Sans remise à zéro des associations, le delta suivant de B la
    verrait « associée, non déclarée » : re-quarantaine confirmée sous le
    seuil, désinstallée partout — la police tout juste ramenée repartirait."""
    b = Device(name="B", hostname="b", os="macos")
    db.add(b)
    await db.flush()
    data = font_factory(family="Comeback")
    font, _ = await import_font("Comeback.ttf", data, storage, db)
    other, _ = await import_font(
        "Other.ttf", font_factory(family="OtherOnB"), storage, db
    )
    await register_device_font(b.id, font.id, "/Users/b/Comeback.ttf", db)
    await register_device_font(b.id, other.id, "/Users/b/Other.ttf", db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deletion_confirmed = True
    await db.commit()

    revived, _ = await import_font("Comeback.ttf", data, storage, db)
    assert revived.id == font.id and revived.deleted_at is None

    stale = await db.execute(select(DeviceFont).where(DeviceFont.font_id == font.id))
    assert stale.scalars().all() == []
    detection = await detect_local_deletions(b.id, {other.file_hash}, db)
    assert detection.quarantined == [] and detection.pending == []


@pytest.mark.asyncio
async def test_web_upload_of_harvested_font_is_allowed_and_clears_fingerprint(
    db, storage, font_factory
) -> None:
    """M-29 : l'upload web est un geste explicite — il ramène une police
    récoltée (nouvelle ligne) et retire son empreinte ; le push agent, lui,
    est refusé tant que l'empreinte existe."""
    from backend.models.harvested_fingerprint import HarvestedFingerprint
    from backend.services.font_importer import HarvestedFontRefused

    data = font_factory(family="Back From Harvest")
    file_hash = hashlib.sha256(data).hexdigest()
    now = datetime.now(timezone.utc)
    db.add(HarvestedFingerprint(file_hash=file_hash, deleted_at=now, harvested_at=now))
    await db.commit()

    with pytest.raises(HarvestedFontRefused):
        await import_font("Back.ttf", data, storage, db, revive_deleted=False)
    assert await _count_fonts(db) == 0

    font, is_duplicate = await import_font("Back.ttf", data, storage, db)

    assert is_duplicate is False
    assert font.deleted_at is None and font.file_hash == file_hash
    left = await db.execute(
        select(HarvestedFingerprint).where(HarvestedFingerprint.file_hash == file_hash)
    )
    assert left.first() is None


@pytest.mark.asyncio
async def test_failed_web_upload_of_harvested_font_keeps_the_fingerprint(
    db, storage, font_factory, monkeypatch
) -> None:
    """M-29 : si le stockage échoue pendant l'upload web d'une police
    récoltée, l'empreinte reste. La perdre sans importer la police rendrait
    le hash inconnu : le delta suivant la réclamerait au push."""
    from backend.models.harvested_fingerprint import HarvestedFingerprint

    data = font_factory(family="Store Fails")
    file_hash = hashlib.sha256(data).hexdigest()
    now = datetime.now(timezone.utc)
    db.add(HarvestedFingerprint(file_hash=file_hash, deleted_at=now, harvested_at=now))
    await db.commit()

    async def failing_store(*args, **kwargs) -> None:
        raise OSError("disque NAS plein")

    monkeypatch.setattr(storage, "store", failing_store)
    with pytest.raises(OSError):
        await import_font("StoreFails.ttf", data, storage, db)
    # L'appelant (upload multiple) avale l'erreur et continue : simuler le
    # commit d'un import suivant dans la même session.
    await db.commit()

    left = await db.execute(
        select(HarvestedFingerprint).where(HarvestedFingerprint.file_hash == file_hash)
    )
    assert left.first() is not None
    assert await _count_fonts(db) == 0
