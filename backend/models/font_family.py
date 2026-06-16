import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


class FontFamily(UUIDPrimaryKey, Base):
    """Famille de polices regroupant plusieurs styles."""

    __tablename__ = "font_families"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    designer: Mapped[str | None] = mapped_column(String(500))
    manufacturer: Mapped[str | None] = mapped_column(String(500))
    classification: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    style_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_auto_grouped: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    members: Mapped[list["FontFamilyMember"]] = relationship(
        back_populates="family", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_font_families_name", "name"),
        Index("ix_font_families_slug", "slug"),
    )


class FontFamilyMember(Base):
    """Association entre une font et sa famille (une font = une seule famille)."""

    __tablename__ = "font_family_members"

    font_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("fonts.id"),
        primary_key=True,
    )
    family_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("font_families.id"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relations
    family: Mapped["FontFamily"] = relationship(back_populates="members")
    font: Mapped["Font"] = relationship(back_populates="family_member")

    __table_args__ = (Index("ix_font_family_members_family_id", "family_id"),)


from backend.models.font import Font  # noqa: E402
