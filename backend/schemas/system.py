"""Schémas Pydantic pour l'état et la mise à jour du serveur."""

from datetime import datetime

from backend.schemas.base import CamelModel


class SystemInfo(CamelModel):
    """État du serveur tel que l'interface a besoin de le connaître."""

    version: str
    """Version de l'image en cours d'exécution, injectée au build.
    `dev` quand le serveur ne tourne pas depuis une image publiée."""

    update_available: bool
    """Le serveur sait-il se mettre à jour tout seul ? Faux si aucun Watchtower
    n'est configuré — l'interface masque alors le bouton plutôt que de proposer
    une action qui échouerait."""


class BackupHealth(CamelModel):
    """État des sauvegardes automatiques (`GET /api/system/backups`)."""

    enabled: bool
    """Au moins une sauvegarde active (`BACKUP_DIR` défini) : instantanés de
    la base SQLite et/ou miroir des polices."""

    last_snapshot_at: datetime | None
    """Date du plus récent instantané sur disque (survit aux redémarrages)."""

    last_snapshot_bytes: int | None

    last_error_at: datetime | None
    last_error: str | None
    """Erreur en cours la plus récente (une par boucle, effacée par la
    réussite suivante de la même boucle). Sans chemin absolu de l'hôte."""

    last_mirror_at: datetime | None
    """Dernière passe du miroir des polices depuis le démarrage du serveur."""

    mirror_copied: int | None
    mirror_repaired: int | None
    mirror_failed: int | None

    stale: bool
    """Instantanés actifs, et aucun instantané ou le plus récent a plus de 36 h."""


class UpdateResponse(CamelModel):
    """Accusé de réception d'une demande de mise à jour."""

    status: str
