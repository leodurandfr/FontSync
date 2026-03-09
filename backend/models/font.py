import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


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
    is_italic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_oblique: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    panose: Mapped[str | None] = mapped_column(String(30))

    # Classification
    classification: Mapped[str | None] = mapped_column(String(50))

    # Unicode / scripts
    unicode_ranges: Mapped[dict | None] = mapped_column(JSONB)
    supported_scripts: Mapped[list | None] = mapped_column(JSONB)

    # Glyphes
    glyph_count: Mapped[int | None] = mapped_column(Integer)

    # Variable fonts
    is_variable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    variable_axes: Mapped[dict | None] = mapped_column(JSONB)

    # Source
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    google_fonts_id: Mapped[str | None] = mapped_column(String(200))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Relations
    device_fonts: Mapped[list["DeviceFont"]] = relationship(back_populates="font")
    sync_queue_items: Mapped[list["SyncQueue"]] = relationship(back_populates="font")
    family_member: Mapped["FontFamilyMember | None"] = relationship(back_populates="font")

    __table_args__ = (
        Index("ix_fonts_family_name", "family_name"),
        Index("ix_fonts_classification", "classification"),
        Index("ix_fonts_file_hash", "file_hash"),
        Index("ix_fonts_source", "source"),
        Index("ix_fonts_deleted_at", "deleted_at"),
        Index("ix_fonts_supported_scripts", "supported_scripts", postgresql_using="gin"),
    )


from backend.models.device_font import DeviceFont  # noqa: E402
from backend.models.font_family import FontFamilyMember  # noqa: E402
from backend.models.sync_queue import SyncQueue  # noqa: E402
