"""Capacités annoncées par les agents (B-32, M-32).

L'agent liste au register ce qu'il sait faire (`agent/capabilities.py`). Le
serveur s'y fie plutôt qu'à `agent_version` : un appareil sans une capacité ne
reçoit pas l'ordre correspondant, et rien n'est déduit de ce qu'il ne garantit
pas.
"""

from __future__ import annotations

from fastapi import HTTPException

from backend.models.device import Device

# Chaque delta liste toutes les polices trouvées sur le disque : une empreinte
# absente veut dire un fichier absent. Sans elle, aucune suppression déduite.
FULL_DECLARATION = "full-declaration"
# L'agent applique `toDeactivate` (déplace les fichiers vers le dossier désactivé
# et retour).
DEACTIVATE = "deactivate"
# L'agent applique `toUninstall` quand la propagation des suppressions est active.
UNINSTALL = "uninstall"

AGENT_TOO_OLD = (
    "L'agent FontSync de cet appareil est trop ancien pour cette action. "
    "Mettez à jour l'app FontSync sur ce Mac."
)


def supports(device: Device, capability: str) -> bool:
    """Vrai si le dernier register de l'appareil annonçait cette capacité."""
    return capability in (device.capabilities or [])


def require_capability(device: Device, capability: str) -> None:
    """Refuse (409) une action que l'agent de l'appareil n'appliquerait pas."""
    if not supports(device, capability):
        raise HTTPException(status_code=409, detail=AGENT_TOO_OLD)
