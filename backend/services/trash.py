"""Corbeille : vidage et purge automatique optionnelle.

Vider la corbeille retire le **fichier** du stockage et garde la **ligne**. Ce
n'est pas une demi-mesure, c'est la seule forme correcte : l'empreinte
(`file_hash`) est ce qui rend la suppression durable. Supprimer la ligne aussi
ferait revenir la police au premier push d'une machine qui détient encore le
fichier — et une purge automatique au jour 30 la ferait réapparaître au jour 31,
indéfiniment.

La purge automatique est **désactivée par défaut** (`TRASH_RETENTION_DAYS=0`) :
une suppression de fichier qui se déclenche toute seule doit être demandée.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.font import Font
from backend.services.storage import StorageBackend

logger = logging.getLogger(__name__)

# Cadence de la boucle de purge. Une rétention se compte en jours : inutile de
# repasser plus souvent, et le premier passage a lieu au démarrage.
PURGE_INTERVAL_SECONDS = 12 * 3600


async def purge_font(font: Font, storage: StorageBackend, db: AsyncSession) -> bool:
    """Retire le fichier du stockage et marque la font purgée. Ne commit pas.

    Idempotent : une font déjà purgée, ou dont le fichier a disparu du stockage,
    n'est pas une erreur. Un échec de stockage laisse la ligne intacte (on ne
    prétend jamais avoir purgé ce qui est encore là).

    Returns:
        True si le fichier vient d'être retiré, False si rien n'était à faire.
    """
    if font.purged_at is not None:
        return False

    try:
        await storage.delete(font.file_hash, font.file_format)
    except FileNotFoundError:
        logger.info(
            "Fichier déjà absent du stockage pour la font %s (purge idempotente)",
            font.id,
        )
    except Exception:
        logger.exception("Purge du fichier impossible pour la font %s", font.id)
        return False

    font.purged_at = datetime.now(timezone.utc)
    return True


async def purge_expired(
    storage: StorageBackend,
    db: AsyncSession,
    *,
    retention_days: int | None = None,
) -> int:
    """Purge les fonts supprimées depuis plus de `retention_days` jours.

    `retention_days` à 0 (défaut de la configuration) désactive la purge : la
    fonction ne fait rien et le dit.

    Returns:
        Nombre de fichiers effectivement retirés du stockage.
    """
    days = settings.trash_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(Font).where(
            Font.deleted_at.is_not(None),
            Font.deleted_at < cutoff,
            Font.purged_at.is_(None),
        )
    )
    expired = list(result.scalars().all())
    if not expired:
        return 0

    purged = 0
    for font in expired:
        if await purge_font(font, storage, db):
            purged += 1
    await db.commit()

    logger.info(
        "Purge automatique : %d fichier(s) retiré(s) du stockage "
        "(supprimés depuis plus de %d jours). Les empreintes sont conservées.",
        purged,
        days,
    )
    return purged


async def run_purge_loop(session_factory, storage_factory) -> None:
    """Boucle de purge automatique : au démarrage, puis toutes les 12 h.

    Ne démarre pas si la rétention est désactivée. Une erreur ne tue jamais la
    boucle — le serveur d'un NAS tourne des mois d'affilée.
    """
    if settings.trash_retention_days <= 0:
        logger.info("Purge automatique de la corbeille désactivée (rétention = 0).")
        return

    logger.info(
        "Purge automatique de la corbeille activée : rétention %d jours.",
        settings.trash_retention_days,
    )
    while True:
        try:
            async with session_factory() as session:
                await purge_expired(storage_factory(), session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Passage de purge automatique échoué (la boucle continue)")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
