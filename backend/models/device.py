from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, UUIDPrimaryKey


class Device(UUIDPrimaryKey, Base):
    __tablename__ = "devices"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    os: Mapped[str] = mapped_column(String(50), nullable=False)
    os_version: Mapped[str | None] = mapped_column(String(100))
    agent_version: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(String(20), default="idle")
    font_directories: Mapped[dict | None] = mapped_column(JSON)
    auto_pull: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_push: Mapped[bool] = mapped_column(Boolean, default=True)
    # Participation de cet appareil à la **propagation des suppressions**, dans
    # les deux sens : ses suppressions locales mettent la police en quarantaine
    # côté serveur, et une police supprimée côté serveur y est désinstallée.
    #
    # Réglage distinct d'`auto_push`/`auto_pull` à dessein : ces deux mots ne
    # promettent aujourd'hui que d'envoyer et d'installer. Les activer ne doit
    # pas devenir destructeur. Défaut `False` — on n'efface rien sans un oui.
    propagate_deletions: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    device_fonts: Mapped[list["DeviceFont"]] = relationship(back_populates="device")


from backend.models.device_font import DeviceFont  # noqa: E402
