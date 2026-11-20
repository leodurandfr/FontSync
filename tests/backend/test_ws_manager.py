"""Diffusion WebSocket non bloquante (P1-7a, M-10, B-45).

`broadcast_to_clients` envoyait à chaque client, à la suite, sous un verrou
global et sans délai : un seul onglet qui ne lit plus (veille, réseau coupé
sans RST) bloquait toutes les diffusions suivantes — et donc chaque requête qui
diffuse (upload, push d'un agent). Il itérait en outre la liste vivante : un
client retiré pendant la boucle en faisait sauter un autre (B-45).

Désormais : une file bornée et une tâche d'envoi par client ; la diffusion ne
fait que déposer dans les files ; un client dont la file déborde ou dont un
envoi dépasse le délai est évincé (close 1013) et retiré.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

import pytest

from backend.services.ws_manager import WebSocketManager

MSG = {"type": "font.added", "data": {"id": "x"}}


class FakeWS:
    """WebSocket factice : `mute` n'achève jamais un envoi (client qui ne lit plus)."""

    def __init__(self, name: str, *, mute: bool = False) -> None:
        self.name = name
        self.mute = mute
        self.sent: list[dict[str, Any]] = []
        self.closed: int | None = None
        self.accepted = False
        self.on_send: Any = None

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.on_send is not None:
            self.on_send(self)
        if self.mute:
            await asyncio.Event().wait()
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = code


def manager(
    *, send_timeout: float = 0.2, queue_size: int = 256, queue_wait: float = 0.3
) -> WebSocketManager:
    mgr = WebSocketManager()
    # Délais injectables (attributs) : sur l'ancien code ils n'ont pas d'effet,
    # et les tests y échouent par blocage réel.
    mgr.send_timeout = send_timeout
    mgr.queue_size = queue_size
    mgr.queue_wait = queue_wait
    return mgr


async def settle(predicate: Any, timeout: float = 1.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


async def close_all(mgr: WebSocketManager, *clients: FakeWS) -> None:
    for ws in clients:
        mgr.disconnect(ws)  # type: ignore[arg-type]
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_broadcast_not_blocked_by_mute_client() -> None:
    mgr = manager()
    mute, healthy = FakeWS("mute", mute=True), FakeWS("healthy")
    await mgr.connect_client(mute)  # type: ignore[arg-type]
    await mgr.connect_client(healthy)  # type: ignore[arg-type]
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        await asyncio.wait_for(mgr.broadcast_to_clients(MSG), 0.5)
        await asyncio.wait_for(mgr.broadcast_to_clients(MSG), 0.5)
        assert loop.time() - start < 0.5
        assert await settle(lambda: len(healthy.sent) == 2)
        # Évincé après le délai d'envoi (0,2 s), en 1013 « try again later ».
        assert await settle(lambda: mute.closed == 1013)
        assert mgr.client_count == 1
    finally:
        await close_all(mgr, mute, healthy)


@pytest.mark.asyncio
async def test_disconnect_during_broadcast_does_not_skip() -> None:
    """B-45 : un client retiré pendant la diffusion n'en fait pas sauter un autre."""
    mgr = manager()
    a, b, c = FakeWS("a"), FakeWS("b"), FakeWS("c")
    for ws in (a, b, c):
        await mgr.connect_client(ws)  # type: ignore[arg-type]
    a.on_send = lambda ws: mgr.disconnect(ws)  # le handler de « a » se termine
    try:
        await asyncio.wait_for(mgr.broadcast_to_clients(MSG), 0.5)
        assert await settle(lambda: b.sent == [MSG] and c.sent == [MSG])
    finally:
        await close_all(mgr, a, b, c)


@pytest.mark.asyncio
async def test_full_queue_evicts_the_client_within_the_timeout() -> None:
    mgr = manager(send_timeout=30, queue_size=2, queue_wait=0.2)
    mute, healthy = FakeWS("mute", mute=True), FakeWS("healthy")
    await mgr.connect_client(mute)  # type: ignore[arg-type]
    await mgr.connect_client(healthy)  # type: ignore[arg-type]
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        for _ in range(5):
            await asyncio.wait_for(mgr.broadcast_to_clients(MSG), 1.0)
        # Au pire une attente bornée (queue_wait), pas une par diffusion, même
        # si l'envoi bloqué du client muet n'a pas encore expiré (30 s).
        assert loop.time() - start < 0.45
        assert await settle(lambda: mute.closed == 1013)
        assert await settle(lambda: len(healthy.sent) == 5)
        assert mgr.client_count == 1
    finally:
        await close_all(mgr, mute, healthy)


@pytest.mark.asyncio
async def test_burst_larger_than_the_queue_keeps_a_healthy_client() -> None:
    """Rafale (upload multiple, quarantaine de centaines de polices) sans rendre
    la main : un onglet sain n'est jamais évincé, rien n'est perdu."""
    mgr = manager(send_timeout=1.0, queue_size=4)
    healthy = FakeWS("healthy")
    await mgr.connect_client(healthy)  # type: ignore[arg-type]
    try:
        for i in range(50):
            await mgr.broadcast_to_clients({"type": "n", "data": i})
        assert await settle(lambda: len(healthy.sent) == 50)
        assert [m["data"] for m in healthy.sent] == list(range(50))
        assert healthy.closed is None
        assert mgr.client_count == 1
    finally:
        await close_all(mgr, healthy)


@pytest.mark.asyncio
async def test_messages_keep_their_order_per_client() -> None:
    mgr = manager()
    ws = FakeWS("ws")
    await mgr.connect_client(ws)  # type: ignore[arg-type]
    try:
        for i in range(50):
            await mgr.broadcast_to_clients({"type": "n", "data": i})
        assert await settle(lambda: len(ws.sent) == 50)
        assert [m["data"] for m in ws.sent] == list(range(50))
    finally:
        await close_all(mgr, ws)


@pytest.mark.asyncio
async def test_disconnect_cancels_the_sender_task() -> None:
    """Pas de fuite de tâche : la tâche d'envoi meurt avec le client."""
    mgr = manager(send_timeout=30)
    mute = FakeWS("mute", mute=True)
    before = {t for t in asyncio.all_tasks() if not t.done()}
    await mgr.connect_client(mute)  # type: ignore[arg-type]
    await asyncio.wait_for(mgr.broadcast_to_clients(MSG), 0.5)
    await asyncio.sleep(0.05)
    mgr.disconnect(mute)  # type: ignore[arg-type]
    assert await settle(
        lambda: (
            {t for t in asyncio.all_tasks() if not t.done()}
            <= before | {asyncio.current_task()}
        )
    )
    assert mgr.client_count == 0


@pytest.mark.asyncio
async def test_initial_messages_go_first_through_the_queue() -> None:
    """La présence initiale passe par la file : jamais d'envoi direct concurrent."""
    mgr = manager()
    ws = FakeWS("ws")
    initial = [{"type": "device.connected", "data": {"deviceId": "d1"}}]
    await mgr.connect_client(ws, initial=initial)  # type: ignore[arg-type]
    await mgr.broadcast_to_clients(MSG)
    try:
        assert await settle(lambda: len(ws.sent) == 2)
        assert ws.sent == [*initial, MSG]
    finally:
        await close_all(mgr, ws)


@pytest.mark.asyncio
async def test_failing_client_is_dropped_without_affecting_others() -> None:
    class Broken(FakeWS):
        async def send_json(self, message: dict[str, Any]) -> None:
            raise RuntimeError("socket closed")

    mgr = manager()
    broken, healthy = Broken("broken"), FakeWS("healthy")
    await mgr.connect_client(broken)  # type: ignore[arg-type]
    await mgr.connect_client(healthy)  # type: ignore[arg-type]
    try:
        await mgr.broadcast_to_clients(MSG)
        await mgr.broadcast_to_clients(MSG)
        assert await settle(lambda: len(healthy.sent) == 2)
        assert await settle(lambda: mgr.client_count == 1)
    finally:
        await close_all(mgr, broken, healthy)


class GatedWS(FakeWS):
    """Client dont chaque envoi attend que le test ouvre le portillon."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.gate = asyncio.Event()

    async def send_json(self, message: dict[str, Any]) -> None:
        await self.gate.wait()
        self.gate.clear()
        self.sent.append(message)


@pytest.mark.asyncio
async def test_a_later_broadcast_never_overtakes_an_earlier_one() -> None:
    """File pleine : A attend une place. La tâche d'envoi en libère une (et
    réveille A) ; avant que A ne reprenne, B — plus récent — arrive. Sans
    garde, B prend la place en put_nowait et passe devant A : font.deleted
    puis font.added, la police supprimée reste affichée."""
    mgr = manager(queue_size=2, queue_wait=2.0, send_timeout=5.0)
    ws = GatedWS("gated")
    await mgr.connect_client(ws)  # type: ignore[arg-type]
    try:
        for i in range(3):  # fill0 en cours d'envoi, fill1 et fill2 en file
            await mgr.broadcast_to_clients({"type": "fill", "data": i})
            await asyncio.sleep(0)
        a = asyncio.create_task(mgr.broadcast_to_clients({"type": "font.added"}))
        await asyncio.sleep(0)  # A attend une place
        ws.gate.set()  # fill0 part ; la tâche d'envoi va prendre fill1 (place libre)
        await asyncio.sleep(0)  # la tâche d'envoi tourne et réveille A…

        async def pump() -> None:  # ouvre le portillon pour la suite des envois
            for _ in range(100):
                ws.gate.set()
                await asyncio.sleep(0.01)

        # Créée maintenant, la pompe ne tourne qu'après la décision synchrone
        # de B (dépôt immédiat ou attente) : la course reste intacte.
        pumping = asyncio.create_task(pump())
        await asyncio.wait_for(
            mgr.broadcast_to_clients({"type": "font.deleted"}), 3
        )  # …B arrive avant que A ne reprenne
        await asyncio.wait_for(a, 3)
        assert await settle(lambda: len(ws.sent) == 5, timeout=3)
        assert [m["type"] for m in ws.sent][-2:] == ["font.added", "font.deleted"]
        assert ws.closed is None
        pumping.cancel()
    finally:
        await close_all(mgr, ws)


@pytest.mark.asyncio
async def test_send_error_closes_the_socket() -> None:
    """Message refusé par le socket : le client est fermé (1013), pas seulement
    oublié — sinon l'onglet se croirait connecté sans plus rien recevoir."""

    class Refusing(FakeWS):
        async def send_json(self, message: dict[str, Any]) -> None:
            raise TypeError("not JSON serializable")

    mgr = manager()
    ws = Refusing("refusing")
    await mgr.connect_client(ws)  # type: ignore[arg-type]
    await mgr.broadcast_to_clients(MSG)
    assert await settle(lambda: ws.closed == 1013)
    assert mgr.client_count == 0


@pytest.mark.asyncio
async def test_concurrent_requests_keep_emission_order_on_a_full_queue() -> None:
    """8 requêtes concurrentes × 50 diffusions, file d'une place : le client
    reçoit dans l'ordre d'émission (le verrou par client sérialise les attentes
    en FIFO ; sans lui, une attente réveillée plus tard double une autre)."""

    class Yielding(FakeWS):
        async def send_json(self, message: dict[str, Any]) -> None:
            await asyncio.sleep(0)
            self.sent.append(message)

    mgr = manager(queue_size=1, queue_wait=5.0, send_timeout=5.0)
    ws = Yielding("yielding")
    await mgr.connect_client(ws)  # type: ignore[arg-type]
    counter = itertools.count()

    async def request() -> None:
        for _ in range(50):
            await asyncio.sleep(0)
            await mgr.broadcast_to_clients({"n": next(counter)})

    try:
        await asyncio.wait_for(asyncio.gather(*(request() for _ in range(8))), 10)
        assert await settle(lambda: len(ws.sent) == 400, timeout=5)
        received = [m["n"] for m in ws.sent]
        assert received == sorted(received)
        assert ws.closed is None
    finally:
        await close_all(mgr, ws)
