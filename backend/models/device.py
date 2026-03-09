from datetime import datetime

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


class Device(UUIDPrimaryKey, Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    os: Mapped[str] = mapped_column(String(50), nullable=False)
    os_version: Mapped[str | None] = mapped_column(String(100))
    agent_version: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    sync_status: Mapped[str] = mapped_column(
        String(20), default="idle", server_default=text("'idle'")
    )
    font_directories: Mapped[dict | None] = mapped_column(JSONB)
    auto_pull: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    auto_push: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )

    # Relations
    device_fonts: Mapped[list["DeviceFont"]] = relationship(back_populates="device")
    sync_queue_items: Mapped[list["SyncQueue"]] = relationship(back_populates="device")


from backend.models.device_font import DeviceFont  # noqa: E402
from backend.models.sync_queue import SyncQueue  # noqa: E402
