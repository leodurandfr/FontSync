"""Canal SSE serveur → agent (process `listen`).

L'agent ouvre une connexion SSE longue durée ; le serveur y pousse un simple
signal « sync » (sans payload exploité) chaque fois qu'une font devient
disponible pour ce device. Le process `listen` se contente de relancer la
commande `sync` à chaque signal — la sémantique de delta vit côté serveur.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.auth import Principal, can_access_device, db_session_for, require_auth
from backend.models.device import Device
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Intervalle d'envoi d'un commentaire keep-alive pour maintenir la connexion
# ouverte au travers des proxies (en secondes).
_KEEPALIVE_INTERVAL = 25.0


async def _check_listener(
    request: Request, principal: Principal, device_id: str
) -> None:
    if principal.is_admin:
        return
    try:
        wanted = uuid.UUID(device_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Device non trouvé.") from None
    async with db_session_for(request.app) as db:
        device = await db.get(Device, wanted)
    if device is None or not can_access_device(principal, device):
        raise HTTPException(
            status_code=403, detail="Cet appareil ne vous appartient pas."
        )


@router.get("/{device_id}/events")
async def agent_events(
    device_id: str,
    request: Request,
    principal: Principal = Depends(require_auth),
) -> StreamingResponse:
    """Flux SSE des signaux « re-sync » pour un device.

    Un jeton d'appareil n'écoute que le sien, un membre que les siens. La base
    est lue puis relâchée avant le flux : une session tenue pendant des heures
    par écouteur épuiserait le pool.
    """
    await _check_listener(request, principal, device_id)

    async def event_stream() -> AsyncIterator[str]:
        # Présence « en ligne » : le `listen` (SSE) a remplacé la connexion
        # WebSocket de l'agent. On notifie les clients frontend à la première
        # connexion SSE d'un device et à la déconnexion de la dernière.
        was_online = device_id in ws_manager.connected_sse_devices
        queue = ws_manager.subscribe_agent_events(device_id)
        # `try` dès l'abonnement (M-11) : un flux annulé pendant la diffusion
        # initiale (client qui coupe, arrêt du serveur) se désabonne quand même,
        # sinon le device resterait « en ligne » à vie.
        try:
            if not was_online:
                await ws_manager.broadcast_to_clients(
                    {"type": "device.connected", "data": {"deviceId": device_id}}
                )
            # Signal initial : déclenche un premier sync au démarrage du `listen`.
            yield "event: sync\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    # On coalesce les signaux en attente en un seul sync.
                    while not queue.empty():
                        queue.get_nowait()
                    yield "event: sync\ndata: {}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive : commentaire SSE ignoré par le client.
                    yield ": keep-alive\n\n"
        finally:
            ws_manager.unsubscribe_agent_events(device_id, queue)
            if device_id not in ws_manager.connected_sse_devices:
                await ws_manager.broadcast_to_clients(
                    {"type": "device.disconnected", "data": {"deviceId": device_id}}
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
