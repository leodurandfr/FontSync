"""Schémas Pydantic pour les devices."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DeviceRegister(BaseModel):
    """Schéma d'enregistrement d'un device."""

    name: str = Field(..., max_length=200)
    hostname: str = Field(..., max_length=200)
    os: str = Field(..., max_length=50)
    os_version: str | None = Field(None, max_length=100)
    agent_version: str | None = Field(None, max_length=20)
    font_directories: list[str] | None = None
    auto_pull: bool = False


class DeviceUpdate(BaseModel):
    """Schéma de mise à jour d'un device."""

    name: str | None = Field(None, max_length=200)
    agent_version: str | None = Field(None, max_length=20)
    font_directories: list[str] | None = None
    auto_pull: bool | None = None
    sync_status: str | None = Field(None, pattern=r"^(idle|syncing|error)$")


class DeviceResponse(BaseModel):
    """Schéma de réponse pour un device."""

    id: uuid.UUID
    name: str
    hostname: str
    os: str
    os_version: str | None = None
    agent_version: str | None = None
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    sync_status: str
    font_directories: list[str] | None = None
    auto_pull: bool
    created_at: datetime

    model_config = {"from_attributes": True}
