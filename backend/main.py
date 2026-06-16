from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import agent_events, devices, font_families, fonts, stats, sync, ws

app = FastAPI(title="FontSync", version="0.1.0")
app.include_router(fonts.router)
app.include_router(devices.router)
app.include_router(sync.router)
app.include_router(font_families.router)
app.include_router(stats.router)
app.include_router(agent_events.router)
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
