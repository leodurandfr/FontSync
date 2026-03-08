"""Router pour la gestion des fonts."""

import logging

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.font import FontResponse, FontUploadResponse
from backend.services.font_importer import FontImportError, import_font
from backend.services.storage import StorageBackend, get_storage_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fonts", tags=["fonts"])


def get_storage() -> StorageBackend:
    return get_storage_backend()


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

    return FontUploadResponse(
        imported=imported,
        duplicates=duplicates,
        errors=errors,
    )
