"""Auth par token partagé d'instance (P1 — PLAN-PUBLICATION.md).

Vérifie le contrat de `backend.auth` bout-en-bout sur l'app réelle :
- tout `/api/*` exige le token (`401` sans / avec mauvais token, `200` avec),
  vérifié route par route par énumération de l'app (M-49) ; REST n'accepte
  que l'en-tête `Authorization` ;
- `/health` reste public, et aucune autre route publique n'apparaît en douce ;
- le flux **SSE** accepte l'en-tête `Authorization` **ou** un query param ;
- les **WebSocket** refusent le handshake sans token et l'acceptent via query
  param, en-tête ou cookie (le navigateur ne peut pas poser d'en-tête au
  handshake) ;
- les quasi-égalités (préfixe, suffixe, casse, substitution) sont refusées ;
- un token est généré + loggé quand `FONTSYNC_TOKEN` est absent ou blanc.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from fastapi import HTTPException, WebSocketDisconnect
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.routing import Mount, Route, WebSocketRoute
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

# Échantillon de GET qui répondent 200 avec le bon token. La couverture du
# rejet, elle, s'obtient par énumération de `app.routes` (plus bas, M-49) :
# un nouveau router oublié ici est couvert d'office.
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
    # Sous délai : un flux ouvert par erreur doit faire échouer le test, pas
    # bloquer la suite.
    resp = await asyncio.wait_for(client.get("/api/agent/dev-x/events"), 5)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sse_rejects_wrong_query_token(client: AsyncClient) -> None:
    resp = await asyncio.wait_for(
        client.get("/api/agent/dev-x/events", params={"token": "nope"}), 5
    )
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


# ---- Énumération structurelle et quasi-égalités (M-49) ----
#
# Chaque route `/api/*` de l'app réelle, telle que montée : un router ajouté
# sans `Depends(require_token)` (ou un `include_router` qui la perd) fait
# échouer la suite, sans qu'il faille penser à l'ajouter à une liste.

# REST : en-tête seulement (`require_token`) ; le query param `?token=` n'est
# admis que sur le flux SSE (`EventSource` ne pose pas d'en-tête).
_SSE_PATH = "/api/agent/{device_id}/events"
# Hors `/api` : la santé et, si le frontend est buildé, le repli SPA.
_PUBLIC_ROUTES = {"/health", "/{full_path:path}"}
# Routes Starlette (pas FastAPI) admises : la doc OpenAPI, publique jusqu'à
# P1-5, et les assets du frontend buildé. Toute autre (`add_route`, `mount`,
# `WebSocketRoute` brute) échappe à l'énumération ci-dessous : refusée.
_STARLETTE_PUBLIC = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/assets",
}
_WEBSOCKET_ROUTES = {"/ws/client"}
# Relevé à l'import, avant que la fixture `client` ne vide les surcharges : un
# `app.dependency_overrides[require_token] = …` dans l'app ouvrirait tout.
_OVERRIDES_AT_IMPORT = dict(app.dependency_overrides)


def _routes(kind: type) -> list:
    """Routes effectives de l'app, routers inclus aplatis.

    Depuis FastAPI 0.16x, `app.routes` garde chaque `include_router` en un
    seul nœud ; `iter_route_contexts` rend les routes telles que servies,
    dépendances du router comprises."""
    return [
        c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, kind)
    ]


def _api_routes() -> list:
    return [r for r in _routes(APIRoute) if r.path.startswith("/api/")]


def _dependency_calls(dependant: Dependant) -> set[Callable[..., Any]]:
    calls: set[Callable[..., Any]] = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            calls.add(sub.call)
        calls |= _dependency_calls(sub)
    return calls


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", _MISSING_UUID, path)


_API_CALLS = sorted(
    (method, route.path) for route in _api_routes() for method in route.methods
)


def test_route_enumeration_sees_every_router() -> None:
    prefixes = {path.split("/")[2] for _method, path in _API_CALLS}
    assert prefixes >= {
        "agent",
        "devices",
        "font-families",
        "fonts",
        "stats",
        "sync",
        "system",
    }
    assert ("POST", "/api/system/update") in _API_CALLS


@pytest.mark.parametrize(("method", "path"), _API_CALLS)
def test_every_api_route_declares_the_token_dependency(method: str, path: str) -> None:
    route = next(r for r in _api_routes() if r.path == path and method in r.methods)
    expected = auth.require_token_stream if path == _SSE_PATH else auth.require_token
    assert expected in _dependency_calls(route.dependant), (
        f"{method} {path} n'exige pas {expected.__name__}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _API_CALLS)
async def test_every_api_route_rejects_a_missing_token(
    client: AsyncClient, method: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Une régression ne doit rien déclencher pour de vrai (POST /api/system/update
    # appellerait Watchtower si l'environnement du test le configure).
    monkeypatch.setattr(settings, "watchtower_url", "")
    monkeypatch.setattr(settings, "watchtower_token", "")
    # Délai : une route SSE sans auth ouvrirait un flux infini.
    resp = await asyncio.wait_for(client.request(method, _concrete(path)), 5)
    assert resp.status_code == 401, f"{method} {path} → {resp.status_code}"


def test_no_unexpected_public_route() -> None:
    sockets = set()
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if isinstance(route, APIRoute):
            if not route.path.startswith("/api/"):
                assert route.path in _PUBLIC_ROUTES, f"route publique : {route.path}"
        elif isinstance(route, WebSocketRoute):  # APIWebSocketRoute comprise
            sockets.add(route.path)
        elif isinstance(route, (Route, Mount)):
            assert route.path in _STARLETTE_PUBLIC, f"route hors FastAPI : {route.path}"
        else:
            pytest.fail(f"type de route inattendu : {route!r}")
    assert sockets == _WEBSOCKET_ROUTES, sockets


def test_no_low_priority_route() -> None:
    """`app.frontend(…)` (FastAPI 0.16x) range ses routes à part, hors de
    `iter_route_contexts` : il n'y en a pas, il ne doit pas y en avoir."""
    routers = [app.router] + [
        r.original_router for r in app.routes if hasattr(r, "original_router")
    ]
    for router in routers:
        assert not getattr(router, "_low_priority_routes", []), router


def test_auth_dependencies_are_never_overridden() -> None:
    assert not set(_OVERRIDES_AT_IMPORT) & {
        auth.require_token,
        auth.require_token_stream,
    }


# Préfixe, suffixe, casse, troncature, substitution à longueur égale : une
# comparaison relâchée (préfixe, `in`, insensible à la casse, partielle) en
# accepterait au moins un.
_NEAR_MISSES = [TOKEN[:-1], TOKEN + "x", TOKEN.upper(), TOKEN[1:], TOKEN[:-1] + "X"]


@pytest.mark.parametrize("candidate", [*_NEAR_MISSES, " " + TOKEN, ""])
def test_token_is_valid_rejects_near_misses(candidate: str) -> None:
    assert auth.token_is_valid(TOKEN)
    assert not auth.token_is_valid(candidate)


@pytest.mark.asyncio
async def test_rest_ignores_query_and_cookie_tokens(client: AsyncClient) -> None:
    """REST : en-tête seulement. Un token en query (journaux, historique) ou
    en cookie (envoyé d'office par le navigateur, forme CSRF) ne vaut rien."""
    resp = await client.get("/api/stats", params={"token": TOKEN})
    assert resp.status_code == 401
    resp = await client.get("/api/stats", cookies={"fontsync_token": TOKEN})
    assert resp.status_code == 401


def test_blank_configured_token_is_never_the_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`FONTSYNC_TOKEN="   "` vaut « absent » : un token est généré, et une
    suite d'espaces n'ouvre rien."""
    monkeypatch.setattr(settings, "fontsync_token", "   ")
    monkeypatch.setattr(auth, "_generated_token", None)
    assert auth.get_server_token().strip()
    assert not auth.token_is_valid("   ")


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="Constat de relecture P1-4c : `compare_digest` lève TypeError sur un "
    "token non ASCII (500 au lieu de 401). Corrigé avec P1-5e (comparaison sur "
    "octets) : retirer ce marqueur alors.",
)
async def test_non_ascii_token_is_rejected_not_an_error() -> None:
    assert not auth.token_is_valid(TOKEN + "é")


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", _NEAR_MISSES)
async def test_rest_rejects_near_miss_bearer(
    client: AsyncClient, candidate: str
) -> None:
    resp = await client.get("/api/stats", headers=_bearer(candidate))
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", _NEAR_MISSES)
async def test_require_token_stream_rejects_near_misses(candidate: str) -> None:
    for kwargs in (
        {"authorization": f"Bearer {candidate}", "token": None},
        {"authorization": None, "token": candidate},
    ):
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(auth.require_token_stream(**kwargs), 2)
        assert exc.value.status_code == 401


def test_ws_client_rejected_with_wrong_cookie() -> None:
    client = TestClient(app)
    client.cookies.set("fontsync_token", "nope")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/client"):
            pass


@pytest.mark.parametrize("via", ["query", "header", "cookie"])
@pytest.mark.parametrize("candidate", _NEAR_MISSES)
def test_ws_client_rejects_near_misses(candidate: str, via: str) -> None:
    client = TestClient(app)
    url, headers = "/ws/client", {}
    if via == "query":
        url = f"/ws/client?{urlencode({'token': candidate})}"
    elif via == "header":
        headers = _bearer(candidate)
    else:
        client.cookies.set("fontsync_token", candidate)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url, headers=headers):
            pass


def test_ws_client_rejected_with_wrong_header() -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/client", headers={"Authorization": "Bearer nope"}
        ):
            pass


def test_ws_client_accepts_header() -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws/client", headers=_bearer()) as ws:
        ws.close()
