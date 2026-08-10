"""Schémas Pydantic pour l'état et la mise à jour du serveur."""

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


class UpdateResponse(CamelModel):
    """Accusé de réception d'une demande de mise à jour."""

    status: str
