"""Réconciliation de `device_fonts` avec la déclaration réelle d'un appareil.

Aujourd'hui `device_fonts` n'est écrit qu'au transfert (push/pull) : deux
police installées avant la refonte, ou copiées d'une machine à l'autre hors
sync, n'y ont jamais d'association. Ce module le rend fidèle à ce que la
machine déclare à **chaque** delta — condition préalable à toute récolte de
pierre tombale (cf. `docs/PLAN-ETATS-FONTS.md` §3).

Ce module **écrit** — il vit à côté de `sync_manager.compute_delta` (lecture
pure) et de `deletion_propagation.detect_local_deletions`, pour la même
raison : ne pas mélanger le calcul du delta avec les décisions qui modifient
le registre.

Commutatif avec `detect_local_deletions` par construction : la détection ne
touche que les polices **actives** non déclarées, la réconciliation n'insère
que du déclaré et ne supprime que des polices déjà **tombées**. Ensembles
disjoints — l'ordre d'appel n'a pas à faire de différence, il reste fixé et
testé en défense en profondeur (`routers/sync.py`).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_font import DeviceFont
from backend.models.font import Font
from backend.schemas.sync import DeviceFontEntry

logger = logging.getLogger(__name__)

# Taille des lots, pour ne pas dépendre de la limite de variables liées de
# SQLite — même contrainte, même valeur que `deletion_propagation._DELETE_BATCH`.
_BATCH = 500


@dataclass
class ReconcileStats:
    """Bilan d'une réconciliation."""

    arrivals: int
    """Associations créées : hash déclaré, police connue, pas encore associée."""

    departs: int
    """Associations retirées : police déjà tombée, plus déclarée."""

    updates: int
    """Associations existantes dont `local_path`/`ingestible` a changé."""


async def _registry_size(device_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(DeviceFont)
        .where(DeviceFont.device_id == device_id)
    )
    return result.scalar() or 0


async def reconcile_inventory(
    device_id: uuid.UUID,
    entries: list[DeviceFontEntry],
    db: AsyncSession,
) -> ReconcileStats:
    """`device_fonts` devient le MIROIR de ce que la machine déclare.

    Ne commit pas : l'appelant (`routers/sync.py:delta_sync`) maîtrise la
    transaction. À appeler uniquement sur une déclaration **non vide et non
    suspecte** — les garde-fous vivent dans l'appelant, pas ici.

    Args:
        device_id: appareil dont on interprète la déclaration.
        entries: déclaration brute de l'agent. Peut contenir des doublons de
            hash : une police installée à la fois pour l'utilisateur et pour
            tous les utilisateurs (Office, Adobe) produit deux entrées du même
            fichier, `ingestible=True` puis `False`.
        db: session de base de données.

    Returns:
        Le décompte d'arrivées, de départs et de mises à jour.
    """
    # Étape 0 — déduplication par hash, agrégation par OU logique.
    # Nécessaire, pas défensive : sans elle, la seconde entrée d'un même hash
    # viole soit la clé primaire `(device_id, font_id)` à l'insertion, soit
    # écrase `ingestible=1` par `ingestible=0` si « le dernier gagne » — dans
    # les deux cas une police que la machine détient aussi ingestiblement
    # perdrait sa protection contre la récolte.
    by_hash: dict[str, DeviceFontEntry] = {}
    for entry in entries:
        prev = by_hash.get(entry.hash)
        if prev is None or (entry.ingestible and not prev.ingestible):
            by_hash[entry.hash] = entry

    # Log volontairement bruyant pendant la fenêtre d'observation de L1 : le
    # registre d'un appareil qui n'avait jamais eu d'association complète peut
    # grossir de plusieurs milliers de lignes au premier delta sous ce palier
    # — un fait attendu et à vérifier, pas un effet de bord découvert après
    # coup (cf. §4.4 du plan).
    registry_before = await _registry_size(device_id, db)
    logger.warning(
        "Device %s : déclaration de %d police(s) (%d après dédup par hash) — "
        "registre avant réconciliation : %d association(s).",
        device_id,
        len(entries),
        len(by_hash),
        registry_before,
    )

    existing_rows = await db.execute(
        select(DeviceFont, Font.file_hash, Font.deleted_at)
        .join(Font, Font.id == DeviceFont.font_id)
        .where(DeviceFont.device_id == device_id)
    )
    existing_by_hash: dict[str, tuple[DeviceFont, object]] = {
        file_hash: (device_font, deleted_at)
        for device_font, file_hash, deleted_at in existing_rows.all()
    }

    # ---------- Arrivées ----------
    # Hash déclaré ∧ police connue du serveur (active OU tombée) ∧ pas encore
    # associée. C'est le geste le plus important du chantier : créer
    # l'association d'une police EN CORBEILLE est ce qui protège son fichier
    # tant que cette machine le détient encore.
    arrivals = 0
    missing_hashes = [h for h in by_hash if h not in existing_by_hash]
    if missing_hashes:
        font_by_hash: dict[str, Font] = {}
        for start in range(0, len(missing_hashes), _BATCH):
            chunk = missing_hashes[start : start + _BATCH]
            result = await db.execute(select(Font).where(Font.file_hash.in_(chunk)))
            for font in result.scalars().all():
                font_by_hash[font.file_hash] = font

        for file_hash, font in font_by_hash.items():
            entry = by_hash[file_hash]
            db.add(
                DeviceFont(
                    device_id=device_id,
                    font_id=font.id,
                    local_path=entry.local_path or entry.filename,
                    ingestible=entry.ingestible,
                    # Borne inférieure vraie plutôt que « maintenant » : cette
                    # association existait déjà en pratique, on ne fait que la
                    # rendre visible au registre.
                    installed_at=font.created_at,
                )
            )
            # Une arrivée sur une tombe annule sa candidature à la récolte
            # (`docs/PLAN-ETATS-FONTS.md` §3.1, §3.4/G8) : ce détenteur retrouvé
            # prouve que la pierre tombale n'était pas orpheline, quelle que soit
            # la couche (ingestible ou non — G6 la protège déjà indépendamment).
            if font.deleted_at is not None:
                font.harvest_candidate_since = None
            arrivals += 1

    # ---------- Départs et mises à jour ----------
    depart_font_ids: list[uuid.UUID] = []
    updates = 0
    for file_hash, (device_font, deleted_at) in existing_by_hash.items():
        entry = by_hash.get(file_hash)
        if entry is None:
            # DÉPARTS — uniquement les polices déjà TOMBÉES, sans quarantaine
            # ni notification (il n'y a rien à quarantiner : la police est déjà
            # hors bibliothèque). Une police ACTIVE non déclarée n'est jamais
            # touchée ici : domaine exclusif de `detect_local_deletions`, avec
            # son seuil et sa quarantaine.
            if deleted_at is not None:
                depart_font_ids.append(device_font.font_id)
            continue
        new_local_path = entry.local_path or entry.filename
        if (
            device_font.local_path != new_local_path
            or device_font.ingestible != entry.ingestible
        ):
            device_font.local_path = new_local_path
            device_font.ingestible = entry.ingestible
            updates += 1

    for start in range(0, len(depart_font_ids), _BATCH):
        chunk = depart_font_ids[start : start + _BATCH]
        await db.execute(
            delete(DeviceFont).where(
                DeviceFont.device_id == device_id,
                DeviceFont.font_id.in_(chunk),
            )
        )

    await db.flush()

    stats = ReconcileStats(
        arrivals=arrivals, departs=len(depart_font_ids), updates=updates
    )
    if stats.arrivals or stats.departs or stats.updates:
        logger.info(
            "Device %s : réconciliation — %d arrivée(s), %d départ(s), "
            "%d mise(s) à jour.",
            device_id,
            stats.arrivals,
            stats.departs,
            stats.updates,
        )
    return stats
