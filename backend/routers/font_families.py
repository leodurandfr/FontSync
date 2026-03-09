"""Router pour les familles de polices."""

import logging
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.font import Font
from backend.models.font_family import FontFamily, FontFamilyMember
from backend.schemas.font_family import (
    AddFontsToFamily,
    FamilyMemberResponse,
    FamilySortField,
    FontFamilyCreate,
    FontFamilyDetailResponse,
    FontFamilyListResponse,
    FontFamilyResponse,
    FontFamilyUpdate,
    FontPreview,
    MergeFamilies,
    MergeResult,
    RegroupStats,
    SortOrder,
)
from backend.services.family_grouper import compute_sort_order, ensure_unique_slug, regroup_all, slugify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/font-families", tags=["font-families"])


# ---------- Helpers ----------


async def _get_family_or_404(family_id: uuid.UUID, db: AsyncSession) -> FontFamily:
    """Récupère une famille par ID ou lève 404."""
    result = await db.execute(select(FontFamily).where(FontFamily.id == family_id))
    family = result.scalar_one_or_none()
    if family is None:
        raise HTTPException(status_code=404, detail="Famille non trouvée.")
    return family


async def _build_family_response(family: FontFamily, db: AsyncSession) -> FontFamilyResponse:
    """Construit la réponse d'une famille avec le preview font."""
    # Charger le premier membre non-supprimé (par sort_order) pour le preview
    result = await db.execute(
        select(FontFamilyMember)
        .join(FontFamilyMember.font)
        .where(
            FontFamilyMember.family_id == family.id,
            Font.deleted_at.is_(None),
        )
        .order_by(FontFamilyMember.sort_order)
        .limit(1)
        .options(selectinload(FontFamilyMember.font))
    )
    first_member = result.scalar_one_or_none()

    preview_font = None
    if first_member and first_member.font:
        preview_font = FontPreview(
            id=first_member.font.id,
            full_name=first_member.font.full_name,
            file_format=first_member.font.file_format,
        )

    return FontFamilyResponse(
        id=family.id,
        name=family.name,
        slug=family.slug,
        classification=family.classification,
        description=family.description,
        designer=family.designer,
        manufacturer=family.manufacturer,
        style_count=family.style_count,
        is_auto_grouped=family.is_auto_grouped,
        preview_font=preview_font,
        created_at=family.created_at,
        updated_at=family.updated_at,
    )


# ---------- Liste paginée ----------


@router.get("", response_model=FontFamilyListResponse)
async def list_families(
    search: str | None = None,
    classification: str | None = None,
    sort: FamilySortField = FamilySortField.name,
    order: SortOrder = SortOrder.asc,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> FontFamilyListResponse:
    """Liste paginée des familles avec filtres."""
    query = select(FontFamily)

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                FontFamily.name.ilike(pattern),
                FontFamily.designer.ilike(pattern),
                FontFamily.manufacturer.ilike(pattern),
            )
        )

    if classification:
        query = query.where(FontFamily.classification == classification)

    # Compte total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Tri
    sort_column = getattr(FontFamily, sort.value)
    order_func = desc if order == SortOrder.desc else asc
    query = query.order_by(order_func(sort_column))

    # Pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    families = result.scalars().all()

    items = [await _build_family_response(f, db) for f in families]

    return FontFamilyListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total > 0 else 0,
    )


# ---------- Fusion (avant /{family_id} pour éviter les conflits de route) ----------


@router.post("/merge", response_model=MergeResult)
async def merge_families(
    body: MergeFamilies,
    db: AsyncSession = Depends(get_db),
) -> MergeResult:
    """Fusionne plusieurs familles en une seule.

    Si target_family_id est fourni, cette famille est conservée.
    Sinon, la famille avec le plus de styles est conservée.
    """
    # Charger toutes les familles
    families: list[FontFamily] = []
    for fid in body.family_ids:
        family = await _get_family_or_404(fid, db)
        families.append(family)

    # Déterminer la famille survivante
    if body.target_family_id is not None:
        survivor = next(
            (f for f in families if f.id == body.target_family_id), None
        )
        if survivor is None:
            raise HTTPException(
                status_code=400,
                detail="target_family_id doit faire partie de family_ids.",
            )
    else:
        # Automatique : garder celle avec le plus de styles
        survivor = max(families, key=lambda f: f.style_count)

    to_merge = [f for f in families if f.id != survivor.id]
    fonts_moved = 0

    for source_family in to_merge:
        # Récupérer les membres de la famille source
        result = await db.execute(
            select(FontFamilyMember).where(
                FontFamilyMember.family_id == source_family.id
            )
        )
        members = result.scalars().all()

        for member in members:
            member.family_id = survivor.id
            fonts_moved += 1

        # Flush les déplacements avant de supprimer la famille source
        await db.flush()
        # Supprimer la famille source (les membres sont déjà déplacés)
        await db.delete(source_family)

    # Recalculer style_count depuis les données réelles
    count_result = await db.execute(
        select(func.count()).where(FontFamilyMember.family_id == survivor.id)
    )
    survivor.style_count = count_result.scalar() or 0
    survivor.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return MergeResult(
        surviving_family_id=survivor.id,
        fonts_moved=fonts_moved,
        families_deleted=len(to_merge),
    )


# ---------- Regroupement (avant /{family_id} pour éviter les conflits de route) ----------


@router.post("/regroup", response_model=RegroupStats)
async def regroup_fonts(
    db: AsyncSession = Depends(get_db),
) -> RegroupStats:
    """Regroupe toutes les fonts en familles.

    Utile après la migration initiale ou pour recalculer les familles
    après un import massif.
    """
    stats = await regroup_all(db)
    await db.commit()
    return RegroupStats(**stats)


# ---------- Détail ----------


@router.get("/{family_id}", response_model=FontFamilyDetailResponse)
async def get_family(
    family_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FontFamilyDetailResponse:
    """Détail d'une famille avec ses membres triés par sort_order."""
    family = await _get_family_or_404(family_id, db)

    # Charger les membres avec leurs fonts
    result = await db.execute(
        select(FontFamilyMember)
        .where(FontFamilyMember.family_id == family.id)
        .order_by(FontFamilyMember.sort_order)
        .options(selectinload(FontFamilyMember.font))
    )
    members_rows = result.scalars().all()

    members = []
    preview_font = None
    for m in members_rows:
        font = m.font
        if font and font.deleted_at is None:
            if preview_font is None:
                preview_font = FontPreview(
                    id=font.id,
                    full_name=font.full_name,
                    file_format=font.file_format,
                )
            members.append(
                FamilyMemberResponse(
                    font_id=font.id,
                    sort_order=m.sort_order,
                    original_filename=font.original_filename,
                    full_name=font.full_name,
                    subfamily_name=font.subfamily_name,
                    postscript_name=font.postscript_name,
                    file_format=font.file_format,
                    file_size=font.file_size,
                    weight_class=font.weight_class,
                    is_italic=font.is_italic,
                    is_variable=font.is_variable,
                )
            )

    return FontFamilyDetailResponse(
        id=family.id,
        name=family.name,
        slug=family.slug,
        classification=family.classification,
        description=family.description,
        designer=family.designer,
        manufacturer=family.manufacturer,
        style_count=family.style_count,
        is_auto_grouped=family.is_auto_grouped,
        preview_font=preview_font,
        created_at=family.created_at,
        updated_at=family.updated_at,
        members=members,
    )


# ---------- Création ----------


@router.post("", response_model=FontFamilyResponse, status_code=201)
async def create_family(
    body: FontFamilyCreate,
    db: AsyncSession = Depends(get_db),
) -> FontFamilyResponse:
    """Crée une famille manuellement."""
    slug = await ensure_unique_slug(db, slugify(body.name))
    family = FontFamily(
        name=body.name,
        slug=slug,
        description=body.description,
        is_auto_grouped=False,
        style_count=0,
    )
    db.add(family)
    await db.commit()
    await db.refresh(family)
    return await _build_family_response(family, db)


# ---------- Modification ----------


@router.patch("/{family_id}", response_model=FontFamilyResponse)
async def update_family(
    family_id: uuid.UUID,
    body: FontFamilyUpdate,
    db: AsyncSession = Depends(get_db),
) -> FontFamilyResponse:
    """Modifie une famille."""
    family = await _get_family_or_404(family_id, db)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier.")

    # Si le nom change, recalculer le slug
    if "name" in update_data:
        family.slug = await ensure_unique_slug(db, slugify(update_data["name"]))

    for field, value in update_data.items():
        setattr(family, field, value)

    family.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(family)
    return await _build_family_response(family, db)


# ---------- Suppression ----------


@router.delete("/{family_id}", status_code=204)
async def delete_family(
    family_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Supprime une famille. Les fonts deviennent orphelines."""
    family = await _get_family_or_404(family_id, db)
    # Supprimer les membres (les fonts restent intactes)
    await db.execute(
        FontFamilyMember.__table__.delete().where(
            FontFamilyMember.family_id == family.id
        )
    )
    await db.delete(family)
    await db.commit()


# ---------- Gestion des fonts dans une famille ----------


@router.post("/{family_id}/fonts", response_model=FontFamilyDetailResponse)
async def add_fonts_to_family(
    family_id: uuid.UUID,
    body: AddFontsToFamily,
    db: AsyncSession = Depends(get_db),
) -> FontFamilyDetailResponse:
    """Ajoute une ou plusieurs fonts à cette famille."""
    family = await _get_family_or_404(family_id, db)

    for font_id in body.font_ids:
        # Vérifier que la font existe
        font_result = await db.execute(
            select(Font).where(Font.id == font_id, Font.deleted_at.is_(None))
        )
        font = font_result.scalar_one_or_none()
        if font is None:
            raise HTTPException(
                status_code=404, detail=f"Font {font_id} non trouvée."
            )

        # Retirer de la famille précédente si applicable
        existing = await db.execute(
            select(FontFamilyMember).where(FontFamilyMember.font_id == font_id)
        )
        old_member = existing.scalar_one_or_none()
        if old_member is not None:
            if old_member.family_id == family.id:
                continue  # Déjà dans cette famille
            old_family = await db.get(FontFamily, old_member.family_id)
            if old_family is not None:
                old_family.style_count = max(0, old_family.style_count - 1)
                old_family.updated_at = datetime.now(timezone.utc)
            await db.delete(old_member)
            await db.flush()

        # Ajouter à la nouvelle famille
        member = FontFamilyMember(
            font_id=font.id,
            family_id=family.id,
            sort_order=compute_sort_order(font.weight_class, font.is_italic),
        )
        db.add(member)
        family.style_count += 1

    family.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(family)

    # Retourner le détail complet
    return await get_family(family_id, db)


@router.delete("/{family_id}/fonts/{font_id}", status_code=204)
async def remove_font_from_family(
    family_id: uuid.UUID,
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Retire une font de la famille."""
    family = await _get_family_or_404(family_id, db)

    result = await db.execute(
        select(FontFamilyMember).where(
            FontFamilyMember.font_id == font_id,
            FontFamilyMember.family_id == family_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=404,
            detail="Cette font n'appartient pas à cette famille.",
        )

    await db.delete(member)
    family.style_count = max(0, family.style_count - 1)
    family.updated_at = datetime.now(timezone.utc)
    await db.commit()
