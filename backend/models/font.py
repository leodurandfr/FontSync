import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


class Font(UUIDPrimaryKey, Base):
    __tablename__ = "fonts"

    # Fichier
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)

    # Métadonnées name table
    family_name: Mapped[str | None] = mapped_column(String(500))
    subfamily_name: Mapped[str | None] = mapped_column(String(200))
    full_name: Mapped[str | None] = mapped_column(String(500))
    postscript_name: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[str | None] = mapped_column(String(100))
    designer: Mapped[str | None] = mapped_column(String(500))
    manufacturer: Mapped[str | None] = mapped_column(String(500))
    license: Mapped[str | None] = mapped_column(Text)
    license_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)

    # OS/2 table
    weight_class: Mapped[int | None] = mapped_column(Integer)
    width_class: Mapped[int | None] = mapped_column(Integer)
    is_italic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_oblique: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    panose: Mapped[str | None] = mapped_column(String(30))

    # Classification
    classification: Mapped[str | None] = mapped_column(String(50))

    # Unicode / scripts
    unicode_ranges: Mapped[dict | None] = mapped_column(JSON)
    supported_scripts: Mapped[list | None] = mapped_column(JSON)

    # Glyphes
    glyph_count: Mapped[int | None] = mapped_column(Integer)

    # Variable fonts
    is_variable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    variable_axes: Mapped[dict | None] = mapped_column(JSON)

    # Source
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(), nullable=True)
    google_fonts_id: Mapped[str | None] = mapped_column(String(200))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Fichier retiré du stockage (vidage de corbeille), **ligne conservée**.
    # L'empreinte (`file_hash`) doit survivre au fichier : sinon la police
    # reviendrait au push suivant, et une purge au jour 30 la ferait réapparaître
    # au jour 31.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # LE verrou de propagation, seul et unique depuis M3 (remplace la liste
    # blanche à trois valeurs qu'était `deleted_reason`, retirée à cette même
    # révision). Défaut `False` = fail-safe : une police tombée sans qu'on ait
    # explicitement tranché ne se propage jamais.
    deletion_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False
    )

    # Mémoire du délai de grâce de la récolte (`docs/PLAN-ETATS-FONTS.md` §3.4,
    # G8) : posé quand une pierre tombale devient candidate, remis à `NULL` si un
    # appareil la redéclare entre-temps. Aucune lecture d'affichage.
    harvest_candidate_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Relations
    device_fonts: Mapped[list["DeviceFont"]] = relationship(back_populates="font")
    family_member: Mapped["FontFamilyMember | None"] = relationship(
        back_populates="font"
    )

    __table_args__ = (
        Index("ix_fonts_family_name", "family_name"),
        Index("ix_fonts_classification", "classification"),
        Index("ix_fonts_file_hash", "file_hash"),
        Index("ix_fonts_source", "source"),
        Index("ix_fonts_deleted_at", "deleted_at"),
    )


# ---------- « Cette suppression est-elle confirmée ? » ----------
#
# Une question binaire, posée par tout ce qui peut rendre une suppression
# irréversible : retirer le fichier du stockage, vider la corbeille, purger à
# l'échéance, récolter (`services/harvest.py`, G4). Le prédicat vit ici plutôt
# qu'à ces endroits — dupliqué, il dériverait. (`sync_manager` pose la même
# question sur une ligne de résultat brute, pas sur un objet `Font` ; elle lit
# directement `Font.deletion_confirmed`, pas ces helpers.)
#
# La lecture porte sur `Font.deletion_confirmed` (`NOT NULL`) — plus de liste
# blanche à traduire, plus de logique ternaire à éviter. **Chaque appel doit
# rester combiné à `deleted_at IS NOT NULL`** : le défaut `False` de
# `deletion_confirmed` est partagé par toute la bibliothèque vivante, pas
# seulement par les suppressions en attente.


def is_deletion_confirmed(font: Font) -> bool:
    """Cette suppression peut-elle produire un effet irréversible ?"""
    return font.deletion_confirmed


def deletion_confirmed_clause():
    """Version SQL de `is_deletion_confirmed`, pour un `WHERE`."""
    return Font.deletion_confirmed.is_(True)


def deletion_unconfirmed_clause():
    """Le complément explicite de `deletion_confirmed_clause`."""
    return Font.deletion_confirmed.is_(False)


from backend.models.device_font import DeviceFont  # noqa: E402
from backend.models.font_family import FontFamilyMember  # noqa: E402
