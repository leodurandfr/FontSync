"""Service de regroupement automatique des fonts en familles.

Regroupe les fonts par family_name, crée les familles automatiquement
et attribue un sort_order logique basé sur le poids et l'italique.
"""

import logging
import re
import unicodedata
import uuid

from sqlalchemy import delete, func, or_, select
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
    # Fallback pour les noms entièrement non-ASCII (CJK, etc.)
    if not slug:
        slug = f"family-{uuid.uuid4().hex[:8]}"
    return slug


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


async def group_font(font: Font, db: AsyncSession) -> FontFamily | None:
    """Rattache une font à sa famille. Crée la famille si elle n'existe pas.

    Args:
        font: La font à grouper (doit être déjà persistée en base).
        db: Session de base de données.

    Returns:
        La FontFamily à laquelle la font a été rattachée, ou None si
        la font n'a pas de family_name.
    """
    if not (font.family_name or "").strip():
        return None

    # Chercher une famille existante par nom exact
    result = await db.execute(
        select(FontFamily).where(FontFamily.name == font.family_name)
    )
    family = result.scalar_one_or_none()

    if family is None:
        # Créer la famille
        slug = await ensure_unique_slug(db, slugify(font.family_name))
        family = FontFamily(
            name=font.family_name,
            slug=slug,
            designer=font.designer,
            manufacturer=font.manufacturer,
            classification=font.classification,
            is_auto_grouped=True,
            style_count=0,
        )
        db.add(family)
        await db.flush()

    # Vérifier si la font est déjà membre de cette famille
    existing_member = await db.execute(
        select(FontFamilyMember).where(FontFamilyMember.font_id == font.id)
    )
    member = existing_member.scalar_one_or_none()

    if member is not None:
        if member.family_id == family.id:
            # Déjà dans la bonne famille, mettre à jour le sort_order
            member.sort_order = compute_sort_order(font.weight_class, font.is_italic)
            await db.flush()
            return family
        else:
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
    await db.execute(
        delete(FontFamily).where(FontFamily.is_auto_grouped.is_(True))
    )
    await db.flush()

    # 3. Compter les fonts orphelines (sans family_name)
    orphan_result = await db.execute(
        select(func.count()).select_from(Font).where(
            Font.deleted_at.is_(None),
            or_(Font.family_name.is_(None), Font.family_name == ""),
        )
    )
    fonts_orphaned = orphan_result.scalar() or 0

    # 4. Charger toutes les fonts non-supprimées avec un family_name
    result = await db.execute(
        select(Font)
        .where(Font.deleted_at.is_(None), Font.family_name.isnot(None), Font.family_name != "")
        .order_by(Font.family_name)
    )
    fonts = result.scalars().all()

    families_created = 0
    fonts_grouped = 0
    fonts_skipped = 0

    # Cache des familles déjà créées dans cette exécution
    family_cache: dict[str, FontFamily] = {}

    for font in fonts:
        # Vérifier si la font est déjà dans une famille manuelle
        existing = await db.execute(
            select(FontFamilyMember).where(FontFamilyMember.font_id == font.id)
        )
        if existing.scalar_one_or_none() is not None:
            fonts_skipped += 1
            continue

        family_name = font.family_name
        assert family_name is not None  # garanti par le filtre SQL

        if family_name not in family_cache:
            slug = await ensure_unique_slug(db, slugify(family_name))
            family = FontFamily(
                name=family_name,
                slug=slug,
                designer=font.designer,
                manufacturer=font.manufacturer,
                classification=font.classification,
                is_auto_grouped=True,
                style_count=0,
            )
            db.add(family)
            await db.flush()
            family_cache[family_name] = family
            families_created += 1

        family = family_cache[family_name]
        member = FontFamilyMember(
            font_id=font.id,
            family_id=family.id,
            sort_order=compute_sort_order(font.weight_class, font.is_italic),
        )
        db.add(member)
        family.style_count += 1
        fonts_grouped += 1

    await db.flush()

    logger.info(
        "Regroupement terminé : %d familles créées, %d fonts groupées, %d ignorées, %d orphelines",
        families_created, fonts_grouped, fonts_skipped, fonts_orphaned,
    )

    return {
        "families_created": families_created,
        "fonts_grouped": fonts_grouped,
        "fonts_skipped": fonts_skipped,
        "fonts_orphaned": fonts_orphaned,
    }
