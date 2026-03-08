import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FontSortField(str, Enum):
    """Champs de tri disponibles pour la liste des fonts."""

    family_name = "family_name"
    created_at = "created_at"
    updated_at = "updated_at"
    file_size = "file_size"
    weight_class = "weight_class"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


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


class FontListResponse(BaseModel):
    """Réponse paginée pour la liste des fonts."""

    items: list[FontResponse]
    total: int
    page: int
    per_page: int
    pages: int


class FontUpdate(BaseModel):
    """Schéma pour la modification des métadonnées d'une font."""

    family_name: str | None = None
    subfamily_name: str | None = None
    full_name: str | None = None
    description: str | None = None
    classification: str | None = None
    designer: str | None = None
    manufacturer: str | None = None


class FontFilters(BaseModel):
    """Filtres pour la recherche de fonts."""

    search: str | None = None
    classification: str | None = None
    format: str | None = Field(None, alias="file_format")
    scripts: list[str] | None = None
    is_variable: bool | None = None
    weight_min: int | None = None
    weight_max: int | None = None
    sort: FontSortField = FontSortField.created_at
    order: SortOrder = SortOrder.desc
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)


class FontUploadResponse(BaseModel):
    """Réponse pour un upload de fonts (un ou plusieurs fichiers)."""

    imported: list[FontResponse]
    duplicates: list[FontResponse]
    errors: list[dict]


class ClassificationStat(BaseModel):
    classification: str | None
    count: int


class FormatStat(BaseModel):
    format: str
    count: int


class ScriptStat(BaseModel):
    script: str
    count: int


class StatsResponse(BaseModel):
    """Statistiques globales de la bibliothèque."""

    total_fonts: int
    by_classification: list[ClassificationStat]
    by_format: list[FormatStat]
    by_script: list[ScriptStat]
