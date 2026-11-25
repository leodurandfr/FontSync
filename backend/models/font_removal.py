"""Retrait **personnel** d'une police : un compte l'a supprimée d'un de ses Mac.

La bibliothèque est partagée, les Mac ne le sont pas. Supprimer une police sur
son Mac ne la retire donc pas de la bibliothèque (c'est le rôle de la corbeille,
réservée à l'admin) : cela dit seulement « je n'en veux plus sur mes machines ».

Conséquences, toutes limitées aux appareils du même compte :

- ses Mac ne la réinstallent plus (`missing_on_device` l'exclut) ;
- ses Mac qui l'acceptent (`propagate_deletions`) la désinstallent, une fois le
  retrait confirmé (`confirmed`) ;
- les Mac des autres comptes ne sont jamais concernés, admin compris.

`user_id` vide = appareils sans propriétaire (enregistrés avant la création du
premier compte, qui les adopte) : ils forment un seul groupe, comme un compte.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ColumnElement, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UUIDPrimaryKey


class FontRemoval(UUIDPrimaryKey, Base):
    __tablename__ = "font_removals"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    font_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("fonts.id", ondelete="CASCADE"), nullable=False
    )
    # Le Mac où la police a disparu (affichage seulement).
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Au-delà du seuil de disparitions (cf. `services/deletion_propagation.py`),
    # le retrait attend un oui avant de désinstaller quoi que ce soit ailleurs.
    # Il empêche déjà la réinstallation : ne rien réinstaller ne détruit rien.
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    __table_args__ = (
        Index("ix_font_removals_user_id", "user_id"),
        Index("ix_font_removals_font_id", "font_id"),
    )


def removal_scope(owner_user_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Les retraits d'un compte (ou du groupe des appareils sans propriétaire)."""
    if owner_user_id is None:
        return FontRemoval.user_id.is_(None)
    return FontRemoval.user_id == owner_user_id
