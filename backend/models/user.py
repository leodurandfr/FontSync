"""Comptes, sessions et invitations.

La bibliothèque de polices est **partagée** par tous les comptes d'une instance :
un compte dit qui peut entrer et à qui appartient un appareil, pas qui possède
une police. Chaque connexion (un navigateur, un Mac) a sa propre ligne
`auth_sessions` : un même compte peut être connecté sur plusieurs machines, et
chacune se révoque seule.

Aucun secret n'est stocké en clair : mots de passe en argon2id, jetons de
session et d'invitation en SHA-256 (ce sont des valeurs aléatoires de 256 bits,
un hachage lent n'apporterait rien).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UUIDPrimaryKey

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLES = (ROLE_ADMIN, ROLE_MEMBER)

SESSION_WEB = "web"
SESSION_DEVICE = "device"


class User(UUIDPrimaryKey, Base):
    __tablename__ = "users"

    # Toujours en minuscules (normalisé à l'écriture) : l'unicité vaut sans casse.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_MEMBER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Un compte désactivé ne se connecte plus, ses sessions sont révoquées. La
    # ligne reste : ses appareils gardent un propriétaire identifiable.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(UUIDPrimaryKey, Base):
    """Une connexion : un navigateur (`web`) ou un appareil (`device`)."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Session `device` : l'appareil auquel le jeton est lié. Vide jusqu'au
    # premier `register` de l'agent, qui l'attache (cf. `routers/devices.py`).
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("devices.id", ondelete="SET NULL")
    )
    # Ce que l'utilisateur voit dans « Mes sessions » (nom du Mac, navigateur).
    label: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Vide = pas d'expiration (jeton d'appareil). Les sessions web glissent.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(UUIDPrimaryKey, Base):
    """Lien d'invitation à usage unique, copié par l'admin (pas d'email sortant).

    L'invité choisit lui-même son email en ouvrant le lien. `email` n'est
    renseigné que pour les invitations créées avant ce choix : le compte
    créé reprend alors cette adresse."""

    __tablename__ = "invitations"

    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_MEMBER)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
