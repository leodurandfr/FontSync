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
    # Dernier delta CRÉDIBLE traité (déclaration non vide, non suspecte). Sert de
    # borne à la récolte de pierres tombales : `last_seen_at` ne peut pas jouer ce
    # rôle, il est posé par le register HTTP — donc avant le delta — et déplacé
    # par un simple PATCH depuis l'UI.
    last_declaration_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Soft delete : l'appareil sort de l'UI mais son registre `device_fonts`
    # reste — il continue de protéger les pierres tombales qu'il détient
    # (convention `CLAUDE.md`). `register_device` le ranime.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
