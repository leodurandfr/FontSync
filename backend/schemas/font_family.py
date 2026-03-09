"""Schémas Pydantic pour les familles de polices."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field

from backend.schemas.base import CamelModel


# ---------- Enums ----------


class FamilySortField(str, Enum):
    name = "name"
    style_count = "style_count"
    created_at = "created_at"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


# ---------- Sous-objets ----------


class FontPreview(CamelModel):
    """Aperçu minimal d'une font pour la liste des familles."""

    id: uuid.UUID
    full_name: str | None = None
    file_format: str

    model_config = {
        "from_attributes": True,
        "alias_generator": CamelModel.model_config["alias_generator"],
        "populate_by_name": True,
    }


class FamilyMemberResponse(CamelModel):
    """Un membre (style) d'une famille, avec les infos de la font."""

    font_id: uuid.UUID
    sort_order: int
    # Champs de la font
    original_filename: str
    full_name: str | None = None
    subfamily_name: str | None = None
    postscript_name: str | None = None
    file_format: str
    file_size: int
    weight_class: int | None = None
    is_italic: bool = False
    is_variable: bool = False

    model_config = {
        "from_attributes": True,
        "alias_generator": CamelModel.model_config["alias_generator"],
        "populate_by_name": True,
    }


# ---------- Réponses ----------


class FontFamilyResponse(CamelModel):
    """Réponse pour une famille dans la liste."""

    id: uuid.UUID
    name: str
    slug: str
    classification: str | None = None
    description: str | None = None
    designer: str | None = None
    manufacturer: str | None = None
    style_count: int
    is_auto_grouped: bool
    preview_font: FontPreview | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
        "alias_generator": CamelModel.model_config["alias_generator"],
        "populate_by_name": True,
    }


class FontFamilyDetailResponse(FontFamilyResponse):
    """Réponse détaillée d'une famille avec ses membres."""

    members: list[FamilyMemberResponse] = []


class FontFamilyListResponse(CamelModel):
    """Réponse paginée pour la liste des familles."""

    items: list[FontFamilyResponse]
    total: int
    page: int
    per_page: int
    pages: int


# ---------- Entrées ----------


class FontFamilyCreate(CamelModel):
    """Création manuelle d'une famille."""

    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = None


class FontFamilyUpdate(CamelModel):
    """Modification d'une famille."""

    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    classification: str | None = None


class AddFontsToFamily(CamelModel):
    """Ajout de fonts à une famille."""

    font_ids: list[uuid.UUID] = Field(..., min_length=1)


class MergeFamilies(CamelModel):
    """Fusion de plusieurs familles."""

    family_ids: list[uuid.UUID] = Field(..., min_length=2)
    target_family_id: uuid.UUID | None = None


class MergeResult(CamelModel):
    """Résultat d'une fusion de familles."""

    surviving_family_id: uuid.UUID
    fonts_moved: int
    families_deleted: int


# ---------- Regroup ----------


class RegroupStats(CamelModel):
    """Statistiques retournées par le regroupement des fonts en familles."""

    families_created: int
    fonts_grouped: int
    fonts_skipped: int
