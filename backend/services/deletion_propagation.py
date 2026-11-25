"""Détection des polices supprimées **sur une machine** : retrait personnel.

Supprimer une police sur une machine est une **intention**, pas une observation.
L'agent ne dit jamais « supprime ça » : il déclare l'état réel de son disque. Le
serveur en déduit ce qui a disparu, en confrontant ce que la machine déclare au
registre durable `device_fonts` (« cette machine a eu cette police »).

Ce qui a disparu devient un **retrait personnel** du propriétaire de la machine
(`FontRemoval`), jamais une mise en corbeille de la bibliothèque partagée :
chaque compte décide pour ses Mac, personne ne décide pour ceux des autres, pas
même l'admin. Ses Mac ne réinstallent plus la police ; ceux qui l'acceptent
(`propagate_deletions`) la désinstallent (cf. `sync_manager.compute_delta`).

Ce module **écrit** — c'est pourquoi il vit à côté de `compute_delta` et non
dedans : le delta est en lecture pure, propriété qu'on tient à préserver.

Trois garde-fous, dans cet ordre :

1. **Rien à partir d'une déclaration vide.** Une machine qui ne déclare aucune
   police n'a pas supprimé sa bibliothèque : elle a un dossier démonté, un scan
   qui a échoué, une configuration cassée. On ne conclut rien.
2. **Seulement ce qui lui est associé.** Une police jamais transférée à cette
   machine ne peut pas en avoir disparu.
3. **Seuils.** Au-delà, le retrait est enregistré (la police n'est plus
   réinstallée) mais **rien n'est désinstallé** sur les autres Mac du compte
   tant que l'utilisateur n'a pas confirmé. Le cas réel : 625 fichiers disparus
   d'un coup lors d'un nettoyage manuel de doublons — sans seuil, une autre
   machine en aurait perdu 225 sans que personne ne le demande.

L'association `device_fonts` est retirée pour ce qu'on a traité : la machine n'a
plus le fichier, le registre doit le dire. La garder ferait re-détecter la même
disparition à chaque sync.

Une police réapparue sur un Mac du compte (réinstallée à la main) annule le
retrait : c'est le geste inverse (`clear_reinstalled_removals`).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.models.font_removal import FontRemoval, removal_scope
from backend.schemas.sync import DeviceFontEntry
from backend.services.sync_manager import effective_ingestible

logger = logging.getLogger(__name__)

# Taille des lots de suppression d'associations (cf. `detect_local_deletions`).
_DELETE_BATCH = 500


async def device_owner(device_id: uuid.UUID, db: AsyncSession) -> uuid.UUID | None:
    """Propriétaire d'un appareil (`None` : appareil sans compte)."""
    return (
        await db.execute(select(Device.owner_user_id).where(Device.id == device_id))
    ).scalar_one_or_none()


@dataclass
class DeletionDetection:
    """Bilan d'une détection de suppressions locales."""

    quarantined: list[Font]
    """Nouveaux retraits confirmés : les autres Mac du compte qui l'acceptent
    les désinstalleront."""

    pending: list[Font]
    """Nouveaux retraits **en attente de confirmation** : au-delà du seuil, rien
    n'est désinstallé ailleurs tant que l'utilisateur n'a pas dit oui."""

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
    """Enregistre comme retraits personnels les polices disparues de ce Mac.

    Ne touche jamais à la bibliothèque partagée : la police reste disponible
    pour les autres comptes. Ne commit pas : l'appelant maîtrise la transaction
    (le delta qui suit doit voir les retraits, d'où le `flush`).

    Args:
        device_id: appareil dont on interprète la déclaration.
        declared_hashes: hashes réellement présents sur son disque.
        db: session de base de données.

    Returns:
        Le bilan des **nouveaux** retraits — vide si rien n'a disparu, si la
        déclaration est vide, ou si le compte avait déjà retiré ces polices
        (ce Mac applique alors un retrait fait ailleurs).
    """
    if not declared_hashes:
        # Garde-fou 1 : une déclaration vide n'est pas une bibliothèque vidée.
        logger.warning(
            "Device %s ne déclare aucune police : détection de suppressions ignorée.",
            device_id,
        )
        return DeletionDetection(quarantined=[], pending=[])

    # Garde-fou 2 : uniquement les polices associées à cette machine et encore
    # dans la bibliothèque (une police mise en corbeille par l'admin n'est pas
    # un geste de ce compte ; son association part à la réconciliation).
    #
    # Le tri « déclarée ou non » se fait en Python plutôt qu'en `NOT IN (…)` :
    # une bibliothèque réelle compte quelques milliers de hashes, et les passer
    # en paramètres liés flirte avec la limite de variables de SQLite. Les
    # associations d'un appareil tiennent en mémoire sans effort.
    #
    # Seules les associations gérées comptent : une police qui disparaît d'une
    # couche que FontSync ne gère pas (/Library/Fonts, mise à jour par un
    # installeur) n'a été supprimée par personne — l'association part sans
    # bruit à la réconciliation (`services/inventory.py`). Limite : un agent
    # antérieur au champ `ingestible` a ses associations enregistrées gérées
    # (défaut du schéma), y compris pour /Library/Fonts ; c'est la mise à jour
    # de l'agent qui les corrige au sync suivant.
    result = await db.execute(
        select(Font)
        .join(DeviceFont, DeviceFont.font_id == Font.id)
        .where(
            DeviceFont.device_id == device_id,
            DeviceFont.ingestible.is_(True),
            Font.deleted_at.is_(None),
        )
    )
    disappeared = [
        font for font in result.scalars().all() if font.file_hash not in declared_hashes
    ]
    if not disappeared:
        return DeletionDetection(quarantined=[], pending=[])

    owner = await device_owner(device_id, db)
    already = set(
        (
            await db.execute(
                select(FontRemoval.font_id).where(
                    removal_scope(owner),
                    FontRemoval.font_id.in_([f.id for f in disappeared]),
                )
            )
        ).scalars()
    )
    # Déjà retirées par le compte : ce Mac applique le retrait (désinstallation
    # propagée, ou même geste refait ici). Rien de nouveau à décider.
    new = [font for font in disappeared if font.id not in already]

    # Garde-fou 3 : au-delà du seuil, on enregistre sans rien désinstaller.
    limit = propagation_limit(len(declared_hashes))
    propagates = len(new) <= limit

    now = datetime.now(timezone.utc)
    for font in new:
        db.add(
            FontRemoval(
                user_id=owner,
                font_id=font.id,
                source_device_id=device_id,
                removed_at=now,
                confirmed=propagates,
            )
        )

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

    if new:
        logger.info(
            "Device %s : %d police(s) retirée(s) sur %d déclarées → %s (seuil %d)",
            device_id,
            len(new),
            len(declared_hashes),
            "retrait confirmé" if propagates else "retrait EN ATTENTE",
            limit,
        )
    if not propagates:
        logger.warning(
            "Désinstallation suspendue pour %d retraits du device %s : "
            "au-delà du seuil, une confirmation est requise.",
            len(new),
            device_id,
        )

    return DeletionDetection(
        quarantined=new if propagates else [],
        pending=[] if propagates else new,
    )


async def clear_reinstalled_removals(
    device_id: uuid.UUID,
    entries: list[DeviceFontEntry],
    db: AsyncSession,
) -> int:
    """Annule les retraits des polices réinstallées sur un Mac du compte.

    « Réinstallée » = déclarée dans une couche gérée par un Mac qui ne la
    détenait pas jusqu'ici (aucune association). Un Mac qui l'a toujours gardée
    (désinstallation non acceptée) la déclare aussi, mais avec son association :
    il ne dit rien de neuf, le retrait tient.

    À appeler **avant** la réconciliation, qui crée les associations.

    Returns:
        Le nombre de retraits annulés.
    """
    managed = {entry.hash for entry in entries if effective_ingestible(entry)}
    if not managed:
        return 0
    owner = await device_owner(device_id, db)
    rows = (
        await db.execute(
            select(FontRemoval, Font.file_hash)
            .join(Font, Font.id == FontRemoval.font_id)
            .where(removal_scope(owner))
        )
    ).all()
    candidates = {removal.font_id: removal for removal, h in rows if h in managed}
    if not candidates:
        return 0
    held = set(
        (
            await db.execute(
                select(DeviceFont.font_id).where(
                    DeviceFont.device_id == device_id,
                    DeviceFont.font_id.in_(list(candidates)),
                )
            )
        ).scalars()
    )
    cleared = [r for font_id, r in candidates.items() if font_id not in held]
    for removal in cleared:
        await db.delete(removal)
    if cleared:
        await db.flush()
        logger.info(
            "Device %s : %d police(s) réinstallée(s), retrait annulé.",
            device_id,
            len(cleared),
        )
    return len(cleared)
