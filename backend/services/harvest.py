"""Récolte des pierres tombales.

Condition exacte et neuf garde-fous détaillés en `docs/PLAN-ETATS-FONTS.md`
§3.4. Tant que `settings.tombstone_harvest_enabled` est `False` (défaut,
fail-safe), cette fonction reste l'aperçu INERTE livré en L1 : elle compte et
journalise ce qui deviendrait récoltable (G3, G4, G5, G6, G7), sans jamais
rien supprimer.

**Activée**, deux phases, dans la même transaction que l'appelant (pas de
commit ici — `routers/sync.py:delta_sync` maîtrise la transaction) :

1. **Ouverture de candidature** — pose `harvest_candidate_since` sur toute
   pierre tombale qui satisfait G3, G4, G5, G6, G7 et n'a pas encore de
   candidature ouverte. N'efface rien.
2. **Récolte** — supprime, dans la limite de G9 (`tombstone_harvest_max_per_pass`),
   les pierres tombales dont la candidature est ouverte depuis au moins
   `tombstone_harvest_grace_hours` (G8) et dont plus aucun appareil vivant n'a
   redéclaré depuis cette ouverture.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import Font, deletion_confirmed_clause
from backend.models.font_family import FontFamily, FontFamilyMember

logger = logging.getLogger(__name__)

# Nombre d'identifiants journalisés au plus, pour ne pas noyer les logs quand
# la corbeille compte des centaines de candidats.
_LOG_SAMPLE = 20

# Garde-fous partagés par les deux phases : au moins un appareil vivant (G5),
# aucun détenteur ingestible (G6).
_any_live_device = select(Device.id).where(Device.deleted_at.is_(None))
_ingestible_holder_exists = select(DeviceFont.font_id).where(
    DeviceFont.font_id == Font.id, DeviceFont.ingestible.is_(True)
)


async def harvest_tombstones(db: AsyncSession) -> int:
    """Récolte (ou, flag éteint, prévisualise) les pierres tombales éligibles.

    Appelée depuis la branche de confiance de `routers/sync.py:delta_sync`,
    juste après la réconciliation — jamais sur une déclaration vide ou
    suspecte, pour les mêmes raisons que `reconcile_inventory`.
    """
    if not settings.tombstone_harvest_enabled:
        return await _preview_candidates(db)

    now = datetime.now(timezone.utc)
    await _open_candidacies(db, now)
    return await _harvest_ready_candidates(db, now)


async def _preview_candidates(db: AsyncSession) -> int:
    """Version INERTE de L1/L2 : compte et journalise, ne supprime rien.

    Ne couvre que les cinq garde-fous mesurables avant l'activation (G3, G4,
    G5, G6, G7) — G8 (délai de grâce) et G9 (plafond) n'ont de sens qu'une
    fois la suppression réellement en jeu.
    """
    undeclared_since_deletion = select(Device.id).where(
        Device.deleted_at.is_(None),
        or_(
            Device.last_declaration_at.is_(None),
            Device.last_declaration_at <= Font.deleted_at,
        ),
    )
    result = await db.execute(
        select(Font.id).where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_not(None),  # G3
            deletion_confirmed_clause(),  # G4
            exists(_any_live_device),  # G5
            ~exists(_ingestible_holder_exists),  # G6
            ~exists(undeclared_since_deletion),  # G7
        )
    )
    candidate_ids = [row[0] for row in result.all()]

    if candidate_ids:
        _log_candidates(
            candidate_ids,
            "Récolte (aperçu, INERTE — aucune suppression effectuée)",
        )
    return len(candidate_ids)


async def _open_candidacies(db: AsyncSession, now: datetime) -> None:
    """Phase 1 — ouvre la candidature des tombes fraîchement éligibles.

    N'efface rien : ne fait que poser `harvest_candidate_since`, la mémoire du
    délai de grâce (G8) que la phase 2 lit ensuite.
    """
    undeclared_since_deletion = select(Device.id).where(
        Device.deleted_at.is_(None),
        or_(
            Device.last_declaration_at.is_(None),
            Device.last_declaration_at <= Font.deleted_at,
        ),
    )
    await db.execute(
        update(Font)
        .where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_not(None),  # G3
            deletion_confirmed_clause(),  # G4
            Font.harvest_candidate_since.is_(None),
            exists(_any_live_device),  # G5
            ~exists(_ingestible_holder_exists),  # G6
            ~exists(undeclared_since_deletion),  # G7
        )
        .values(harvest_candidate_since=now)
    )


async def _harvest_ready_candidates(db: AsyncSession, now: datetime) -> int:
    """Phase 2 — récolte les candidatures mûres (G8), plafonnées (G9)."""
    grace = timedelta(hours=settings.tombstone_harvest_grace_hours)
    undeclared_since_candidacy = select(Device.id).where(
        Device.deleted_at.is_(None),
        or_(
            Device.last_declaration_at.is_(None),
            Device.last_declaration_at <= Font.harvest_candidate_since,
        ),
    )
    result = await db.execute(
        select(Font.id)
        .where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_not(None),  # G3
            deletion_confirmed_clause(),  # G4
            Font.harvest_candidate_since.is_not(None),
            Font.harvest_candidate_since <= now - grace,  # G8 — délai de grâce
            exists(_any_live_device),  # G5
            ~exists(_ingestible_holder_exists),  # G6
            ~exists(undeclared_since_candidacy),  # G8 — redéclaré depuis
        )
        .limit(settings.tombstone_harvest_max_per_pass)  # G9
    )
    candidate_ids = [row[0] for row in result.all()]
    if not candidate_ids:
        return 0

    await _delete_fonts(db, candidate_ids)
    _log_candidates(candidate_ids, "Récolte — pierre(s) tombale(s) SUPPRIMÉE(S)")
    return len(candidate_ids)


async def _delete_fonts(db: AsyncSession, font_ids: list[uuid.UUID]) -> None:
    """Supprime les lignes récoltées et leur trace dans les familles.

    Ordre exact de `docs/PLAN-ETATS-FONTS.md` §3.4 : les familles auto-groupées
    devenues vides sont retirées à la fin, jamais celles créées à la main
    (`is_auto_grouped = 1`).
    """
    families_result = await db.execute(
        select(FontFamilyMember.family_id)
        .where(FontFamilyMember.font_id.in_(font_ids))
        .distinct()
    )
    touched_family_ids = [row[0] for row in families_result.all()]

    await db.execute(
        delete(FontFamilyMember).where(FontFamilyMember.font_id.in_(font_ids))
    )
    await db.execute(delete(DeviceFont).where(DeviceFont.font_id.in_(font_ids)))
    await db.execute(delete(Font).where(Font.id.in_(font_ids)))

    if touched_family_ids:
        member_count = (
            select(func.count())
            .select_from(FontFamilyMember)
            .where(FontFamilyMember.family_id == FontFamily.id)
            .scalar_subquery()
        )
        await db.execute(
            update(FontFamily)
            .where(FontFamily.id.in_(touched_family_ids))
            .values(style_count=member_count)
        )
        await db.execute(
            delete(FontFamily).where(
                FontFamily.id.in_(touched_family_ids),
                FontFamily.style_count == 0,
                FontFamily.is_auto_grouped.is_(True),
            )
        )
    await db.flush()


def _log_candidates(candidate_ids: list[uuid.UUID], headline: str) -> None:
    sample = [str(font_id) for font_id in candidate_ids[:_LOG_SAMPLE]]
    suffix = (
        f" (échantillon de {_LOG_SAMPLE})" if len(candidate_ids) > _LOG_SAMPLE else ""
    )
    logger.warning("%s : %d%s : %s", headline, len(candidate_ids), suffix, sample)
