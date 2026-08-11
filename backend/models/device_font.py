import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class DeviceFont(Base):
    __tablename__ = "device_fonts"

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("devices.id"), primary_key=True
    )
    font_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("fonts.id"), primary_key=True
    )
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    activated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Ce détenteur peut-il alimenter la bibliothèque synchronisée ? `False` pour
    # une police scannée hors de `scan.ingest_directories` (ex. `/Library/Fonts`,
    # dossier tous-utilisateurs jamais nettoyé par l'agent) : elle reste visible
    # comme présente sur la machine, mais un push ne l'y offre plus et sa
    # présence ne protège plus une pierre tombale ailleurs. Défaut `True` — un
    # agent qui ne connaît pas encore ce champ **bloque** la récolte, jamais
    # l'inverse.
    ingestible: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_device_fonts_font_id", "font_id"),)

    # Relations
    device: Mapped["Device"] = relationship(back_populates="device_fonts")
    font: Mapped["Font"] = relationship(back_populates="device_fonts")


from backend.models.device import Device  # noqa: E402
from backend.models.font import Font  # noqa: E402
