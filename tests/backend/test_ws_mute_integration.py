"""Intégration P1-7a : un vrai client WebSocket muet ne fige plus le serveur.

uvicorn réel (sous-processus), un client WS brut au SO_RCVBUF de 4 Kio qui ne
lit plus rien, 2 000 diffusions : les tampons TCP se remplissent, et avant le
correctif chaque diffusion suivante — donc chaque upload — attendait ce client
indéfiniment. Un upload (police build_ttf) doit répondre en moins de 2 s.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.backend.conftest import build_ttf

REPO = Path(__file__).resolve().parents[2]
TOKEN = "test-secret-token"

LAUNCHER = """
import asyncio, sys
import uvicorn
from sqlalchemy.ext.asyncio import create_async_engine
from backend.config import settings
from backend.models.base import Base
from backend.main import app
from backend.services.ws_manager import ws_manager

async def create_schema():
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(create_schema())

async def flood(n: int = 2000, size: int = 4096) -> dict:
    # Route de test seulement (ce lanceur), jamais dans l'app livrée.
    for i in range(n):
        await ws_manager.broadcast_to_clients({"type": "flood", "data": "x" * size})
    return {"sent": n}

async def clients() -> dict:
    return {"count": ws_manager.client_count}

app.add_api_route("/__flood", flood, methods=["POST"])
app.add_api_route("/__clients", clients, methods=["POST"])  # GET : pris par la SPA
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path):  # type: ignore[no-untyped-def]
    port = free_port()
    (tmp_path / "fonts").mkdir()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        "FONT_STORAGE_PATH": str(tmp_path / "fonts"),
        "FONTSYNC_TOKEN": TOKEN,
        "ALLOWED_HOSTS": "",
        "BACKUP_DIR": "",
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCHER, str(port)],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=(tmp_path / "server.log").open("w"),
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("serveur de test injoignable")
        yield port
    finally:
        proc.kill()
        proc.wait(timeout=10)


def mute_ws_client(port: int) -> socket.socket:
    """Handshake WebSocket à la main, puis plus aucune lecture."""
    sock = socket.socket()
    try:
        return _handshake(sock, port)
    except BaseException:
        sock.close()
        raise


def _handshake(sock: socket.socket, port: int) -> socket.socket:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    sock.connect(("127.0.0.1", port))
    sock.sendall(
        (
            f"GET /ws/client?token={TOKEN} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1)
    assert head.startswith(b"HTTP/1.1 101"), head
    return sock


def test_integration_mute_ws_client(server: int) -> None:
    base = f"http://127.0.0.1:{server}"
    mute = mute_ws_client(server)
    try:
        try:
            httpx.post(f"{base}/__flood", timeout=3)
        except httpx.TimeoutException:
            pass  # ancien code : la diffusion reste bloquée sur le client muet
        start = time.monotonic()
        response = httpx.post(
            f"{base}/api/fonts/upload",
            headers={"Authorization": f"Bearer {TOKEN}"},
            files={"files": ("mute.ttf", build_ttf(family="Mute Probe"), "font/ttf")},
            timeout=2,
        )
        assert response.status_code == 200
        assert time.monotonic() - start < 2
        assert httpx.get(f"{base}/health", timeout=1).status_code == 200
        # Le flood a bien rempli les tampons : le client muet a été évincé
        # (sinon ce test passerait sans rien prouver, ex. tampons agrandis).
        assert httpx.post(f"{base}/__clients", timeout=1).json() == {"count": 0}
    finally:
        mute.close()
