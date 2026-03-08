from fastapi import FastAPI

from backend.routers import fonts

app = FastAPI(title="FontSync", version="0.1.0")
app.include_router(fonts.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
