"""Service de regroupement automatique des fonts en familles.

Regroupe les fonts par family_name, crée les familles automatiquement
et attribue un sort_order logique basé sur le poids et l'italique.
"""

import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.font import Font
from backend.models.font_family import FontFamily, FontFamilyMember

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Génère un slug URL-friendly à partir d'un nom de famille."""
    # Normaliser les caractères Unicode (accents → base)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    # Lowercase, remplacer tout ce qui n'est pas alphanumérique par un tiret
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    # Fallback déterministe pour les noms entièrement non-ASCII (CJK, etc.) :
    # un même nom → toujours le même slug, pour que ces familles se regroupent
    # au lieu de se disperser (un slug = identité de la famille, cf. group_font).
    if not slug:
        digest = hashlib.md5(text.strip().casefold().encode("utf-8")).hexdigest()
        slug = f"family-{digest[:8]}"
    return slug


def resolve_family_name(font: Font) -> str:
    """Nom de famille d'affichage, avec repli pour ne jamais perdre une font.

    Chaîne de repli : ``family_name`` (nameID 16/1) → ``full_name`` (4)
    → ``postscript_name`` (6) → nom de fichier sans extension. Comme
    ``original_filename`` est non-null, le résultat est toujours non vide :
    une font sans métadonnées de famille s'affiche tout de même (famille à
    un seul membre) au lieu de disparaître de la vue.
    """
    for candidate in (font.family_name, font.full_name, font.postscript_name):
        if candidate and candidate.strip():
            return candidate.strip()
    return Path(font.original_filename).stem or font.original_filename


def _representative_rank(font: Font) -> tuple[int, int]:
    """Classe les membres d'une famille : le plus « Regular » d'abord.

    Rang minimal = le plus proche de 400, upright avant italique. Sert à
    dériver les métadonnées de la famille de façon déterministe (indépendante
    de l'ordre d'import).
    """
    weight = font.weight_class or 400
    return (abs(weight - 400), 1 if font.is_italic else 0)


async def _refresh_family_metadata(db: AsyncSession, family: FontFamily) -> None:
    """Recale designer/manufacturer/classification sur le membre le plus Regular."""
    result = await db.execute(
        select(Font)
        .join(FontFamilyMember, FontFamilyMember.font_id == Font.id)
        .where(
            FontFamilyMember.family_id == family.id,
            Font.deleted_at.is_(None),
        )
    )
    members = result.scalars().all()
    if not members:
        return
    rep = min(members, key=_representative_rank)
    family.designer = rep.designer
    family.manufacturer = rep.manufacturer
    family.classification = rep.classification


def compute_sort_order(weight_class: int | None, is_italic: bool) -> int:
    """Calcule le sort_order pour classer les styles logiquement.

    Ordre : Thin → Light → Regular → Medium → Semi-Bold → Bold → Extra-Bold → Black,
    avec les italiques juste après leur variante droite.

    Retourne un entier où les poids pairs = upright, impairs = italic.
    Avec un pas de 50, weight_class 100→0, 150→1, 200→2, ..., 900→16.
    Multiplié par 2 pour intercaler les italiques : 100up=0, 100it=1, 150up=2, etc.
    """
    weight = weight_class or 400
    # Clamp dans la plage standard
    weight = max(100, min(weight, 900))
    # Mapper sur des entiers avec résolution de 50 unités
    base = (weight - 100) // 50
    # Les italiques viennent juste après leur variante droite
    return base * 2 + (1 if is_italic else 0)


async def ensure_unique_slug(db: AsyncSession, base_slug: str) -> str:
    """S'assure que le slug est unique, ajoute un suffixe numérique si nécessaire."""
    slug = base_slug
    counter = 2
    while True:
        exists = await db.execute(
            select(FontFamily.id).where(FontFamily.slug == slug).limit(1)
        )
        if exists.scalar_one_or_none() is None:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


async def group_font(font: Font, db: AsyncSession) -> FontFamily:
    """Rattache une font à sa famille. Crée la famille si elle n'existe pas.

    Le regroupement est **automatique et déterministe** : la clé est le slug
    normalisé du nom de famille (insensible à la casse, aux espaces et aux
    accents) — un slug = une famille. Une font sans ``family_name`` est
    regroupée sous un nom de repli (cf. :func:`resolve_family_name`), donc cette
    fonction ne renvoie **jamais** ``None``.

    Args:
        font: La font à grouper (doit être déjà persistée en base).
        db: Session de base de données.

    Returns:
        La FontFamily à laquelle la font a été rattachée.
    """
    display_name = resolve_family_name(font)
    slug = slugify(display_name)

    # Une famille = un slug. On réutilise toute famille (auto ou manuelle)
    # portant déjà ce slug au lieu d'en créer une variante « -2 ».
    result = await db.execute(select(FontFamily).where(FontFamily.slug == slug))
    family = result.scalar_one_or_none()

    if family is None:
        family = FontFamily(
            name=display_name,
            slug=slug,
            designer=font.designer,
            manufacturer=font.manufacturer,
            classification=font.classification,
            is_auto_grouped=True,
            style_count=0,
        )
        db.add(family)
        await db.flush()

    # Vérifier si la font est déjà membre d'une famille
    existing_member = await db.execute(
        select(FontFamilyMember).where(FontFamilyMember.font_id == font.id)
    )
    member = existing_member.scalar_one_or_none()

    if member is not None:
        if member.family_id == family.id:
            # Déjà dans la bonne famille, mettre à jour le sort_order
            member.sort_order = compute_sort_order(font.weight_class, font.is_italic)
            await db.flush()
            await _refresh_family_metadata(db, family)
            return family
        # Font dans une autre famille → la retirer d'abord
        old_family_id = member.family_id
        await db.delete(member)
        await db.flush()
        # Décrémenter le style_count de l'ancienne famille
        old_family = await db.get(FontFamily, old_family_id)
        if old_family is not None:
            old_family.style_count = max(0, old_family.style_count - 1)

    # Créer le lien famille ↔ font
    new_member = FontFamilyMember(
        font_id=font.id,
        family_id=family.id,
        sort_order=compute_sort_order(font.weight_class, font.is_italic),
    )
    db.add(new_member)
    family.style_count += 1
    await db.flush()
    await _refresh_family_metadata(db, family)

    return family


async def regroup_all(db: AsyncSession) -> dict[str, int]:
    """Regroupe toutes les fonts existantes en familles.

    Supprime toutes les familles auto-groupées et les recrée à partir
    des fonts en base. Les familles manuelles (is_auto_grouped=False)
    sont préservées.

    Returns:
        Dict avec les statistiques : families_created, fonts_grouped, fonts_skipped.
    """
    # 1. Supprimer les membres des familles auto-groupées
    auto_family_ids = select(FontFamily.id).where(FontFamily.is_auto_grouped.is_(True))
    await db.execute(
        delete(FontFamilyMember).where(FontFamilyMember.family_id.in_(auto_family_ids))
    )
    # 2. Supprimer les familles auto-groupées
    await db.execute(delete(FontFamily).where(FontFamily.is_auto_grouped.is_(True)))
    await db.flush()

    # 3. Charger toutes les fonts non-supprimées (orphelines incluses : elles
    #    sont regroupées via un nom de repli, cf. resolve_family_name).
    result = await db.execute(
        select(Font).where(Font.deleted_at.is_(None)).order_by(Font.family_name)
    )
    fonts = result.scalars().all()

    families_created = 0
    fonts_grouped = 0
    fonts_skipped = 0
    fonts_orphaned = 0

    # Cache des familles de cette exécution, indexées par slug (= identité).
    family_cache: dict[str, FontFamily] = {}

    for font in fonts:
        # Vérifier si la font est déjà dans une famille manuelle
        existing = await db.execute(
            select(FontFamilyMember).where(FontFamilyMember.font_id == font.id)
        )
        if existing.scalar_one_or_none() is not None:
            fonts_skipped += 1
            continue

        if not (font.family_name or "").strip():
            fonts_orphaned += 1

        display_name = resolve_family_name(font)
        slug = slugify(display_name)

        family = family_cache.get(slug)
        if family is None:
            # Peut déjà exister si une famille manuelle porte ce slug.
            found = await db.execute(select(FontFamily).where(FontFamily.slug == slug))
            family = found.scalar_one_or_none()
            if family is None:
                family = FontFamily(
                    name=display_name,
                    slug=slug,
                    designer=font.designer,
                    manufacturer=font.manufacturer,
                    classification=font.classification,
                    is_auto_grouped=True,
                    style_count=0,
                )
                db.add(family)
                await db.flush()
                families_created += 1
            family_cache[slug] = family

        member = FontFamilyMember(
            font_id=font.id,
            family_id=family.id,
            sort_order=compute_sort_order(font.weight_class, font.is_italic),
        )
        db.add(member)
        family.style_count += 1
        fonts_grouped += 1

    await db.flush()

    # Métadonnées de famille déterministes (membre le plus Regular).
    for family in family_cache.values():
        await _refresh_family_metadata(db, family)

    logger.info(
        "Regroupement terminé : %d familles créées, %d fonts groupées, "
        "%d ignorées, %d sans nom de famille (repli)",
        families_created,
        fonts_grouped,
        fonts_skipped,
        fonts_orphaned,
    )

    return {
        "families_created": families_created,
        "fonts_grouped": fonts_grouped,
        "fonts_skipped": fonts_skipped,
        "fonts_orphaned": fonts_orphaned,
    }
