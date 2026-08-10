"""Version du serveur et mise à jour à la demande.

Un conteneur ne peut pas se remplacer lui-même sans accès au démon Docker, et
donner cet accès à FontSync reviendrait à donner l'équivalent du root sur le NAS
à une application protégée par un simple token partagé. Le privilège reste donc
chez **Watchtower** : lui seul monte le socket Docker, et FontSync se contente
de lui demander de travailler, par HTTP, sur son réseau interne.

Conséquence à assumer : la réponse au `POST /api/system/update` peut ne jamais
arriver — Watchtower recrée le conteneur qui est en train de répondre. Ce n'est
pas une erreur, c'est le succès. L'interface attend le retour de `/health`
plutôt que la réponse.
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.schemas.system import SystemInfo, UpdateResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

# Court : on ne veut pas tenir la requête ouverte pendant le pull d'image.
# Watchtower répond dès qu'il a accepté le travail.
_UPDATE_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def _update_configured() -> bool:
    return bool(settings.watchtower_url and settings.watchtower_token)


@router.get("/info", response_model=SystemInfo)
async def system_info() -> SystemInfo:
    """Version en cours d'exécution, et disponibilité de la mise à jour."""
    return SystemInfo(
        version=settings.fontsync_version or "dev",
        update_available=_update_configured(),
    )


@router.post("/update", response_model=UpdateResponse, status_code=202)
async def trigger_update() -> UpdateResponse:
    """Demande à Watchtower de tirer la dernière image et de recréer FontSync.

    Best-effort par construction : on relaie l'ordre, on ne garantit pas qu'une
    version plus récente existe. Watchtower ne recrée rien si l'image n'a pas
    bougé.
    """
    if not _update_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "La mise à jour depuis l'interface n'est pas configurée sur ce "
                "serveur (WATCHTOWER_URL / WATCHTOWER_TOKEN)."
            ),
        )

    url = f"{settings.watchtower_url.rstrip('/')}/v1/update"
    try:
        async with httpx.AsyncClient(timeout=_UPDATE_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.watchtower_token}"},
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Watchtower a refusé la demande : HTTP %d", e.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"Watchtower a répondu HTTP {e.response.status_code}.",
        )
    except httpx.HTTPError as e:
        # Le conteneur peut avoir été recréé pendant l'appel : côté serveur c'est
        # indiscernable d'une panne, mais l'interface, elle, verra /health revenir.
        logger.warning("Watchtower injoignable ou connexion coupée : %s", e)
        raise HTTPException(
            status_code=502,
            detail="Watchtower est injoignable depuis le serveur.",
        )

    logger.info("Mise à jour demandée à Watchtower.")
    return UpdateResponse(status="update_requested")
