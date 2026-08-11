"""Service de gestion de la synchronisation delta entre agents et serveur."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.schemas.sync import DeltaSyncResponse, DeviceFontEntry, FontRef


def _to_ref(row: Any) -> FontRef:
    return FontRef(
        id=row.id,
        file_hash=row.file_hash,
        original_filename=row.original_filename,
        file_format=row.file_format,
        family_name=row.family_name,
        file_size=row.file_size,
    )


async def compute_delta(
    device_fonts: list[DeviceFontEntry],
    db: AsyncSession,
    *,
    propagate_deletions: bool = False,
) -> DeltaSyncResponse:
    """Compare les fonts de l'agent avec celles du serveur.

    Lecture pure : ne crée aucune association `device_fonts` et ne commit
    jamais. Les associations sont enregistrées au moment réel du transfert
    (push pour les fonts montantes, pull pour les fonts descendantes). La
    détection des suppressions *locales* vit délibérément dans le routeur, pas
    ici : elle écrit.

    Les fonts supprimées côté serveur sont lues elles aussi. Les ignorer les
    ferait retomber dans `unknown_to_server`, et la machine qui détient encore
    le fichier les repousserait à chaque sync — la boucle qui rendait toute
    suppression illusoire.

    Args:
        device_fonts: Liste des fonts présentes sur le device (hash + filename).
        db: Session de base de données.
        propagate_deletions: l'appareil applique-t-il les suppressions du
            serveur ? Si non, `to_uninstall` reste vide (on renvoie quand même
            le décompte `deleted_on_server`, purement informatif).

    Returns:
        DeltaSyncResponse avec unknown_to_server, missing_on_device,
        already_synced, deleted_on_server et to_uninstall.
    """
    device_hashes = {entry.hash for entry in device_fonts}
    # `ingestible` n'agit QUE sur ce qui serait proposé au push. Ni sur
    # `already_synced`, ni sur `missing_on_device`, ni sur la détection de
    # suppressions : restreindre `device_hashes` lui-même referait passer
    # chaque police non ingestible pour « absente », donc la ferait ressortir
    # de la corbeille au premier delta suivant.
    ingestible_hashes = {entry.hash for entry in device_fonts if entry.ingestible}

    # Toutes les fonts du serveur, supprimées comprises (cf. docstring).
    result = await db.execute(
        select(
            Font.id,
            Font.file_hash,
            Font.original_filename,
            Font.file_format,
            Font.family_name,
            Font.file_size,
            Font.deleted_at,
            Font.deletion_confirmed,
        )
    )
    active_map: dict[str, Any] = {}
    deleted_map: dict[str, Any] = {}
    for row in result.all():
        if row.deleted_at is None:
            active_map[row.file_hash] = row
        else:
            deleted_map[row.file_hash] = row

    active_hashes = set(active_map)
    known_hashes = active_hashes | set(deleted_map)

    # Fonts sur le device et inconnues du serveur → à pusher. « Inconnue » se
    # mesure sur *tout* ce que le serveur connaît, tombes comprises. Seul le
    # sous-ensemble ingestible est proposé : une police hors périmètre
    # d'ingestion (`/Library/Fonts`) reste déclarée (elle protège les tombes
    # qu'elle détient) sans jamais être offerte au push.
    unknown_to_server = list(ingestible_hashes - known_hashes)

    # Fonts sur le serveur mais pas sur le device → à puller
    missing_on_device = [_to_ref(active_map[h]) for h in active_hashes - device_hashes]

    # Fonts en commun → simple comptage (aucune écriture)
    already_synced = len(device_hashes & active_hashes)

    # Fonts que le device détient encore alors qu'elles sont tombées. Une
    # quarantaine en attente de confirmation n'en fait jamais partie : tant que
    # l'utilisateur n'a pas tranché, personne ne perd son fichier.
    deleted_here = [deleted_map[h] for h in device_hashes & set(deleted_map)]
    to_uninstall = (
        [_to_ref(row) for row in deleted_here if row.deletion_confirmed]
        if propagate_deletions
        else []
    )

    return DeltaSyncResponse(
        unknown_to_server=unknown_to_server,
        missing_on_device=missing_on_device,
        already_synced=already_synced,
        deleted_on_server=len(deleted_here),
        to_uninstall=to_uninstall,
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
