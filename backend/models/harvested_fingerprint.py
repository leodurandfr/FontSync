"""Empreinte minimale d'une police récoltée (M-29, `services/harvest.py`).

La récolte supprime la ligne `fonts` d'une pierre tombale : métadonnées,
registre, famille. Sans trace, son hash redeviendrait inconnu, le delta le
réclamerait au push et la police reviendrait comme neuve — « vider la corbeille
conserve l'empreinte » ne serait vrai que jusqu'à la récolte. Cette table garde
le seul hash : le delta le tient pour connu (jamais réclamé), le push agent est
refusé, et seul un upload web explicite (le geste de l'utilisateur vaut oui)
ramène la police et retire l'empreinte.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, UUIDPrimaryKey


class HarvestedFingerprint(UUIDPrimaryKey, Base):
    __tablename__ = "harvested_fingerprints"

    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Date de la suppression d'origine (celle de la pierre tombale récoltée).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    harvested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
