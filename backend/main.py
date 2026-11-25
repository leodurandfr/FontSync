# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# This file is part of FontSync, a self-hosted font manager.
# FontSync is free software: you can redistribute it and/or modify it under the
# terms of the GNU Affero General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. It is distributed WITHOUT ANY WARRANTY; see the GNU AGPL for details.
# You should have received a copy of the license with this program (see LICENSE),
# or at <https://www.gnu.org/licenses/>.

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.auth import AuthMiddleware, legacy_token, require_auth
from backend.config import settings
from backend.database import async_session
from backend.host_guard import HostGuardMiddleware
from backend.logging_filters import install_token_redaction
from backend.routers import (
    agent_events,
    auth,
    devices,
    font_families,
    fonts,
    removals,
    stats,
    sync,
    system,
    users,
    ws,
)
from backend.services.accounts import bootstrap_admin_from_env
from backend.services.backup import run_blob_backup_loop, run_database_backup_loop
from backend.services.storage import get_storage_backend
from backend.services.trash import run_purge_loop

logger = logging.getLogger(__name__)

# Le token peut arriver en `?token=` (WebSocket navigateur) : uvicorn
# journalise le chemin complet, query comprise. Le filtre est posé à l'import,
# après la configuration des loggers par uvicorn, qui ne retire pas les filtres.
install_token_redaction()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Au boot : premier admin éventuel, purge de corbeille, sauvegardes.

    `FONTSYNC_ADMIN_EMAIL`/`_PASSWORD` créent le premier admin si aucun compte
    n'existe (installation scriptée). Le token d'instance hérité, s'il est
    défini, est signalé : il ne sert plus qu'à la transition vers les comptes.

    La purge automatique de la corbeille ne tourne que si une rétention est
    configurée — désactivée par défaut : rien ne supprime de fichier tout seul
    sans qu'on l'ait demandé.

    La sauvegarde automatique (base + polices) ne tourne que si `BACKUP_DIR`
    est configuré — désactivée par défaut, cf. `backend.services.backup`.
    """
    try:
        async with async_session() as db:
            await bootstrap_admin_from_env(db)
    except Exception:  # noqa: BLE001 — une base pas encore migrée ne doit pas tuer le boot
        logger.exception("Création du premier admin depuis l'environnement impossible.")
    if legacy_token() is not None:
        logger.warning(
            "FONTSYNC_TOKEN est défini : il reste accepté avec les droits admin. "
            "Retirez-le du .env une fois chaque Mac connecté avec un compte."
        )

    background_tasks = [
        asyncio.create_task(run_purge_loop(async_session, get_storage_backend)),
        asyncio.create_task(run_database_backup_loop()),
        asyncio.create_task(run_blob_backup_loop()),
    ]
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task


# Docs interactives coupées par défaut (B-143) : `FONTSYNC_API_DOCS=true`.
_DOCS = settings.api_docs_enabled
app = FastAPI(
    title="FontSync",
    version=settings.fontsync_version or "dev",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)
_default_openapi = app.openapi


def _versioned_openapi() -> dict:
    """Schéma OpenAPI dont `info.version` suit `FONTSYNC_VERSION` (injectée au
    build de l'image), au lieu d'une constante qui ne bougeait jamais."""
    version = settings.fontsync_version or "dev"
    if app.version != version:
        app.version = version
        app.openapi_schema = None
    return _default_openapi()


app.openapi = _versioned_openapi  # type: ignore[method-assign]

# Auth (P1-5e) : tout `/api/*` sans identité valide (cookie de session, jeton
# d'appareil, token hérité) reçoit 401 AVANT que le corps soit lu (B-157). Ajouté avant la
# garde Host, donc exécuté après elle : Starlette fait du dernier middleware
# ajouté le plus externe.
app.add_middleware(AuthMiddleware)

# Garde anti DNS rebinding : un `Host` inattendu est refusé avant toute route
# (400, ou fermeture 1008 pour le WebSocket). Réglage `ALLOWED_HOSTS`, cf.
# `backend.host_guard` et docs/INSTALL-NAS.md.
app.add_middleware(HostGuardMiddleware)

# Défense en profondeur : chaque routeur `/api/*` redemande l'identité (même
# règle que le middleware, SSE compris). Le WebSocket la vérifie dans son
# propre handler. `/health`, la SPA et les routes publiques de `/api/auth`
# (`backend.auth.PUBLIC_API_PATHS`) se passent d'identité.
app.include_router(fonts.router, dependencies=[Depends(require_auth)])
app.include_router(devices.router, dependencies=[Depends(require_auth)])
app.include_router(sync.router, dependencies=[Depends(require_auth)])
app.include_router(font_families.router, dependencies=[Depends(require_auth)])
app.include_router(stats.router, dependencies=[Depends(require_auth)])
app.include_router(system.router, dependencies=[Depends(require_auth)])
app.include_router(agent_events.router, dependencies=[Depends(require_auth)])
app.include_router(auth.router)
app.include_router(removals.router, dependencies=[Depends(require_auth)])
app.include_router(users.users_router, dependencies=[Depends(require_auth)])
app.include_router(users.invitations_router, dependencies=[Depends(require_auth)])
app.include_router(ws.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Politiques de cache du SPA. Sans en-tête explicite, un cache HTTP a le droit
# de deviner une fraîcheur à partir de `Last-Modified` (RFC 9111 §4.2.2) et de
# resservir une page périmée sans rien revalider — ce qui fige une version du
# frontend chez le client (typiquement la WKWebView de l'app macOS, dont le
# `websiteDataStore` persiste sur disque et survit au redémarrage de l'app).
#
# `index.html` est le seul point d'entrée mutable : on le fait **toujours**
# revalider (`no-cache` autorise le cache, mais impose un aller-retour ; l'ETag
# rend la réponse 304 la plupart du temps). Les assets Vite portent un hash de
# contenu dans leur nom : leur URL change à chaque build, ils sont donc
# immuables et cachables sans limite.
_HTML_CACHE_CONTROL = "no-cache"
# Chemins des docs d'API : 404 quand elles sont coupées, jamais la SPA (un 200
# HTML ferait croire qu'elles sont servies).
_RESERVED = frozenset({"api", "docs", "redoc", "openapi.json"})
_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


class ImmutableStaticFiles(StaticFiles):
    """`StaticFiles` marquant ses réponses comme immuables (assets hashés)."""

    def file_response(self, *args: object, **kwargs: object) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
        return response


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Mount the built frontend (`dist`) on `app`: `/assets` plus the SPA fallback.

    The fallback only serves files listed at mount time directly under `dist`
    (favicon, manifest…), looked up by exact name; any other path gets
    `index.html`. No filesystem path is ever built from the request URL.
    """
    app.mount(
        "/assets",
        ImmutableStaticFiles(directory=dist / "assets"),
        name="static",
    )
    root_files = frozenset(
        entry.name
        for entry in dist.iterdir()
        if entry.is_file() and not entry.is_symlink()
    )
    index_html = dist / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> Response:
        """Serve index.html for all non-API routes (SPA fallback).

        Les chemins `/api/*` non résolus renvoient un 404 JSON plutôt que la
        SPA, pour qu'une URL d'API mal orthographiée échoue clairement au lieu
        de renvoyer du HTML.

        Tout ce qui passe ici est servi en `no-cache` : `index.html` change à
        chaque build, et les fichiers racine (favicon, manifeste…) n'ont pas de
        hash dans leur nom — aucun n'est sûr à figer côté client.
        """
        if full_path in _RESERVED or full_path.startswith(("api/", "docs/")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        headers = {"Cache-Control": _HTML_CACHE_CONTROL}
        if full_path in root_files:
            return FileResponse(dist / full_path, headers=headers)
        return FileResponse(index_html, headers=headers)


# Serve frontend static assets (JS, CSS, images, etc.)
if FRONTEND_DIR.is_dir():
    mount_frontend(app, FRONTEND_DIR)
