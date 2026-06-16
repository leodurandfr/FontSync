import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


class SyncQueue(UUIDPrimaryKey, Base):
    __tablename__ = "sync_queue"

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("devices.id"), nullable=False
    )
    font_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("fonts.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relations
    device: Mapped["Device"] = relationship(back_populates="sync_queue_items")
    font: Mapped["Font"] = relationship(back_populates="sync_queue_items")


from backend.models.device import Device  # noqa: E402
from backend.models.font import Font  # noqa: E402
