"""Activité de sync d'un appareil : `last_seen_at` et l'état « en retard ».

`last_seen_at` est la date du dernier passage de sync de l'agent : delta, push,
pull. Ni le `register` d'un appareil existant (il précède le delta, qui peut
échouer à chaque fois), ni un réglage changé depuis l'interface (activité de
l'utilisateur, pas de l'agent) ne le font avancer.

Être connecté ne dit pas qu'un appareil se synchronise : le process `listen`
survit à un job `sync` qui ne démarre plus (cas du Mac mini, M-39). D'où
`sync_overdue`.
"""

from datetime import datetime, timedelta, timezone

from backend.config import settings
from backend.models.device import Device

# Un pull n'écrit rien d'autre : au plus une écriture par minute et par
# appareil, au lieu d'une par police téléchargée.
PULL_ACTIVITY_INTERVAL = timedelta(seconds=60)


def as_utc(value: datetime) -> datetime:
    """SQLite rend des datetimes naïfs ; tout ce qu'on écrit est en UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def sync_overdue(last_seen_at: datetime | None, now: datetime | None = None) -> bool:
    """Aucun passage de sync depuis plus de `device_overdue_minutes`, ou jamais."""
    if last_seen_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    threshold = timedelta(minutes=settings.device_overdue_minutes)
    return now - as_utc(last_seen_at) > threshold


def note_sync_activity(
    device: Device, *, min_interval: timedelta | None = None
) -> bool:
    """Avance `last_seen_at` (sans commit). Avec `min_interval`, seulement s'il
    est plus ancien que cela. Renvoie `True` si la valeur a changé."""
    now = datetime.now(timezone.utc)
    if (
        min_interval is not None
        and device.last_seen_at is not None
        and now - as_utc(device.last_seen_at) < min_interval
    ):
        return False
    device.last_seen_at = now
    return True
