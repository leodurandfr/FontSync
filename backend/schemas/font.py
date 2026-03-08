import uuid
from datetime import datetime

from pydantic import BaseModel


class FontResponse(BaseModel):
    """Schéma de réponse pour une font."""

    id: uuid.UUID
    file_hash: str
    original_filename: str
    file_size: int
    file_format: str
    storage_path: str

    # Métadonnées name table
    family_name: str | None = None
    subfamily_name: str | None = None
    full_name: str | None = None
    postscript_name: str | None = None
    version: str | None = None
    designer: str | None = None
    manufacturer: str | None = None
    license: str | None = None
    license_url: str | None = None
    description: str | None = None

    # OS/2
    weight_class: int | None = None
    width_class: int | None = None
    is_italic: bool = False
    is_oblique: bool = False
    panose: str | None = None

    # Classification
    classification: str | None = None

    # Unicode / scripts
    unicode_ranges: dict | None = None
    supported_scripts: list | None = None

    # Glyphes
    glyph_count: int | None = None

    # Variable fonts
    is_variable: bool = False
    variable_axes: list | None = None

    # Source
    source: str

    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FontUploadResponse(BaseModel):
    """Réponse pour un upload de fonts (un ou plusieurs fichiers)."""

    imported: list[FontResponse]
    duplicates: list[FontResponse]
    errors: list[dict]
