import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


class DeviceFont(Base):
    __tablename__ = "device_fonts"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True
    )
    font_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fonts.id"), primary_key=True
    )
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    activated: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    # Relations
    device: Mapped["Device"] = relationship(back_populates="device_fonts")
    font: Mapped["Font"] = relationship(back_populates="device_fonts")


from backend.models.device import Device  # noqa: E402
from backend.models.font import Font  # noqa: E402
