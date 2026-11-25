"""Authentification : comptes, sessions par connexion, token d'instance hérité.

Qui peut appeler l'API (`Principal`) :

- **session web** : cookie `HttpOnly` `fontsync_session`, posé par
  `POST /api/auth/login`. Le JavaScript de la page ne voit jamais le secret, et
  le WebSocket navigateur s'authentifie par ce même cookie ;
- **jeton d'appareil** : `Authorization: Bearer <jeton>`, obtenu par
  `POST /api/auth/device-login` (app Mac, agent). Un par machine, sans
  expiration, révocable seul, lié à UN appareil (`assert_device_access`) ;
- **token d'instance hérité** (`FONTSYNC_TOKEN`) : s'il est défini, il reste
  accepté en `Bearer` avec les droits admin, le temps que chaque Mac passe à son
  jeton d'appareil. Le retirer du `.env` le coupe.

Une session web peut aussi être présentée en `Bearer` (client d'API, tests).

`/api/*` est filtré par `AuthMiddleware` AVANT toute lecture du corps (P1-5e),
puis de nouveau par la dépendance `require_auth` des routeurs (défense en
profondeur). Seules les routes de `PUBLIC_API_PATHS` (statut, création du
premier admin, connexion, invitations) passent sans identité.

Une requête authentifiée par cookie et qui modifie quelque chose doit venir
d'une `Origin` admise : le cookie est `SameSite=Strict`, ce contrôle est la
ceinture en plus des bretelles contre le CSRF.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.cookies import SimpleCookie

from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.config import settings
from backend.database import get_db
from backend.host_guard import origin_is_allowed
from backend.models.user import ROLE_ADMIN, SESSION_DEVICE, SESSION_WEB
from backend.services.accounts import resolve_session

logger = logging.getLogger(__name__)

SESSION_COOKIE = "fontsync_session"
KIND_LEGACY = "legacy"

# Routes `/api/*` servies sans identité. Exactes, jamais par préfixe : une route
# ajoutée sous `/api/auth/` reste protégée tant qu'on ne l'a pas listée ici.
PUBLIC_API_PATHS = frozenset(
    {
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/device-login",
        "/api/auth/invitations/lookup",
        "/api/auth/invitations/accept",
    }
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Principal:
    """Qui fait la requête."""

    kind: str  # "web" | "device" | "legacy"
    role: str
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None

    @property
    def is_admin(self) -> bool:
        """Droits d'administration. Jamais pour un jeton d'appareil : il dort sur
        le disque d'un Mac, sans expiration ; il ne doit pas pouvoir gérer les
        comptes ni vider la corbeille, même celui d'un admin."""
        return self.role == ROLE_ADMIN and self.kind != SESSION_DEVICE


LEGACY_PRINCIPAL = Principal(kind=KIND_LEGACY, role=ROLE_ADMIN)


# ---------- Token d'instance hérité ----------


def legacy_token() -> str | None:
    """`FONTSYNC_TOKEN` s'il est défini (et non blanc), sinon `None`.

    Lu à chaque appel : les tests surchargent `settings.fontsync_token`.
    """
    configured = (settings.fontsync_token or "").strip()
    return configured or None


def token_is_valid(token: str | None) -> bool:
    """Compare un jeton au token d'instance hérité, en temps constant.

    Sur octets UTF-8 : `compare_digest` lève TypeError sur une chaîne non ASCII
    (un en-tête arbitraire donnait 500 au lieu de 401).
    """
    expected = legacy_token()
    if not token or expected is None:
        return False
    return secrets.compare_digest(
        token.encode("utf-8", "surrogatepass"),
        expected.encode("utf-8", "surrogatepass"),
    )


# ---------- Résolution ----------


def _bearer(authorization: str | None) -> str | None:
    """Extrait le token d'un en-tête `Authorization: Bearer <token>`."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def _cookie_value(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except Exception:  # noqa: BLE001 — en-tête malformé = pas de cookie
        return None
    morsel = jar.get(SESSION_COOKIE)
    return morsel.value if morsel and morsel.value else None


@asynccontextmanager
async def db_session_for(app: ASGIApp | None) -> AsyncIterator[AsyncSession]:
    """Session de base hors injection FastAPI (middleware, WebSocket).

    Passe par `app.dependency_overrides` comme le ferait `Depends(get_db)` :
    les tests y branchent leur base en mémoire.
    """
    overrides = getattr(app, "dependency_overrides", {}) or {}
    factory = overrides.get(get_db, get_db)
    gen = factory()
    session = await gen.__anext__()
    try:
        yield session
    finally:
        await gen.aclose()


# Forme exacte d'un jeton émis par `services.accounts.new_token` (32 octets en
# base64 URL-safe, sans remplissage). Tout le reste est refusé sans toucher la
# base : un en-tête arbitraire ne coûte pas une requête SQL.
_SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def looks_like_session_token(token: str) -> bool:
    return _SESSION_TOKEN.fullmatch(token) is not None


async def resolve_principal(
    db: AsyncSession, *, bearer: str | None, cookie: str | None
) -> Principal | None:
    """Identité portée par un `Bearer` (prioritaire) ou le cookie de session."""
    if bearer:
        if token_is_valid(bearer):
            return LEGACY_PRINCIPAL
        if not looks_like_session_token(bearer):
            return None
        found = await resolve_session(db, bearer, kinds=(SESSION_WEB, SESSION_DEVICE))
    elif cookie and looks_like_session_token(cookie):
        found = await resolve_session(db, cookie, kinds=(SESSION_WEB,))
    else:
        return None
    if found is None:
        return None
    return Principal(
        kind=found.kind,
        role=found.role,
        user_id=found.user_id,
        session_id=found.session_id,
        device_id=found.device_id,
    )


async def principal_for_app(
    app: ASGIApp | None, *, bearer: str | None, cookie: str | None
) -> Principal | None:
    """`resolve_principal` hors injection : n'ouvre la base que si un jeton de
    session plausible est présenté (le token hérité se vérifie sans elle)."""
    if bearer and token_is_valid(bearer):
        return LEGACY_PRINCIPAL
    candidate = bearer if bearer else cookie
    if not candidate or not looks_like_session_token(candidate):
        return None
    async with db_session_for(app) as db:
        return await resolve_principal(db, bearer=bearer, cookie=cookie)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentification requise.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Principal:
    """Dependency REST : exige une identité valide (posée par le middleware,
    sinon résolue ici — défense en profondeur)."""
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    principal = await resolve_principal(
        db,
        bearer=_bearer(request.headers.get("authorization")),
        cookie=request.cookies.get(SESSION_COOKIE),
    )
    if principal is None:
        raise _unauthorized()
    request.state.principal = principal
    return principal


async def require_admin(principal: Principal = Depends(require_auth)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
    return principal


def can_access_device(principal: Principal, device: object) -> bool:
    """Un jeton d'appareil n'agit que pour SON appareil ; un admin (ou le token
    hérité) pour tous ; un membre pour les siens."""
    device_id = getattr(device, "id", None)
    if principal.kind == SESSION_DEVICE:
        return principal.device_id is not None and principal.device_id == device_id
    if principal.is_admin:
        return True
    return getattr(device, "owner_user_id", None) == principal.user_id


def assert_device_access(principal: Principal, device: object) -> None:
    if not can_access_device(principal, device):
        raise HTTPException(
            status_code=403, detail="Cet appareil ne vous appartient pas."
        )


# ---------- Middleware ----------


def _route_path(scope: Scope) -> str:
    """Path as Starlette routes it: `path` minus `root_path` (same rule as
    `starlette._utils.get_route_path`). Under `--root-path /fs`, uvicorn sends
    `path=/fs/api/…` and the router matches `/api/…` — checking `path` alone
    would let every API call through unauthenticated."""
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path) :]
    return path


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _first_header(scope: Scope, name: bytes) -> str | None:
    return next(
        (
            value.decode("latin-1")
            for key, value in scope.get("headers", ())
            if key == name
        ),
        None,
    )


async def _send_json(send: Send, status_code: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        # Sinon le serveur garde la connexion et lit (pour le jeter) tout le
        # corps qu'un client non authentifié envoie.
        (b"connection", b"close"),
    ]
    if status_code == 401:
        headers.append((b"www-authenticate", b"Bearer"))
    await send(
        {"type": "http.response.start", "status": status_code, "headers": headers}
    )
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    """Pure ASGI middleware: `/api/*` requires an identity (except
    `PUBLIC_API_PATHS`).

    Refuses with 401 before the application, hence before `receive()` is ever
    called: an unauthenticated client cannot make the server read or parse a
    request body (multipart upload, JSON). WebSocket scopes are left to their
    handler (`/ws/client`).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = _route_path(scope)
        if not _is_api_path(path) or path in PUBLIC_API_PATHS:
            await self.app(scope, receive, send)
            return

        bearer = _bearer(_first_header(scope, b"authorization"))
        cookie = None if bearer else _cookie_value(_first_header(scope, b"cookie"))
        principal = await principal_for_app(
            scope.get("app"), bearer=bearer, cookie=cookie
        )
        if principal is None:
            await _send_json(send, 401, "Authentification requise.")
            return

        if cookie and scope.get("method", "GET") not in _SAFE_METHODS:
            origins = [
                value.decode("latin-1")
                for key, value in scope.get("headers", ())
                if key == b"origin"
            ]
            if len(origins) > 1 or not origin_is_allowed(
                origins[0] if origins else None,
                _first_header(scope, b"host"),
                settings.allowed_hosts,
                settings.allowed_origins,
            ):
                await _send_json(send, 403, "Origine non admise.")
                return

        scope.setdefault("state", {})["principal"] = principal
        await self.app(scope, receive, send)


# ---------- WebSocket ----------


def websocket_token(websocket: WebSocket) -> str | None:
    """Jeton présenté en query `token` ou en `Authorization: Bearer`.

    Le navigateur passe par le cookie de session ; ces deux voies restent pour
    le token hérité et les clients hors navigateur.
    """
    qp = websocket.query_params.get("token")
    if qp:
        return qp
    return _bearer(websocket.headers.get("authorization"))


async def websocket_principal(websocket: WebSocket) -> Principal | None:
    return await principal_for_app(
        websocket.scope.get("app"),
        bearer=websocket_token(websocket),
        cookie=websocket.cookies.get(SESSION_COOKIE),
    )
