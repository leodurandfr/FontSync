"""Service de gestion de la synchronisation delta entre agents et serveur."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.schemas.sync import DeltaSyncResponse, DeviceFontEntry, FontRef


async def compute_delta(
    device_id: uuid.UUID,
    device_fonts: list[DeviceFontEntry],
    db: AsyncSession,
) -> DeltaSyncResponse:
    """Compare les fonts de l'agent avec celles du serveur.

    Args:
        device_id: Identifiant du device.
        device_fonts: Liste des fonts présentes sur le device (hash + filename).
        db: Session de base de données.

    Returns:
        DeltaSyncResponse avec unknown_to_server, missing_on_device, already_synced.
    """
    device_hashes = {entry.hash for entry in device_fonts}

    # Récupérer toutes les fonts actives du serveur
    result = await db.execute(
        select(Font.id, Font.file_hash, Font.original_filename, Font.file_format, Font.family_name, Font.file_size)
        .where(Font.deleted_at.is_(None))
    )
    server_fonts = result.all()
    server_hash_map: dict[str, tuple] = {row.file_hash: row for row in server_fonts}
    server_hashes = set(server_hash_map.keys())

    # Fonts sur le device mais pas sur le serveur → à pusher
    unknown_to_server = list(device_hashes - server_hashes)

    # Fonts sur le serveur mais pas sur le device → à puller
    missing_hashes = server_hashes - device_hashes
    missing_on_device = [
        FontRef(
            id=server_hash_map[h].id,
            file_hash=h,
            original_filename=server_hash_map[h].original_filename,
            file_format=server_hash_map[h].file_format,
            family_name=server_hash_map[h].family_name,
            file_size=server_hash_map[h].file_size,
        )
        for h in missing_hashes
    ]

    already_synced = len(device_hashes & server_hashes)

    return DeltaSyncResponse(
        unknown_to_server=unknown_to_server,
        missing_on_device=missing_on_device,
        already_synced=already_synced,
    )


async def register_device_font(
    device_id: uuid.UUID,
    font_id: uuid.UUID,
    local_path: str,
    db: AsyncSession,
) -> None:
    """Enregistre l'association device ↔ font.

    Si l'association existe déjà, met à jour le local_path.
    """
    existing = await db.execute(
        select(DeviceFont).where(
            DeviceFont.device_id == device_id,
            DeviceFont.font_id == font_id,
        )
    )
    device_font = existing.scalar_one_or_none()

    if device_font is not None:
        device_font.local_path = local_path
    else:
        device_font = DeviceFont(
            device_id=device_id,
            font_id=font_id,
            local_path=local_path,
        )
        db.add(device_font)

    await db.flush()
