from fastapi import FastAPI

from backend.routers import fonts, stats

app = FastAPI(title="FontSync", version="0.1.0")
app.include_router(fonts.router)
app.include_router(stats.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
