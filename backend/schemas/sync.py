"""Schémas Pydantic pour la synchronisation."""

import uuid

from pydantic import Field

from backend.schemas.base import CamelModel


class DeviceFontEntry(CamelModel):
    """Entrée d'une font côté agent : hash + nom de fichier."""

    hash: str = Field(..., min_length=64, max_length=64)
    filename: str


class DeltaSyncRequest(CamelModel):
    """Requête delta sync envoyée par un agent."""

    device_id: uuid.UUID
    fonts: list[DeviceFontEntry]


class FontRef(CamelModel):
    """Référence minimale à une font pour la réponse delta."""

    id: uuid.UUID
    file_hash: str
    original_filename: str
    file_format: str
    family_name: str | None = None
    file_size: int


class DeltaSyncResponse(CamelModel):
    """Réponse du delta sync."""

    unknown_to_server: list[str]
    """Hashes de fonts que le serveur ne connaît pas (à pusher par l'agent)."""

    missing_on_device: list[FontRef]
    """Fonts présentes sur le serveur mais absentes du device (à puller)."""

    already_synced: int
    """Nombre de fonts déjà synchronisées."""


class PushResponse(CamelModel):
    """Réponse après un push de font depuis un agent."""

    font_id: uuid.UUID
    file_hash: str
    is_duplicate: bool
    family_name: str | None = None
