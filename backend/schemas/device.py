"""Schémas Pydantic pour les devices."""

import uuid
from datetime import datetime

from pydantic import Field

from backend.schemas.base import CamelModel


class DeviceRegister(CamelModel):
    """Schéma d'enregistrement d'un device."""

    device_id: uuid.UUID | None = None
    """Identité persistée par l'agent depuis son premier enregistrement. Elle
    prime sur le hostname, qui change avec le réseau sous macOS et créait une
    ligne par variante. Absente au tout premier `register`."""

    name: str = Field(..., max_length=200)
    hostname: str = Field(..., max_length=200)
    os: str = Field(..., max_length=50)
    os_version: str | None = Field(None, max_length=100)
    agent_version: str | None = Field(None, max_length=20)
    font_directories: list[str] | None = None
    auto_pull: bool = False
    auto_push: bool = True


class DeviceUpdate(CamelModel):
    """Schéma de mise à jour d'un device."""

    name: str | None = Field(None, max_length=200)
    agent_version: str | None = Field(None, max_length=20)
    font_directories: list[str] | None = None
    auto_pull: bool | None = None
    auto_push: bool | None = None
    # Réglage volontairement distinct d'auto_pull/auto_push : ces deux-là ne
    # promettent que d'envoyer et d'installer. Les rendre destructeurs serait
    # une trahison de leur nom. Piloté depuis le frontend uniquement — l'agent
    # ne se l'attribue jamais à l'enregistrement.
    propagate_deletions: bool | None = None


class DeviceMerge(CamelModel):
    """Fusion d'appareils en double dans un seul."""

    source_device_ids: list[uuid.UUID] = Field(..., min_length=1)
    """Appareils à absorber puis supprimer. Leurs polices sont réaffectées à la
    cible : c'est tout l'intérêt de fusionner plutôt que de supprimer."""


class DeviceMergeResponse(CamelModel):
    """Bilan d'une fusion."""

    device: "DeviceResponse"
    fonts_moved: int
    """Associations réaffectées à la cible (celles qu'elle avait déjà sont
    simplement retirées du doublon, pas comptées)."""
    devices_removed: int


class DeviceResponse(CamelModel):
    """Schéma de réponse pour un device."""

    id: uuid.UUID
    name: str
    hostname: str
    os: str
    os_version: str | None = None
    agent_version: str | None = None
    last_seen_at: datetime | None = None
    font_directories: list[str] | None = None
    auto_pull: bool
    auto_push: bool
    propagate_deletions: bool = False
    created_at: datetime
    # Présence « en ligne » : calculée à la volée depuis les connexions SSE
    # `listen` (cf. routeur), pas une colonne en base.
    is_online: bool = False

    model_config = {
        "from_attributes": True,
        "alias_generator": CamelModel.model_config["alias_generator"],
        "populate_by_name": True,
    }


DeviceMergeResponse.model_rebuild()
