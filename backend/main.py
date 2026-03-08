from fastapi import FastAPI

from backend.routers import devices, fonts, stats, sync, ws

app = FastAPI(title="FontSync", version="0.1.0")
app.include_router(fonts.router)
app.include_router(devices.router)
app.include_router(sync.router)
app.include_router(stats.router)
app.include_router(ws.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
