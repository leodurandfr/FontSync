"""Auth par token partagé d'instance (P1, PLAN-PUBLICATION.md).

Un secret serveur unique (`FONTSYNC_TOKEN`) protège tout `/api/*`. Il **n'y a
pas de comptes utilisateurs** : le token protège une instance mono-utilisateur
implicite (la frontière de tenancy se décide au passage cloud / Phase 7).

Politique de présentation du token :
- **REST** (`require_token`) : `Authorization: Bearer <token>`. L'agent (httpx)
  et le frontend (`fetch`) peuvent tous deux poser cet en-tête.
- **SSE** (`require_token_stream`) : en-tête `Authorization` **ou** query param
  `?token=…`. L'agent SSE pose l'en-tête ; un `EventSource` navigateur, qui ne
  peut pas poser d'en-tête, passe par le query param.
- **WebSocket** (`websocket_token` / `verify_websocket_token`) : query param,
  en-tête `Authorization`, ou cookie `fontsync_token` — le `WebSocket` natif du
  navigateur ne permet pas d'en-tête custom au handshake.

Si `FONTSYNC_TOKEN` n'est pas défini, on **génère** un token au démarrage et on
le **loggue** (visible dans les logs du conteneur) : un serveur potentiellement
exposé sur un NAS ne doit jamais rester ouvert par défaut.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Header, HTTPException, Query, WebSocket, status

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
    """Compare le token fourni au token serveur en temps constant."""
    if not token:
        return False
    return secrets.compare_digest(token, get_server_token())


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


async def require_token_stream(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """Dependency SSE : en-tête `Authorization` **ou** query param `?token=`."""
    if not token_is_valid(_bearer(authorization) or token):
        raise _unauthorized()


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
