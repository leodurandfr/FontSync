"""Router pour la gestion des fonts."""

import logging
import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.models.font import Font
from backend.models.font_family import FontFamilyMember
from backend.schemas.font import (
    FontListResponse,
    FontResponse,
    FontSortField,
    FontUpdate,
    FontUploadResponse,
    SortOrder,
)
from backend.services.font_importer import FontImportError, import_font
from backend.services.storage import StorageBackend, get_storage_backend
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fonts", tags=["fonts"])


def get_storage() -> StorageBackend:
    return get_storage_backend()


# ---------- Upload ----------


@router.post("/upload", response_model=FontUploadResponse)
async def upload_fonts(
    files: list[UploadFile],
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> FontUploadResponse:
    """Upload un ou plusieurs fichiers de fonts."""
    imported: list[FontResponse] = []
    duplicates: list[FontResponse] = []
    errors: list[dict] = []

    for file in files:
        filename = file.filename or "unknown"
        try:
            file_data = await file.read()
            font, is_duplicate = await import_font(
                filename=filename,
                file_data=file_data,
                storage=storage,
                db=db,
            )
            font_response = FontResponse.model_validate(font)
            if is_duplicate:
                duplicates.append(font_response)
            else:
                imported.append(font_response)
        except FontImportError as e:
            errors.append({"filename": e.filename, "detail": e.detail})
        except Exception:
            logger.exception("Erreur inattendue lors de l'import de %s", filename)
            errors.append({"filename": filename, "detail": "Erreur interne du serveur."})

    # Notification WebSocket pour chaque font importée
    for font_resp in imported:
        message = {
            "type": "font.added",
            "data": font_resp.model_dump(mode="json", by_alias=True),
        }
        await ws_manager.broadcast_to_clients(message)
        await ws_manager.broadcast_to_agents(message)

    return FontUploadResponse(
        imported=imported,
        duplicates=duplicates,
        errors=errors,
    )


# ---------- Liste paginée avec filtres ----------


@router.get("", response_model=FontListResponse)
async def list_fonts(
    search: str | None = None,
    classification: str | None = None,
    file_format: str | None = Query(None, alias="format"),
    scripts: list[str] | None = Query(None),
    is_variable: bool | None = None,
    weight_min: int | None = None,
    weight_max: int | None = None,
    family_id: uuid.UUID | None = None,
    orphan: bool | None = None,
    sort: FontSortField = FontSortField.created_at,
    order: SortOrder = SortOrder.desc,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> FontListResponse:
    """Liste paginée des fonts avec filtres."""
    query = select(Font).where(Font.deleted_at.is_(None))

    # Filtre recherche textuelle
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Font.family_name.ilike(pattern),
                Font.full_name.ilike(pattern),
                Font.postscript_name.ilike(pattern),
                Font.original_filename.ilike(pattern),
                Font.designer.ilike(pattern),
            )
        )

    # Filtres exacts
    if classification:
        query = query.where(Font.classification == classification)
    if file_format:
        query = query.where(Font.file_format == file_format)
    if is_variable is not None:
        query = query.where(Font.is_variable == is_variable)

    # Filtre scripts (contient tous les scripts demandés)
    if scripts:
        query = query.where(Font.supported_scripts.contains(scripts))

    # Filtre weight range
    if weight_min is not None:
        query = query.where(Font.weight_class >= weight_min)
    if weight_max is not None:
        query = query.where(Font.weight_class <= weight_max)

    # Filtre famille
    if family_id is not None:
        query = query.join(FontFamilyMember, Font.id == FontFamilyMember.font_id).where(
            FontFamilyMember.family_id == family_id
        )
    elif orphan is True:
        # Fonts sans famille
        member_ids = select(FontFamilyMember.font_id)
        query = query.where(Font.id.notin_(member_ids))

    # Compte total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Tri
    sort_column = getattr(Font, sort.value)
    order_func = desc if order == SortOrder.desc else asc
    query = query.order_by(order_func(sort_column))

    # Pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    fonts = result.scalars().all()

    return FontListResponse(
        items=[FontResponse.model_validate(f) for f in fonts],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total > 0 else 0,
    )


# ---------- Détail ----------


async def _get_font_or_404(
    font_id: uuid.UUID, db: AsyncSession, *, include_deleted: bool = False
) -> Font:
    """Récupère une font par ID ou lève 404."""
    query = select(Font).where(Font.id == font_id)
    if not include_deleted:
        query = query.where(Font.deleted_at.is_(None))
    result = await db.execute(query)
    font = result.scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font non trouvée.")
    return font


@router.get("/{font_id}", response_model=FontResponse)
async def get_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Détail complet d'une font."""
    font = await _get_font_or_404(font_id, db)
    resp = FontResponse.model_validate(font)

    # Résoudre le nom du device source
    if font.source_device_id:
        device_result = await db.execute(
            select(Device.name).where(Device.id == font.source_device_id)
        )
        resp.source_device_name = device_result.scalar_one_or_none()

    return resp


# ---------- Téléchargement fichier ----------


MIME_TYPES: dict[str, str] = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttc": "font/collection",
}


@router.get("/{font_id}/file")
async def download_font_file(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Télécharge le fichier binaire de la font."""
    font = await _get_font_or_404(font_id, db)
    try:
        data = await storage.retrieve(font.file_hash, font.file_format)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable dans le stockage.")
    content_type = MIME_TYPES.get(font.file_format, "application/octet-stream")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{font.original_filename}"',
        },
    )


# ---------- Preview (pour @font-face) ----------


@router.get("/{font_id}/preview")
async def preview_font_file(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Fichier pour @font-face (preview dans le navigateur)."""
    font = await _get_font_or_404(font_id, db)
    try:
        data = await storage.retrieve(font.file_hash, font.file_format)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable dans le stockage.")
    content_type = MIME_TYPES.get(font.file_format, "application/octet-stream")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


# ---------- Modification ----------


@router.patch("/{font_id}", response_model=FontResponse)
async def update_font(
    font_id: uuid.UUID,
    body: FontUpdate,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Modifie les métadonnées d'une font."""
    font = await _get_font_or_404(font_id, db)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier.")
    for field, value in update_data.items():
        setattr(font, field, value)
    font.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(font)
    return FontResponse.model_validate(font)


# ---------- Soft delete ----------


@router.delete("/{font_id}", status_code=204)
async def delete_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete d'une font."""
    font = await _get_font_or_404(font_id, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ---------- Restauration ----------


@router.post("/{font_id}/restore", response_model=FontResponse)
async def restore_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Restaure une font supprimée (soft delete)."""
    font = await _get_font_or_404(font_id, db, include_deleted=True)
    if font.deleted_at is None:
        raise HTTPException(status_code=400, detail="Cette font n'est pas supprimée.")
    font.deleted_at = None
    font.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(font)
    return FontResponse.model_validate(font)
