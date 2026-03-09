"""Service d'import de fonts.

Orchestre le pipeline complet : validation → hash → doublon → stockage → parsing → insertion.
"""

import hashlib
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.font import Font
from backend.services import font_analyzer
from backend.services.family_grouper import group_font
from backend.services.storage import StorageBackend

logger = logging.getLogger(__name__)

# Extensions acceptées
ALLOWED_EXTENSIONS: set[str] = {"ttf", "otf", "woff", "woff2", "ttc"}

# Magic bytes par format de font
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "ttf": [b"\x00\x01\x00\x00", b"true"],
    "otf": [b"OTTO"],
    "woff": [b"wOFF"],
    "woff2": [b"wOF2"],
    "ttc": [b"ttcf"],
}


class FontImportError(Exception):
    """Erreur lors de l'import d'une font."""

    def __init__(self, filename: str, detail: str) -> None:
        self.filename = filename
        self.detail = detail
        super().__init__(f"{filename}: {detail}")


def _validate_extension(filename: str) -> str:
    """Valide et retourne l'extension du fichier."""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FontImportError(
            filename,
            f"Extension '.{ext}' non supportée. "
            f"Formats acceptés : {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


def _validate_magic_bytes(filename: str, data: bytes, extension: str) -> None:
    """Vérifie que les magic bytes correspondent au format déclaré."""
    if len(data) < 4:
        raise FontImportError(filename, "Fichier trop petit pour être une font valide.")

    valid_magics = _MAGIC_BYTES.get(extension, [])
    header = data[:4]

    if valid_magics and not any(header.startswith(magic) for magic in valid_magics):
        raise FontImportError(
            filename,
            f"Le contenu du fichier ne correspond pas au format .{extension}.",
        )


def _compute_hash(data: bytes) -> str:
    """Calcule le SHA-256 du contenu du fichier."""
    return hashlib.sha256(data).hexdigest()


async def _check_duplicate(
    db: AsyncSession, file_hash: str
) -> Font | None:
    """Vérifie si une font avec le même hash existe déjà en base."""
    stmt = select(Font).where(Font.file_hash == file_hash, Font.deleted_at.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def import_font(
    filename: str,
    file_data: bytes,
    storage: StorageBackend,
    db: AsyncSession,
    source: str = "upload",
) -> tuple[Font, bool]:
    """Importe une font : validation, stockage, parsing, insertion.

    Args:
        filename: Nom original du fichier.
        file_data: Contenu binaire du fichier.
        storage: Backend de stockage.
        db: Session de base de données.
        source: Source de l'import (upload, local_scan, google_fonts).

    Returns:
        Tuple (Font, is_duplicate) : le modèle Font et un booléen
        indiquant si c'est un doublon.

    Raises:
        FontImportError: Si le fichier est invalide.
    """
    # 1. Validation extension
    extension = _validate_extension(filename)

    # 2. Validation magic bytes
    _validate_magic_bytes(filename, file_data, extension)

    # 3. Calcul SHA-256
    file_hash = _compute_hash(file_data)

    # 4. Vérification doublon
    existing = await _check_duplicate(db, file_hash)
    if existing is not None:
        return existing, True

    # 5. Stockage
    storage_path = await storage.store(file_hash, file_data, extension)

    # 6. Parsing via font_analyzer (nécessite un fichier temporaire)
    metadata: dict = {}
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{extension}", delete=True) as tmp:
            tmp.write(file_data)
            tmp.flush()
            metadata = font_analyzer.analyze(tmp.name)
    except Exception:
        logger.warning(
            "Parsing partiel pour %s (hash=%s)", filename, file_hash, exc_info=True
        )

    # 7. Insertion en base
    font = Font(
        file_hash=file_hash,
        original_filename=filename,
        file_size=len(file_data),
        file_format=extension,
        storage_path=storage_path,
        source=source,
        # Métadonnées parsées
        family_name=metadata.get("family_name"),
        subfamily_name=metadata.get("subfamily_name"),
        full_name=metadata.get("full_name"),
        postscript_name=metadata.get("postscript_name"),
        version=metadata.get("version"),
        designer=metadata.get("designer"),
        manufacturer=metadata.get("manufacturer"),
        license=metadata.get("license"),
        license_url=metadata.get("license_url"),
        description=metadata.get("description"),
        weight_class=metadata.get("weight_class"),
        width_class=metadata.get("width_class"),
        is_italic=metadata.get("is_italic", False),
        is_oblique=metadata.get("is_oblique", False),
        panose=metadata.get("panose"),
        classification=metadata.get("classification"),
        supported_scripts=metadata.get("supported_scripts"),
        glyph_count=metadata.get("glyph_count"),
        is_variable=metadata.get("is_variable", False),
        variable_axes=metadata.get("variable_axes"),
    )

    db.add(font)
    await db.flush()
    await db.refresh(font)

    # 8. Regroupement en famille
    try:
        await group_font(font, db)
    except Exception:
        logger.warning(
            "Échec du regroupement en famille pour %s (id=%s)", filename, font.id,
            exc_info=True,
        )

    await db.commit()

    return font, False
