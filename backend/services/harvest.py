"""Récolte des pierres tombales.

Condition exacte et neuf garde-fous détaillés en `docs/PLAN-ETATS-FONTS.md`
§3.4. **Cette version, livrée en L1, est INERTE : elle ne supprime jamais
rien.** Deux des garde-fous du modèle cible — G8 (délai de grâce) et G9
(plafond, activation) — dépendent de `fonts.harvest_candidate_since` et
`fonts.deletion_confirmed`, colonnes que M2 n'a pas encore posées.

Ce qu'elle fait : compter et journaliser, sur les garde-fous déjà mesurables
avec le schéma actuel (G3, G4 — via `is_deletion_confirmed`, la traduction
existante de `deleted_reason` en attendant le booléen dédié —, G5, G6, G7), ce
qui deviendrait récoltable. C'est la répétition à blanc sur les données
réelles qui précède l'activation, en L4/L5, de la suppression effective.
"""

from __future__ import annotations

import logging

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font, deletion_confirmed_clause

logger = logging.getLogger(__name__)

# Nombre d'identifiants journalisés au plus, pour ne pas noyer les logs quand
# la corbeille compte des centaines de candidats.
_LOG_SAMPLE = 20


async def harvest_tombstones(db: AsyncSession) -> int:
    """Compte les pierres tombales déjà candidates à la récolte. Ne supprime rien.

    Appelée depuis la branche de confiance de `routers/sync.py:delta_sync`,
    juste après la réconciliation — jamais sur une déclaration vide ou
    suspecte, pour les mêmes raisons que `reconcile_inventory`.
    """
    holder_exists = select(DeviceFont.font_id).where(
        DeviceFont.font_id == Font.id, DeviceFont.ingestible.is_(True)
    )
    undeclared_live_device = select(Device.id).where(
        Device.deleted_at.is_(None),
        or_(
            Device.last_declaration_at.is_(None),
            Device.last_declaration_at <= Font.deleted_at,
        ),
    )
    any_live_device = select(Device.id).where(Device.deleted_at.is_(None))

    result = await db.execute(
        select(Font.id).where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_not(None),  # G3 — le fichier a quitté le stockage
            deletion_confirmed_clause(),  # G4 — suppression confirmée (proxy)
            exists(any_live_device),  # G5 — au moins un appareil vivant
            ~exists(holder_exists),  # G6 — aucun détenteur ingestible
            ~exists(undeclared_live_device),  # G7 — tous ont redéclaré depuis
        )
    )
    candidate_ids = [row[0] for row in result.all()]

    if candidate_ids:
        sample = [str(font_id) for font_id in candidate_ids[:_LOG_SAMPLE]]
        logger.warning(
            "Récolte (aperçu, INERTE — aucune suppression effectuée) : "
            "%d pierre(s) tombale(s) candidate(s)%s : %s",
            len(candidate_ids),
            f" (échantillon de {_LOG_SAMPLE})"
            if len(candidate_ids) > _LOG_SAMPLE
            else "",
            sample,
        )

    return len(candidate_ids)
