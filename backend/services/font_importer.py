"""Service d'import de fonts.

Orchestre le pipeline complet : validation → hash → doublon → stockage → parsing → insertion.
"""

import hashlib
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    "ttf": [b"\x00\x01\x00\x00", b"true", b"OTTO"],
    "otf": [b"OTTO", b"\x00\x01\x00\x00"],
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


async def _safe_delete_storage(
    storage: StorageBackend, file_hash: str, extension: str
) -> None:
    """Supprime un fichier stocké sans jamais propager d'erreur de nettoyage."""
    try:
        await storage.delete(file_hash, extension)
    except Exception:
        logger.warning(
            "Nettoyage du fichier orphelin échoué (hash=%s)", file_hash, exc_info=True
        )


async def _find_by_hash(db: AsyncSession, file_hash: str) -> Font | None:
    """Recherche une font par hash, qu'elle soit active ou soft-deleted.

    Le hash porte la contrainte d'unicité : il ne peut exister qu'une seule
    ligne par contenu, **y compris** si elle a été soft-deleted. On ne filtre
    donc pas sur ``deleted_at`` ici (sinon on tenterait un INSERT en doublon
    sur une font supprimée et on lèverait une IntegrityError).
    """
    result = await db.execute(select(Font).where(Font.file_hash == file_hash))
    return result.scalar_one_or_none()


async def _revive_if_deleted(font: Font, db: AsyncSession) -> None:
    """Ressuscite une font soft-deleted ré-importée (import idempotent).

    Ré-importer un contenu identique signifie « cette font est de nouveau
    présente » : on annule le soft-delete et on la re-rattache à sa famille.
    """
    if font.deleted_at is None:
        return
    font.deleted_at = None
    await db.commit()
    await db.refresh(font)
    try:
        await group_font(font, db)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "Échec du regroupement après réveil de la font %s", font.id, exc_info=True
        )


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

    # 4. Vérification doublon (idempotence). Une font soft-deleted est
    #    ressuscitée plutôt que ré-insérée (le hash est unique en base).
    existing = await _find_by_hash(db, file_hash)
    if existing is not None:
        await _revive_if_deleted(existing, db)
        return existing, True

    # 5. Stockage. Le chemin est déterministe (dérivé du hash) : ré-écrire le
    #    même contenu est idempotent. En cas de doublon concurrent, le fichier
    #    appartient légitimement à la font existante (même hash → même chemin).
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
        unicode_ranges=metadata.get("unicode_ranges"),
        supported_scripts=metadata.get("supported_scripts"),
        glyph_count=metadata.get("glyph_count"),
        is_variable=metadata.get("is_variable", False),
        variable_axes=metadata.get("variable_axes"),
    )

    db.add(font)
    try:
        await db.flush()
        await db.refresh(font)
        await db.commit()
    except IntegrityError:
        # Push concurrent du même hash : l'autre transaction a déjà inséré la
        # font. On la récupère et on la retourne comme doublon (idempotence).
        await db.rollback()
        existing = await _find_by_hash(db, file_hash)
        if existing is not None:
            await _revive_if_deleted(existing, db)
            return existing, True
        # Conflit sans ligne correspondante (anormal) : pas de fichier orphelin.
        await _safe_delete_storage(storage, file_hash, extension)
        raise FontImportError(filename, "Conflit d'insertion en base de données.")
    except Exception:
        # Échec d'insertion non lié à un doublon : ne pas laisser le fichier
        # stocké à l'étape 5 en orphelin sur le disque.
        await db.rollback()
        await _safe_delete_storage(storage, file_hash, extension)
        raise

    # 8. Regroupement en famille — best-effort, isolé de l'insertion de la font.
    #    Un échec ici ne doit jamais annuler l'import (font malformée stockée
    #    avec des métadonnées partielles, cf. CLAUDE.md).
    try:
        await group_font(font, db)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "Échec du regroupement en famille pour %s (id=%s)",
            filename,
            font.id,
            exc_info=True,
        )

    return font, False
