"""Détection des polices supprimées **sur une machine**, et mise en quarantaine.

Supprimer une police sur une machine est une **intention**, pas une observation.
L'agent ne dit jamais « supprime ça » : il déclare l'état réel de son disque. Le
serveur en déduit ce qui a disparu, en confrontant ce que la machine déclare au
registre durable `device_fonts` (« cette machine a eu cette police »).

Ce module **écrit** — c'est pourquoi il vit à côté de `compute_delta` et non
dedans : le delta est en lecture pure, propriété qu'on tient à préserver.

Trois garde-fous, dans cet ordre :

1. **Rien à partir d'une déclaration vide.** Une machine qui ne déclare aucune
   police n'a pas supprimé sa bibliothèque : elle a un dossier démonté, un scan
   qui a échoué, une configuration cassée. On ne conclut rien.
2. **Seulement ce qui lui est associé.** Une police jamais transférée à cette
   machine ne peut pas en avoir disparu.
3. **Seuils.** Au-delà, la disparition est mise en quarantaine (elle sort de la
   bibliothèque, récupérable d'un clic depuis la corbeille) mais **n'est pas
   propagée** tant que l'utilisateur n'a pas confirmé. Le cas réel : 625
   fichiers disparus d'un coup lors d'un nettoyage manuel de doublons — sans
   seuil, une autre machine en aurait perdu 225 sans que personne ne le demande.

L'association `device_fonts` est retirée pour ce qu'on a traité : la machine n'a
plus le fichier, le registre doit le dire. La garder ferait re-détecter la même
disparition à chaque sync — et surtout, restaurer la police depuis la corbeille
la ferait re-quarantiner au sync suivant, une boucle qu'aucun clic ne casse.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.device_font import DeviceFont
from backend.models.font import Font

logger = logging.getLogger(__name__)

# Taille des lots de suppression d'associations (cf. `detect_local_deletions`).
_DELETE_BATCH = 500


@dataclass
class DeletionDetection:
    """Bilan d'une détection de suppressions locales."""

    quarantined: list[Font]
    """Polices sorties de la bibliothèque et propageables aux autres machines."""

    pending: list[Font]
    """Polices sorties de la bibliothèque mais **en attente de confirmation** :
    au-delà du seuil, elles ne sont propagées à personne."""

    @property
    def total(self) -> int:
        return len(self.quarantined) + len(self.pending)


def propagation_limit(declared_count: int) -> int:
    """Nombre maximal de disparitions propageables pour une machine.

    Le plus contraignant des deux seuils décide, relevé par un plancher pour que
    les petites suppressions passent toujours.
    """
    ratio_limit = int(declared_count * settings.deletion_propagation_max_ratio)
    return max(
        settings.deletion_propagation_min_fonts,
        min(settings.deletion_propagation_max_fonts, ratio_limit),
    )


async def detect_local_deletions(
    device_id: uuid.UUID,
    declared_hashes: set[str],
    db: AsyncSession,
) -> DeletionDetection:
    """Met en quarantaine les polices qui ont disparu de cette machine.

    Ne commit pas : l'appelant maîtrise la transaction (le delta qui suit doit
    voir les quarantaines, d'où le `flush`).

    Args:
        device_id: appareil dont on interprète la déclaration.
        declared_hashes: hashes réellement présents sur son disque.
        db: session de base de données.

    Returns:
        Le bilan — vide si rien n'a disparu, ou si la déclaration est vide.
    """
    if not declared_hashes:
        # Garde-fou 1 : une déclaration vide n'est pas une bibliothèque vidée.
        logger.warning(
            "Device %s ne déclare aucune police : détection de suppressions ignorée.",
            device_id,
        )
        return DeletionDetection(quarantined=[], pending=[])

    # Garde-fou 2 : uniquement les polices associées à cette machine et encore
    # actives (une police déjà tombée ne se re-détecte pas).
    #
    # Le tri « déclarée ou non » se fait en Python plutôt qu'en `NOT IN (…)` :
    # une bibliothèque réelle compte quelques milliers de hashes, et les passer
    # en paramètres liés flirte avec la limite de variables de SQLite. Les
    # associations d'un appareil tiennent en mémoire sans effort.
    result = await db.execute(
        select(Font)
        .join(DeviceFont, DeviceFont.font_id == Font.id)
        .where(DeviceFont.device_id == device_id, Font.deleted_at.is_(None))
    )
    disappeared = [
        font for font in result.scalars().all() if font.file_hash not in declared_hashes
    ]
    if not disappeared:
        return DeletionDetection(quarantined=[], pending=[])

    # Garde-fou 3 : au-delà du seuil, on quarantine sans propager.
    limit = propagation_limit(len(declared_hashes))
    propagates = len(disappeared) <= limit

    now = datetime.now(timezone.utc)
    for font in disappeared:
        font.deleted_at = now
        font.deletion_confirmed = propagates
        font.updated_at = now

    # Le registre doit refléter le disque : la machine n'a plus ces fichiers.
    # Par lots, pour ne pas dépendre de la limite de variables liées de SQLite
    # (un nettoyage manuel peut faire disparaître des centaines de polices).
    font_ids = [f.id for f in disappeared]
    for start in range(0, len(font_ids), _DELETE_BATCH):
        await db.execute(
            delete(DeviceFont).where(
                DeviceFont.device_id == device_id,
                DeviceFont.font_id.in_(font_ids[start : start + _DELETE_BATCH]),
            )
        )
    await db.flush()

    logger.info(
        "Device %s : %d police(s) disparue(s) sur %d déclarées → %s (seuil %d)",
        device_id,
        len(disappeared),
        len(declared_hashes),
        "quarantaine propagée" if propagates else "quarantaine EN ATTENTE",
        limit,
    )
    if not propagates:
        logger.warning(
            "Propagation suspendue pour %d suppressions du device %s : "
            "au-delà du seuil, une confirmation est requise.",
            len(disappeared),
            device_id,
        )

    return DeletionDetection(
        quarantined=disappeared if propagates else [],
        pending=[] if propagates else disappeared,
    )
