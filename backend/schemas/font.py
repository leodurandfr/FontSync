import uuid
from datetime import datetime
from enum import Enum

from backend.schemas.base import CamelModel


class FontSortField(str, Enum):
    """Champs de tri disponibles pour la liste des fonts (specs §5.1)."""

    name = "name"
    family_name = "family_name"
    created_at = "created_at"
    updated_at = "updated_at"
    file_size = "file_size"
    weight_class = "weight_class"
    glyph_count = "glyph_count"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class FontResponse(CamelModel):
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

    # Famille (renseignée sur le détail uniquement)
    family_id: uuid.UUID | None = None

    # Source
    source: str
    source_device_id: uuid.UUID | None = None
    source_device_name: str | None = None

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Pierre tombale — nuls pour une police de la bibliothèque.
    deleted_at: datetime | None = None
    deleted_reason: str | None = None
    """`manual`, `quarantine`, ou `quarantine_pending` (suppression détectée
    au-delà du seuil : en corbeille, mais non propagée sans confirmation)."""
    purged_at: datetime | None = None
    """Fichier retiré du stockage. La police n'est plus restaurable telle
    quelle ; seule son empreinte subsiste, pour que la suppression tienne."""

    model_config = {
        "from_attributes": True,
        "alias_generator": CamelModel.model_config["alias_generator"],
        "populate_by_name": True,
    }


class FontDeviceStatus(CamelModel):
    """Statut d'installation d'une font sur un appareil."""

    device_id: uuid.UUID
    device_name: str
    hostname: str
    is_online: bool = False
    installed: bool
    activated: bool = False
    local_path: str | None = None
    installed_at: datetime | None = None


class FontListResponse(CamelModel):
    """Réponse paginée pour la liste des fonts."""

    items: list[FontResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TrashListResponse(FontListResponse):
    """Corbeille : polices supprimées, plus le décompte des cas à trancher."""

    pending_confirmation: int = 0
    """Polices mises en quarantaine **au-delà du seuil** de propagation. Elles
    attendent un arbitrage : confirmer (les autres machines les désinstallent)
    ou restaurer. Tant que le compte n'est pas nul, aucune d'elles n'est
    propagée."""


class PurgeResponse(CamelModel):
    """Bilan d'un vidage de corbeille."""

    purged: int
    """Fichiers retirés du stockage. Les empreintes, elles, sont conservées :
    sans ça la police reviendrait au premier push d'une machine qui l'a encore."""


class ConfirmDeletionsResponse(CamelModel):
    """Bilan d'une confirmation de quarantaines en attente."""

    confirmed: int
    """Polices dont la suppression se propage désormais aux appareils."""


class FontUpdate(CamelModel):
    """Schéma pour la modification des métadonnées d'une font."""

    family_name: str | None = None
    subfamily_name: str | None = None
    full_name: str | None = None
    description: str | None = None
    classification: str | None = None
    designer: str | None = None
    manufacturer: str | None = None


class FontUploadResponse(CamelModel):
    """Réponse pour un upload de fonts (un ou plusieurs fichiers)."""

    imported: list[FontResponse]
    duplicates: list[FontResponse]
    errors: list[dict]


class ClassificationStat(CamelModel):
    classification: str | None
    count: int


class FormatStat(CamelModel):
    format: str
    count: int


class ScriptStat(CamelModel):
    script: str
    count: int


class StatsResponse(CamelModel):
    """Statistiques globales de la bibliothèque."""

    total_fonts: int
    by_classification: list[ClassificationStat]
    by_format: list[FormatStat]
    by_script: list[ScriptStat]
