"""Schémas des retraits personnels (`/api/me/removals`)."""

import uuid
from datetime import datetime

from backend.schemas.base import CamelModel


class FontRemovalResponse(CamelModel):
    font_id: uuid.UUID
    family_name: str | None = None
    full_name: str | None = None
    original_filename: str
    removed_at: datetime
    confirmed: bool
    """`False` : au-delà du seuil, rien n'est désinstallé sur les autres Mac du
    compte avant un oui (`POST /api/me/removals/confirm`)."""
    source_device_name: str | None = None


class RemovalsConfirmed(CamelModel):
    confirmed: int
