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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import get_server_token, require_token, require_token_stream
from backend.routers import agent_events, devices, font_families, fonts, stats, sync, ws

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Au boot : résoudre le token d'instance (le génère + loggue si absent).

    Garantit que le token est visible dans les logs du conteneur dès le
    démarrage (P1.1), sans attendre la première requête.
    """
    get_server_token()
    logger.info("Auth par token activée sur /api/* (token d'instance résolu).")
    yield


app = FastAPI(title="FontSync", version="0.1.0", lifespan=lifespan)

# Auth par token partagé d'instance (P1) : tout `/api/*` exige le token. Les
# routes REST le veulent en en-tête `Authorization: Bearer` ; le flux SSE
# accepte en plus un query param (EventSource navigateur). Le WebSocket vérifie
# le token dans son propre handler (handshake sans en-tête côté navigateur).
# `/health` et la SPA restent publics.
app.include_router(fonts.router, dependencies=[Depends(require_token)])
app.include_router(devices.router, dependencies=[Depends(require_token)])
app.include_router(sync.router, dependencies=[Depends(require_token)])
app.include_router(font_families.router, dependencies=[Depends(require_token)])
app.include_router(stats.router, dependencies=[Depends(require_token)])
app.include_router(agent_events.router, dependencies=[Depends(require_token_stream)])
app.include_router(ws.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve frontend static assets (JS, CSS, images, etc.)
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        """Serve index.html for all non-API routes (SPA fallback).

        Les chemins `/api/*` non résolus renvoient un 404 JSON plutôt que la
        SPA, pour qu'une URL d'API mal orthographiée échoue clairement au lieu
        de renvoyer du HTML.
        """
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
