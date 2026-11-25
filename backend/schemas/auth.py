"""Schémas Pydantic des comptes, sessions et invitations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.schemas.base import CamelModel
from backend.services.accounts import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

Role = Literal["admin", "member"]

# Pas de validation d'email stricte (pas d'envoi de mail : l'adresse n'est
# qu'un identifiant) ; juste de quoi refuser l'évidemment faux.
_EMAIL = Field(..., min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
_NEW_PASSWORD = Field(
    ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
)
_PASSWORD = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)


class SetupRequest(CamelModel):
    email: str = _EMAIL
    password: str = _NEW_PASSWORD
    legacy_token: str | None = Field(None, max_length=512)
    """Requis si `FONTSYNC_TOKEN` est défini : prouve que la personne qui crée
    l'admin d'un serveur déjà installé en est bien le propriétaire."""


class LoginRequest(CamelModel):
    email: str = Field(..., max_length=320)
    password: str = _PASSWORD


class DeviceLoginRequest(LoginRequest):
    device_name: str | None = Field(None, max_length=200)


class PasswordChange(CamelModel):
    current_password: str = _PASSWORD
    new_password: str = _NEW_PASSWORD


class PasswordReset(CamelModel):
    password: str = _NEW_PASSWORD


class InvitationLookup(CamelModel):
    token: str = Field(..., min_length=1, max_length=512)


class InvitationAccept(InvitationLookup):
    password: str = _NEW_PASSWORD


class InvitationCreate(CamelModel):
    email: str = _EMAIL
    role: Role = "member"


class UserUpdate(CamelModel):
    role: Role | None = None
    disabled: bool | None = None


class UserResponse(CamelModel):
    id: uuid.UUID
    email: str
    role: str
    created_at: datetime
    disabled_at: datetime | None = None
    device_count: int = 0
    session_count: int = 0


class MeResponse(CamelModel):
    """L'identité de la requête. `user` est vide pour le token hérité."""

    kind: str
    role: str
    user: UserResponse | None = None
    device_id: uuid.UUID | None = None


class AuthStatus(CamelModel):
    setup_required: bool
    """Aucun compte n'existe : l'interface propose de créer l'admin."""
    setup_needs_legacy_token: bool
    """Un `FONTSYNC_TOKEN` est défini : la création de l'admin le demande."""
    legacy_token_enabled: bool
    me: MeResponse | None = None


class DeviceLoginResponse(CamelModel):
    token: str
    """Jeton d'appareil, montré une seule fois. À ranger dans
    `server.device_token` de `~/.fontsync/config.yaml`."""
    user: UserResponse


class SessionResponse(CamelModel):
    id: uuid.UUID
    kind: str
    label: str | None = None
    device_id: uuid.UUID | None = None
    user_id: uuid.UUID
    user_email: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    current: bool = False


class InvitationResponse(CamelModel):
    id: uuid.UUID
    email: str
    role: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


class InvitationCreated(CamelModel):
    invitation: InvitationResponse
    token: str
    """Montré une seule fois. L'interface en fait un lien `/invite#<token>` (le
    fragment n'est jamais envoyé au serveur, donc jamais journalisé)."""


class InvitationInfo(CamelModel):
    email: str
    role: str
