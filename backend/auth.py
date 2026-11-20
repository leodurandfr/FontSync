"""Auth par token partagé d'instance (P1, PLAN-PUBLICATION.md).

Un secret serveur unique (`FONTSYNC_TOKEN`) protège tout `/api/*`. Il **n'y a
pas de comptes utilisateurs** : le token protège une instance mono-utilisateur
implicite (la frontière de tenancy se décide au passage cloud / Phase 7).

Politique de présentation du token :
- **Tout `/api/*`, SSE compris** : `Authorization: Bearer <token>`, vérifié par
  `TokenAuthMiddleware` AVANT toute lecture du corps (P1-5e), puis de nouveau
  par la dépendance `require_token` des routeurs (défense en profondeur).
  L'agent (httpx) et le frontend (`fetch`) posent l'en-tête ; le flux SSE n'est
  lu que par l'agent, qui le pose aussi (plus de `?token=`).
- **WebSocket** (`websocket_token` / `verify_websocket_token`) : query param,
  en-tête `Authorization`, ou cookie `fontsync_token` — le `WebSocket` natif du
  navigateur ne permet pas d'en-tête custom au handshake.

Si `FONTSYNC_TOKEN` n'est pas défini, on **génère** un token au démarrage et on
le **loggue** (visible dans les logs du conteneur) : un serveur potentiellement
exposé sur un NAS ne doit jamais rester ouvert par défaut.
"""

from __future__ import annotations

import json
import logging
import secrets

from fastapi import Header, HTTPException, WebSocket, status
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.config import settings

logger = logging.getLogger(__name__)

# Token de repli généré une seule fois par process si `FONTSYNC_TOKEN` est vide.
# Mémorisé ici pour rester stable sur la durée de vie du serveur (sinon il
# changerait à chaque requête et invaliderait les agents déjà connectés).
_generated_token: str | None = None


def get_server_token() -> str:
    """Retourne le token d'instance effectif.

    `FONTSYNC_TOKEN` s'il est défini ; sinon un token aléatoire généré une fois
    et loggué (avec un avertissement de le figer). La lecture de `settings` est
    dynamique → les tests peuvent surcharger `settings.fontsync_token`.
    """
    global _generated_token
    configured = (settings.fontsync_token or "").strip()
    if configured:
        return configured
    if _generated_token is None:
        _generated_token = secrets.token_urlsafe(32)
        logger.warning(
            "FONTSYNC_TOKEN non défini : token d'instance généré pour cette "
            "session : %s\n"
            "Définissez FONTSYNC_TOKEN (env) pour le figer — sinon il change à "
            "chaque redémarrage et tous les agents/navigateurs devront le ressaisir.",
            _generated_token,
        )
    return _generated_token


def _bearer(authorization: str | None) -> str | None:
    """Extrait le token d'un en-tête `Authorization: Bearer <token>`."""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def token_is_valid(token: str | None) -> bool:
    """Compare le token fourni au token serveur en temps constant.

    Sur octets UTF-8 : `compare_digest` lève TypeError sur une chaîne non ASCII
    (un en-tête arbitraire donnait 500 au lieu de 401).
    """
    if not token:
        return False
    return secrets.compare_digest(
        token.encode("utf-8", "surrogatepass"),
        get_server_token().encode("utf-8", "surrogatepass"),
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token manquant ou invalide.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_token(authorization: str | None = Header(default=None)) -> None:
    """Dependency REST : exige un `Authorization: Bearer <token>` valide."""
    if not token_is_valid(_bearer(authorization)):
        raise _unauthorized()


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


_UNAUTHORIZED_BODY = json.dumps(
    {"detail": "Token manquant ou invalide."}, ensure_ascii=False
).encode("utf-8")


class TokenAuthMiddleware:
    """Pure ASGI middleware: `/api/*` requires a valid Bearer token.

    Refuses with 401 before the application, hence before `receive()` is ever
    called: an unauthenticated client cannot make the server read or parse a
    request body (multipart upload, JSON). WebSocket scopes are left to their
    handler (`/ws/client`, browser handshake without headers).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_api_path(_route_path(scope)):
            await self.app(scope, receive, send)
            return
        # Premier en-tête, comme `Header()` côté dépendance.
        authorization = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", ())
                if key == b"authorization"
            ),
            None,
        )
        if token_is_valid(_bearer(authorization)):
            await self.app(scope, receive, send)
            return
        # Point d'accroche du 413 (P2-5o) : la limite de taille du corps se
        # posera ici aussi, sur Content-Length, toujours sans lire le corps.
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode()),
                    (b"www-authenticate", b"Bearer"),
                    # Sinon le serveur garde la connexion et lit (pour le jeter)
                    # tout le corps qu'un client non authentifié envoie.
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})


def websocket_token(websocket: WebSocket) -> str | None:
    """Token présenté par un client WebSocket.

    Ordre de priorité : query param `token`, en-tête `Authorization: Bearer`,
    puis cookie `fontsync_token`. Le `WebSocket` natif du navigateur ne pouvant
    pas poser d'en-tête au handshake, le query param (ou le cookie) est la voie
    réaliste côté frontend.
    """
    qp = websocket.query_params.get("token")
    if qp:
        return qp
    header = _bearer(websocket.headers.get("authorization"))
    if header:
        return header
    return websocket.cookies.get("fontsync_token")


def verify_websocket_token(websocket: WebSocket) -> bool:
    """Valide le token d'un client WebSocket (voir `websocket_token`)."""
    return token_is_valid(websocket_token(websocket))
