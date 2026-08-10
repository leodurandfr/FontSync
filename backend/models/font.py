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
    or_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey

# ---------- Motifs de suppression ----------
#
# Une suppression est une **intention**, pas une observation : c'est ce qui rend
# la pierre tombale nécessaire. Sans motif, on ne peut pas distinguer « cette
# police a été supprimée » de « cette police est absente », et le push d'une
# machine qui détient encore le fichier la ressuscite (cf.
# `font_importer._revive_if_deleted`).

DELETION_MANUAL = "manual"
"""Supprimée depuis l'interface web. Se propage aux appareils."""

DELETION_QUARANTINE = "quarantine"
"""Disparue d'un appareil qui propage ses suppressions. Se propage aux autres."""

DELETION_PENDING = "quarantine_pending"
"""Disparition d'un appareil **au-delà du seuil** : mise en quarantaine (elle sort
de la bibliothèque, récupérable d'un clic) mais **non propagée** tant que
l'utilisateur n'a pas confirmé. C'est le garde-fou du nettoyage manuel massif :
personne d'autre ne perd son fichier sur la foi d'un seul scan."""

PROPAGATING_DELETION_REASONS = (DELETION_MANUAL, DELETION_QUARANTINE)
"""Motifs dont la suppression descend jusqu'aux appareils."""


class Font(UUIDPrimaryKey, Base):
    __tablename__ = "fonts"

    # Fichier
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)

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

    # Pierre tombale. `deleted_at` seul ne dit pas *pourquoi* : c'est
    # `deleted_reason` qui porte l'intention (cf. constantes en tête de module) et
    # qui empêche la résurrection au prochain push d'une machine qui détient
    # encore le fichier. Toujours renseigné quand `deleted_at` l'est.
    deleted_reason: Mapped[str | None] = mapped_column(String(30))

    # Fichier retiré du stockage (vidage de corbeille), **ligne conservée**.
    # L'empreinte (`file_hash`) doit survivre au fichier : sinon la police
    # reviendrait au push suivant, et une purge au jour 30 la ferait réapparaître
    # au jour 31.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
# l'échéance. Le prédicat vit ici plutôt qu'à ces trois endroits — dupliqué, il
# dériverait. (`sync_manager` pose la même question sur une ligne de résultat
# brute, pas sur un objet `Font` ; c'est la quatrième et dernière lecture.)
#
# Forme **liste blanche**, jamais négation : un motif absent ou inattendu reste
# NON confirmé, donc inerte. C'est le sens sûr — rien ne s'efface sur un doute.


def is_deletion_confirmed(font: Font) -> bool:
    """Cette suppression peut-elle produire un effet irréversible ?"""
    return font.deleted_reason in PROPAGATING_DELETION_REASONS


def deletion_confirmed_clause():
    """Version SQL de `is_deletion_confirmed`, pour un `WHERE`."""
    return Font.deleted_reason.in_(PROPAGATING_DELETION_REASONS)


def deletion_unconfirmed_clause():
    """Le complément — et **pas** `~deletion_confirmed_clause()`.

    En logique ternaire SQL, `NOT (NULL IN (…))` vaut NULL : une ligne au motif
    absent échapperait aux deux clauses à la fois, donc ne serait ni purgée ni
    comptée comme retenue. La forme explicite la range du bon côté.
    """
    return or_(
        Font.deleted_reason.is_(None),
        Font.deleted_reason.not_in(PROPAGATING_DELETION_REASONS),
    )


from backend.models.device_font import DeviceFont  # noqa: E402
from backend.models.font_family import FontFamilyMember  # noqa: E402
