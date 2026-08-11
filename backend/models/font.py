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

    # LE verrou de propagation (M2). Remplace la liste blanche à trois valeurs de
    # `deleted_reason` par une question binaire lue à un seul endroit (cf. plus
    # bas). `deleted_reason` reste posé en parallèle jusqu'à M3 — double écriture,
    # lecture uniquement sur ce booléen. Défaut `False` = fail-safe : une police
    # tombée sans qu'on ait explicitement tranché ne se propage jamais.
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
# Depuis M2, la lecture porte sur `Font.deletion_confirmed` (`NOT NULL`) — plus
# de liste blanche à traduire, plus de logique ternaire à éviter.
# `deleted_reason` reste écrit en parallèle jusqu'à M3 (double écriture) mais
# n'est plus lu ici. **Chaque appel doit rester combiné à `deleted_at IS NOT
# NULL`** : le défaut `False` de `deletion_confirmed` est partagé par toute la
# bibliothèque vivante, pas seulement par les suppressions en attente.


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
