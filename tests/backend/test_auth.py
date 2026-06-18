"""Auth par token partagé d'instance (P1 — PLAN-PUBLICATION.md).

Vérifie le contrat de `backend.auth` bout-en-bout sur l'app réelle :
- tout `/api/*` exige le token (`401` sans / avec mauvais token, `200` avec) ;
- `/health` reste public ;
- le flux **SSE** accepte l'en-tête `Authorization` **ou** un query param ;
- les **WebSocket** refusent le handshake sans token et l'acceptent via query
  param ou cookie (le navigateur ne peut pas poser d'en-tête au handshake) ;
- un token est généré + loggé quand `FONTSYNC_TOKEN` est absent.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import HTTPException, WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from backend import auth
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models.base import Base
from backend.routers import agent_events
from backend.routers import ws as ws_router
from backend.services.ws_manager import WebSocketManager

TOKEN = "test-secret-token"

# Tout `/api/*` exige le token : on couvre chaque router monté avec
# `Depends(require_token)` (fonts, devices, sync, font-families, stats).
_MISSING_UUID = "00000000-0000-0000-0000-000000000000"
REST_GET_PATHS = [
    "/api/stats",
    "/api/devices",
    "/api/fonts",
    "/api/font-families",
]
# `sync` n'expose qu'un GET paramétré : le token est vérifié **avant** la
# validation des query params, donc le rejet sans token vaut aussi pour lui.
SYNC_PULL_PATH = f"/api/sync/pull/{_MISSING_UUID}?device_id={_MISSING_UUID}"


@pytest.fixture(autouse=True)
def _set_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token d'instance connu + repli généré réinitialisé pour l'isolation."""
    monkeypatch.setattr(settings, "fontsync_token", TOKEN)
    monkeypatch.setattr(auth, "_generated_token", None)


@pytest.fixture(autouse=True)
def _fresh_ws_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un `ws_manager` neuf par test.

    Les tests SSE (boucle asyncio de pytest) et WS (TestClient, thread/loop
    dédié) ne doivent pas partager le `asyncio.Lock` du singleton, sous peine de
    « Future attached to a different loop ». Un manager neuf, utilisé par une
    seule boucle à la fois, lie son lock paresseusement à la bonne boucle.
    """
    mgr = WebSocketManager()
    monkeypatch.setattr(agent_events, "ws_manager", mgr)
    monkeypatch.setattr(ws_router, "ws_manager", mgr)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP ASGI avec une base SQLite in-memory injectée via override."""
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

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- REST : header Authorization ----


@pytest.mark.asyncio
async def test_health_is_public(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [*REST_GET_PATHS, SYNC_PULL_PATH])
async def test_rest_rejects_without_token(client: AsyncClient, path: str) -> None:
    resp = await client.get(path)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_rest_rejects_wrong_token(client: AsyncClient) -> None:
    resp = await client.get("/api/stats", headers=_bearer("nope"))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rest_rejects_non_bearer_scheme(client: AsyncClient) -> None:
    resp = await client.get("/api/stats", headers={"Authorization": f"Basic {TOKEN}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", REST_GET_PATHS)
async def test_rest_accepts_valid_token(client: AsyncClient, path: str) -> None:
    resp = await client.get(path, headers=_bearer())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sync_accepts_valid_token(client: AsyncClient) -> None:
    # Token accepté → on atteint le handler, qui renvoie 404 (device/font
    # absents de la base de test). L'essentiel : surtout pas 401.
    resp = await client.get(SYNC_PULL_PATH, headers=_bearer())
    assert resp.status_code != 401
    assert resp.status_code == 404


# ---- SSE : header OU query param ----
#
# Le rejet (token absent/invalide) se vérifie de bout en bout : la dependency
# lève **avant** d'ouvrir le flux. Le chemin « accepté », lui, ouvrirait un flux
# SSE infini que `httpx.ASGITransport` bufferise sans jamais rendre la main — on
# vérifie donc la dependency `require_token_stream` directement (c'est l'unité
# d'auth ; l'endpoint ne fait que la déclarer).


@pytest.mark.asyncio
async def test_sse_rejects_without_token(client: AsyncClient) -> None:
    resp = await client.get("/api/agent/dev-x/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sse_rejects_wrong_query_token(client: AsyncClient) -> None:
    resp = await client.get("/api/agent/dev-x/events", params={"token": "nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_require_token_stream_accepts_header() -> None:
    # Aucune exception levée = accepté.
    await auth.require_token_stream(authorization=f"Bearer {TOKEN}", token=None)


@pytest.mark.asyncio
async def test_require_token_stream_accepts_query_param() -> None:
    await auth.require_token_stream(authorization=None, token=TOKEN)


@pytest.mark.asyncio
async def test_require_token_stream_rejects_missing() -> None:
    with pytest.raises(HTTPException) as exc:
        await auth.require_token_stream(authorization=None, token=None)
    assert exc.value.status_code == 401


# ---- WebSocket : query param ou cookie ----


def test_ws_client_rejected_without_token() -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/client"):
            pass


def test_ws_client_rejected_with_wrong_token() -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/client?token=nope"):
            pass


def test_ws_client_accepts_query_param() -> None:
    client = TestClient(app)
    with client.websocket_connect(f"/ws/client?token={TOKEN}") as ws:
        ws.close()


def test_ws_client_accepts_cookie() -> None:
    client = TestClient(app)
    client.cookies.set("fontsync_token", TOKEN)
    with client.websocket_connect("/ws/client") as ws:
        ws.close()


def test_ws_agent_rejected_without_token() -> None:
    # `/ws/agent` (legacy) applique la même barrière de token que `/ws/client`.
    # Le chemin « accepté » est couvert par les tests `/ws/client` (même
    # `verify_websocket_token`) : ici on ne fait pas le handshake complet, dont
    # le `disconnect` toucherait la vraie DB en parsant un device_id non-UUID.
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/agent/dev-1"):
            pass


# ---- Token généré quand FONTSYNC_TOKEN est absent ----


def test_generates_and_logs_token_when_unset(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "fontsync_token", "")
    monkeypatch.setattr(auth, "_generated_token", None)

    with caplog.at_level(logging.WARNING, logger="backend.auth"):
        first = auth.get_server_token()
        second = auth.get_server_token()

    assert first  # non vide
    assert first == second  # stable sur la durée de vie du process
    assert any("FONTSYNC_TOKEN" in r.getMessage() for r in caplog.records)
