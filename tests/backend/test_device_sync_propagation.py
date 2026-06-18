"""Propagation réactive serveur→agent et canal commande UI→agent (P0.2, B1/B2).

Régressions confirmées pendant la validation E2E (`tests/e2e/CHECKLIST.md`) :

- **B2 (majeur)** : `/api/fonts/upload` ne déclenchait aucune propagation réactive
  (il poussait sur le canal WebSocket *legacy* mort au lieu d'émettre le signal
  SSE « re-sync »). On vérifie qu'un upload signale désormais les process `listen`.
- **B1 (bloquant)** : install/uninstall/activate/deactivate par appareil passaient
  par `send_to_agent` (WS legacy) → `503`. Stop-gap : « install » déclenche un
  re-sync de l'appareil (signal SSE, sémantique miroir), et les actions par-device
  non encore supportées répondent `501` (et non un `503` trompeur).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend import auth
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models.base import Base
from backend.routers import fonts as fonts_router
from backend.services.storage import FilesystemStorage
from backend.services.ws_manager import WebSocketManager

TOKEN = "test-secret-token"
_AUTH = {"Authorization": f"Bearer {TOKEN}"}
_MISSING_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fontsync_token", TOKEN)
    monkeypatch.setattr(auth, "_generated_token", None)


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> WebSocketManager:
    """`ws_manager` neuf et isolé, injecté dans le router fonts."""
    mgr = WebSocketManager()
    monkeypatch.setattr(fonts_router, "ws_manager", mgr)
    return mgr


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """Client ASGI : DB SQLite in-memory + stockage filesystem isolé."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    storage = FilesystemStorage(base_path=str(tmp_path / "storage"))
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[fonts_router.get_storage] = lambda: storage

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def _register_device(client: AsyncClient, hostname: str = "mac-test") -> str:
    resp = await client.post(
        "/api/devices/register",
        headers=_AUTH,
        json={"name": "Mac de test", "hostname": hostname, "os": "macos"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload_font(client: AsyncClient, font_bytes: bytes, name: str) -> str:
    resp = await client.post(
        "/api/fonts/upload",
        headers=_AUTH,
        files=[("files", (name, font_bytes, "font/ttf"))],
    )
    assert resp.status_code == 200, resp.text
    imported = resp.json()["imported"]
    assert len(imported) == 1, resp.text
    return imported[0]["id"]


# ---------- B2 : upload → signal SSE « re-sync » ----------


@pytest.mark.asyncio
async def test_upload_signals_resync_to_listeners(
    client: AsyncClient, manager: WebSocketManager, font_factory
) -> None:
    # Un agent `listen` abonné en SSE.
    queue = manager.subscribe_agent_events("dev-A")

    await _upload_font(client, font_factory(family="E2E Prop"), "E2EProp-Regular.ttf")

    # B2 : l'upload doit pousser un signal « re-sync » (avant le fix : rien).
    assert queue.get_nowait() == "sync"


@pytest.mark.asyncio
async def test_upload_without_listeners_does_not_error(
    client: AsyncClient, manager: WebSocketManager, font_factory
) -> None:
    # Aucun abonné SSE : l'upload réussit quand même (broadcast best-effort).
    font_id = await _upload_font(
        client, font_factory(family="E2E Solo"), "E2ESolo-Regular.ttf"
    )
    assert font_id


# ---------- B1 : install = re-sync ; reste = 501 ----------


@pytest.mark.asyncio
async def test_install_triggers_device_resync(
    client: AsyncClient, manager: WebSocketManager, font_factory
) -> None:
    device_id = await _register_device(client)
    font_id = await _upload_font(
        client, font_factory(family="E2E Inst"), "E2EInst-Regular.ttf"
    )

    # S'abonner APRÈS l'upload pour ne capter que le signal de l'install.
    queue = manager.subscribe_agent_events(device_id)

    resp = await client.post(f"/api/fonts/{font_id}/install/{device_id}", headers=_AUTH)

    # Avant le fix : 503 (« agent non connecté »). Désormais : 202 + re-sync.
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"status": "resync_requested"}
    assert queue.get_nowait() == "sync"


@pytest.mark.asyncio
async def test_install_unknown_font_is_404(
    client: AsyncClient, manager: WebSocketManager
) -> None:
    device_id = await _register_device(client)
    resp = await client.post(
        f"/api/fonts/{_MISSING_UUID}/install/{device_id}", headers=_AUTH
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_install_unknown_device_is_404(
    client: AsyncClient, manager: WebSocketManager, font_factory
) -> None:
    font_id = await _upload_font(
        client, font_factory(family="E2E NoDev"), "E2ENoDev-Regular.ttf"
    )
    resp = await client.post(
        f"/api/fonts/{font_id}/install/{_MISSING_UUID}", headers=_AUTH
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["uninstall", "activate", "deactivate"])
async def test_per_device_actions_return_501_not_503(
    client: AsyncClient, action: str
) -> None:
    # Actions par-device reportées (manifeste désiré) : 501 honnête, pas 503.
    resp = await client.post(
        f"/api/fonts/{_MISSING_UUID}/{action}/{_MISSING_UUID}", headers=_AUTH
    )
    assert resp.status_code == 501
    assert resp.status_code != 503
