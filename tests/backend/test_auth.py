"""Contrat de `backend.auth` bout-en-bout sur l'app réelle.

L'identité est une session de compte (`conftest.seed_session`) :
- tout `/api/*` exige une session (`401` sans / avec mauvais token, `200` avec),
  vérifié route par route par énumération de l'app (M-49) ; REST n'accepte
  que l'en-tête `Authorization` ;
- `/health` reste public, et aucune autre route publique n'apparaît en douce ;
- le flux **SSE** n'accepte que l'en-tête `Authorization` (P1-5e) ;
- les **WebSocket** refusent le handshake sans token et l'acceptent via query
  param ou en-tête (le navigateur ne peut pas poser d'en-tête au handshake) ;
  plus de cookie, et l'Origin est contrôlé (P1-5f, test_ws_origin.py) ;
- les quasi-égalités (préfixe, suffixe, casse, substitution) sont refusées ;
- l'ancien `FONTSYNC_TOKEN` n'ouvre plus rien ;
- les seules routes `/api` publiques sont les entrées de `/api/auth`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.testclient import TestClient

from backend import auth
from backend.config import settings
from backend.main import app
from backend.routers import agent_events
from backend.routers import ws as ws_router
from backend.services.ws_manager import WebSocketManager
from tests.backend.conftest import API_TOKEN as TOKEN

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
def _set_token(auth_db: object) -> None:
    """Base in-memory avec un admin dont la session est `TOKEN`."""


@pytest.fixture(autouse=True)
def _fresh_ws_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un `ws_manager` neuf par test.

    Les tests SSE (boucle asyncio de pytest) et WS (TestClient, thread/loop
    dédié) ne doivent pas partager les files et tâches d'envoi du singleton,
    liées à la boucle qui les a créées (« Future attached to a different
    loop »). Un manager neuf est utilisé par une seule boucle à la fois.
    """
    mgr = WebSocketManager()
    monkeypatch.setattr(agent_events, "ws_manager", mgr)
    monkeypatch.setattr(ws_router, "ws_manager", mgr)


@pytest_asyncio.fixture
async def client(auth_db: object) -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP ASGI sur la base in-memory de `auth_db`."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- REST : header Authorization ----


@pytest.mark.asyncio
async def test_health_is_public(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "maintenance": False}


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


# ---- SSE : en-tête Authorization seulement (P1-5e) ----
#
# Le rejet (token absent/invalide) se vérifie de bout en bout : le middleware
# répond 401 avant d'ouvrir le flux. Le chemin « accepté » ouvrirait un flux SSE
# infini (cf. test_auth_middleware.py pour l'échange ASGI brut).


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
async def test_sse_rejects_valid_query_token(client: AsyncClient) -> None:
    """`?token=` n'est plus accepté nulle part sur /api (l'agent pose l'en-tête)."""
    resp = await asyncio.wait_for(
        client.get("/api/agent/dev-x/events", params={"token": TOKEN}), 5
    )
    assert resp.status_code == 401


# ---- WebSocket : query param ou en-tête (plus de cookie, P1-5f) ----


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


def test_ws_client_rejects_cookie_only() -> None:
    """Voie cookie retirée (P1-5f) : cf. test_ws_origin.py."""
    client = TestClient(app)
    client.cookies.set("fontsync_token", TOKEN)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/client"):
            pass


# ---- L'ancien token d'instance n'ouvre plus rien ----


@pytest.mark.asyncio
async def test_former_instance_token_opens_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `FONTSYNC_TOKEN` resté dans l'environnement est ignoré."""
    monkeypatch.setenv("FONTSYNC_TOKEN", "former-instance-token")
    resp = await client.get("/api/stats", headers=_bearer("former-instance-token"))
    assert resp.status_code == 401


# ---- Énumération structurelle et quasi-égalités (M-49) ----
#
# Chaque route `/api/*` de l'app réelle, telle que montée : un router ajouté
# sans `Depends(require_auth)` (ou un `include_router` qui la perd) fait
# échouer la suite, sans qu'il faille penser à l'ajouter à une liste.

# Tout /api, SSE compris : en-tête seulement (`AuthMiddleware` puis
# `require_auth`) ; `?token=` n'est admis que sur le WebSocket navigateur.
# Hors `/api` : la santé et, si le frontend est buildé, le repli SPA.
_PUBLIC_ROUTES = {"/health", "/{full_path:path}"}
# Routes Starlette (pas FastAPI) admises : la doc OpenAPI (seulement si
# FONTSYNC_API_DOCS=true depuis P1-5e) et les assets du frontend buildé. Toute autre (`add_route`, `mount`,
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
# `app.dependency_overrides[require_auth] = …` dans l'app ouvrirait tout.
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


_PROTECTED_API_CALLS = [(m, p) for m, p in _API_CALLS if p not in auth.PUBLIC_API_PATHS]


def test_public_api_paths_are_exactly_the_auth_entry_points() -> None:
    """Toute route publique de `/api` est une entrée de `/api/auth` listée."""
    public = {p for _m, p in _API_CALLS if p in auth.PUBLIC_API_PATHS}
    assert public == set(auth.PUBLIC_API_PATHS)
    assert all(p.startswith("/api/auth/") for p in public)


@pytest.mark.parametrize(("method", "path"), _PROTECTED_API_CALLS)
def test_every_api_route_declares_the_token_dependency(method: str, path: str) -> None:
    route = next(r for r in _api_routes() if r.path == path and method in r.methods)
    assert auth.require_auth in _dependency_calls(route.dependant), (
        f"{method} {path} n'exige pas require_auth"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _PROTECTED_API_CALLS)
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
    assert auth.require_auth not in _OVERRIDES_AT_IMPORT


# Préfixe, suffixe, casse, troncature, substitution à longueur égale : une
# comparaison relâchée (préfixe, `in`, insensible à la casse, partielle) en
# accepterait au moins un.
_NEAR_MISSES = [TOKEN[:-1], TOKEN + "x", TOKEN.upper(), TOKEN[1:], TOKEN[:-1] + "X"]


@pytest.mark.asyncio
async def test_rest_ignores_query_and_cookie_tokens(client: AsyncClient) -> None:
    """REST : en-tête seulement. Un token en query (journaux, historique) ou
    en cookie (envoyé d'office par le navigateur, forme CSRF) ne vaut rien."""
    resp = await client.get("/api/stats", params={"token": TOKEN})
    assert resp.status_code == 401
    resp = await client.get("/api/stats", cookies={"fontsync_token": TOKEN})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_non_ascii_token_is_rejected_not_an_error(client: AsyncClient) -> None:
    value = ("Bearer " + TOKEN[:-1] + "é").encode("latin-1")
    resp = await client.get("/api/stats", headers={"Authorization": value})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", _NEAR_MISSES)
async def test_rest_rejects_near_miss_bearer(
    client: AsyncClient, candidate: str
) -> None:
    resp = await client.get("/api/stats", headers=_bearer(candidate))
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", _NEAR_MISSES)
async def test_sse_rejects_near_misses(client: AsyncClient, candidate: str) -> None:
    for kwargs in (
        {"headers": _bearer(candidate)},
        {"params": {"token": candidate}},
    ):
        resp = await asyncio.wait_for(
            client.get("/api/agent/dev-x/events", **kwargs), 5
        )
        assert resp.status_code == 401


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
        client.cookies.set("fontsync_session", candidate)
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
