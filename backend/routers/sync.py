"""Router pour la synchronisation agent ↔ serveur."""

import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.models.font import Font
from backend.schemas.font import FontResponse
from backend.schemas.sync import DeltaSyncRequest, DeltaSyncResponse, PushResponse
from backend.services.font_importer import FontImportError, import_font
from backend.services.storage import StorageBackend, get_storage_backend
from backend.services.sync_manager import compute_delta, register_device_font
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

MIME_TYPES: dict[str, str] = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttc": "font/collection",
}


def get_storage() -> StorageBackend:
    return get_storage_backend()


async def _get_device_or_404(device_id: uuid.UUID, db: AsyncSession) -> Device:
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trouvé.")
    return device


@router.post("/delta", response_model=DeltaSyncResponse)
async def delta_sync(
    body: DeltaSyncRequest,
    db: AsyncSession = Depends(get_db),
) -> DeltaSyncResponse:
    """Delta sync : compare les fonts de l'agent avec le serveur.

    L'agent envoie la liste de ses {hash, filename}. Le serveur retourne :
    - unknown_to_server : hashes à pusher
    - missing_on_device : fonts à puller
    - already_synced : nombre de fonts en commun
    """
    # Vérifier que le device existe
    await _get_device_or_404(body.device_id, db)
    return await compute_delta(body.device_id, body.fonts, db)


@router.post("/push", response_model=PushResponse)
async def push_font(
    file: UploadFile,
    device_id: uuid.UUID = Form(...),
    local_path: str = Form(""),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> PushResponse:
    """Push d'une font depuis un agent vers le serveur.

    Utilise le pipeline d'import standard, puis enregistre l'association device ↔ font.
    """
    # Vérifier que le device existe
    device = await _get_device_or_404(device_id, db)

    filename = file.filename or "unknown"
    file_data = await file.read()

    try:
        font, is_duplicate = await import_font(
            filename=filename,
            file_data=file_data,
            storage=storage,
            db=db,
            source="local_scan",
        )
    except FontImportError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    # Mettre à jour source_device_id si c'est une nouvelle font
    if not is_duplicate and font.source_device_id is None:
        font.source_device_id = device.id
        await db.commit()
        await db.refresh(font)

    # Enregistrer l'association device ↔ font
    await register_device_font(
        device_id=device.id,
        font_id=font.id,
        local_path=local_path or filename,
        db=db,
    )
    await db.commit()

    # Notifications WebSocket
    if not is_duplicate:
        font_resp = FontResponse.model_validate(font)
        font_data = font_resp.model_dump(mode="json", by_alias=True)
        # Notifier les clients frontend
        await ws_manager.broadcast_to_clients({
            "type": "font.added",
            "data": font_data,
        })
        # Notifier les autres agents qu'une nouvelle font est disponible
        await ws_manager.broadcast_to_agents({
            "type": "font.available",
            "data": font_data,
        })

    return PushResponse(
        font_id=font.id,
        file_hash=font.file_hash,
        is_duplicate=is_duplicate,
        family_name=font.family_name,
    )


@router.get("/pull/{font_id}")
async def pull_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Retourne le fichier font pour installation par l'agent."""
    result = await db.execute(
        select(Font).where(Font.id == font_id, Font.deleted_at.is_(None))
    )
    font = result.scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font non trouvée.")

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
