"""Présence « en ligne » via le canal SSE `listen` de l'agent.

Depuis la migration de l'agent WebSocket → SSE (Phase B), la présence d'un
device pour le frontend ne vient plus d'une connexion WS mais de l'ouverture
d'un flux SSE `GET /api/agent/{device_id}/events`. On vérifie que le serveur
diffuse bien `device.connected` à la première connexion SSE et
`device.disconnected` à la déconnexion de la dernière.
"""

import pytest

from backend.auth import LEGACY_PRINCIPAL
from backend.routers import agent_events
from backend.services.ws_manager import WebSocketManager


class _FakeRequest:
    """Request minimale : le générateur n'interroge `is_disconnected`
    qu'après le premier `yield`, jamais atteint dans ces tests."""

    async def is_disconnected(self) -> bool:
        return False


@pytest.fixture
def manager(monkeypatch) -> WebSocketManager:
    """Un `ws_manager` neuf et isolé qui capture les broadcasts clients."""
    mgr = WebSocketManager()
    sent: list[dict] = []

    async def _capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr(mgr, "broadcast_to_clients", _capture)
    monkeypatch.setattr(agent_events, "ws_manager", mgr)
    mgr.sent = sent  # type: ignore[attr-defined]
    return mgr


async def _open_stream(device_id: str):
    """Ouvre le flux et consomme le 1er event (subscribe + présence)."""
    response = await agent_events.agent_events(
        device_id, _FakeRequest(), LEGACY_PRINCIPAL
    )
    gen = response.body_iterator
    first = await gen.__anext__()
    return gen, first


@pytest.mark.asyncio
async def test_connect_broadcasts_device_connected(manager: WebSocketManager) -> None:
    gen, first = await _open_stream("dev-1")

    assert first == "event: sync\ndata: {}\n\n"
    assert manager.sent == [{"type": "device.connected", "data": {"deviceId": "dev-1"}}]
    assert "dev-1" in manager.connected_sse_devices

    await gen.aclose()


@pytest.mark.asyncio
async def test_disconnect_broadcasts_device_disconnected(
    manager: WebSocketManager,
) -> None:
    gen, _ = await _open_stream("dev-1")
    manager.sent.clear()

    await gen.aclose()  # déclenche le `finally` → désinscription

    assert manager.sent == [
        {"type": "device.disconnected", "data": {"deviceId": "dev-1"}}
    ]
    assert "dev-1" not in manager.connected_sse_devices


@pytest.mark.asyncio
async def test_second_listen_does_not_rebroadcast_connected(
    manager: WebSocketManager,
) -> None:
    """Deux `listen` pour le même device : un seul `device.connected`."""
    gen1, _ = await _open_stream("dev-1")
    manager.sent.clear()

    gen2, _ = await _open_stream("dev-1")
    assert manager.sent == []  # déjà en ligne → pas de re-broadcast

    # La fermeture du premier flux ne fait pas passer le device hors ligne :
    # le second `listen` est toujours abonné.
    await gen1.aclose()
    assert manager.sent == []
    assert "dev-1" in manager.connected_sse_devices

    # La fermeture du dernier flux → device.disconnected.
    await gen2.aclose()
    assert manager.sent == [
        {"type": "device.disconnected", "data": {"deviceId": "dev-1"}}
    ]
    assert "dev-1" not in manager.connected_sse_devices


@pytest.mark.asyncio
async def test_cancel_during_initial_broadcast_unsubscribes(monkeypatch) -> None:
    """M-11 : le flux annulé PENDANT la diffusion initiale (client qui coupe,
    arrêt du serveur) se désabonne quand même — sinon le device reste « en
    ligne » à vie (présence fantôme, signaux sync accumulés)."""
    import asyncio

    mgr = WebSocketManager()
    entered = asyncio.Event()
    sent: list[dict] = []

    async def _slow_broadcast(message: dict) -> None:
        sent.append(message)
        if message["type"] == "device.connected":
            entered.set()
            await asyncio.Event().wait()  # diffusion qui ne rend jamais la main

    monkeypatch.setattr(mgr, "broadcast_to_clients", _slow_broadcast)
    monkeypatch.setattr(agent_events, "ws_manager", mgr)

    response = await agent_events.agent_events(
        "dev-1", _FakeRequest(), LEGACY_PRINCIPAL
    )
    gen = response.body_iterator
    first = asyncio.ensure_future(gen.__anext__())
    await asyncio.wait_for(entered.wait(), 2)
    assert "dev-1" in mgr.connected_sse_devices

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert "dev-1" not in mgr.connected_sse_devices
    assert mgr._sse_subscribers == {}
    # Un onglet a pu recevoir device.connected avant le blocage : il apprend aussi
    # la déconnexion.
    assert sent[-1] == {"type": "device.disconnected", "data": {"deviceId": "dev-1"}}
