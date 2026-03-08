from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import devices, fonts, stats, sync, ws

app = FastAPI(title="FontSync", version="0.1.0")
app.include_router(fonts.router)
app.include_router(devices.router)
app.include_router(sync.router)
app.include_router(stats.router)
app.include_router(ws.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Serve frontend static assets (JS, CSS, images, etc.)
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str) -> FileResponse:
        """Serve index.html for all non-API routes (SPA fallback)."""
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
