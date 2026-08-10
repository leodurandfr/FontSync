"""Schémas Pydantic pour la synchronisation."""

import uuid

from pydantic import Field

from backend.schemas.base import CamelModel


class DeviceFontEntry(CamelModel):
    """Entrée d'une font côté agent : hash + nom de fichier."""

    hash: str = Field(..., min_length=64, max_length=64)
    filename: str
    local_path: str | None = None


class DeltaSyncRequest(CamelModel):
    """Requête delta sync envoyée par un agent."""

    device_id: uuid.UUID
    fonts: list[DeviceFontEntry]


class FontRef(CamelModel):
    """Référence minimale à une font pour la réponse delta."""

    id: uuid.UUID
    file_hash: str
    original_filename: str
    file_format: str
    family_name: str | None = None
    file_size: int


class DeltaSyncResponse(CamelModel):
    """Réponse du delta sync."""

    unknown_to_server: list[str]
    """Hashes de fonts que le serveur ne connaît pas (à pusher par l'agent).

    Une font **supprimée** côté serveur n'y figure jamais : le delta doit dire
    « connue, supprimée », pas « inconnue ». Sinon la machine qui détient encore
    le fichier tenterait de la pousser à chaque sync, en boucle.
    """

    missing_on_device: list[FontRef]
    """Fonts présentes sur le serveur mais absentes du device (à puller)."""

    already_synced: int
    """Nombre de fonts déjà synchronisées."""

    deleted_on_server: int = 0
    """Nombre de fonts du device connues du serveur mais supprimées.

    Compte informatif (log agent) : il inclut celles que cet appareil ne
    désinstalle pas, faute d'avoir activé la propagation.
    """

    to_uninstall: list[FontRef] = []
    """Fonts à désinstaller de cet appareil.

    Vide tant que `propagate_deletions` est désactivé sur l'appareil, et
    n'inclut jamais une quarantaine en attente de confirmation.
    """


class PushResponse(CamelModel):
    """Réponse après un push de font depuis un agent."""

    font_id: uuid.UUID
    file_hash: str
    is_duplicate: bool
    family_name: str | None = None
    refused_deleted: bool = False
    """La font est connue du serveur mais **supprimée** : le push est refusé,
    rien n'a été importé et elle n'a pas été ressuscitée. Ce n'est pas une
    erreur — l'agent ne doit pas la compter comme telle."""
