"""Auth en middleware ASGI (P1-5e, B-157, B-143, B-54).

Les dépendances `require_auth` des routeurs ne s'exécutent qu'APRÈS que
FastAPI a lu et analysé le corps (formulaire multipart, JSON) : un client sans
token pouvait faire lire au serveur des centaines de Mio avant le 401. Le
middleware refuse tout `/api/*` sans `Authorization: Bearer` valide sans jamais
appeler `receive()`. Les docs d'API (/docs, /redoc, /openapi.json) sont coupées
par défaut, et le flux SSE n'accepte plus `?token=` (aucun client ne s'en sert :
l'agent pose l'en-tête).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.config import settings
from backend.main import app

TOKEN = "test-secret-token"
REPO = Path(__file__).resolve().parents[2]
BODY_SIZE = 5 * 1024 * 1024
CHUNK = 64 * 1024


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fontsync_token", TOKEN)
    monkeypatch.setattr(settings, "allowed_hosts", "")


class Exchange:
    """Requête ASGI brute : compte les `http.request` consommés par l'app."""

    def __init__(self) -> None:
        self.consumed = 0
        self.messages: list[dict[str, Any]] = []

    async def call(
        self,
        method: str,
        path: str,
        *,
        headers: list[tuple[bytes, bytes]] | None = None,
        body_size: int = 0,
        query: bytes = b"",
        timeout: float = 5,
        root_path: str = "",
    ) -> int:
        remaining = body_size

        async def receive() -> dict[str, Any]:
            nonlocal remaining
            if remaining <= 0:
                await asyncio.sleep(3600)  # un flux ouvert attend la déconnexion
                return {"type": "http.disconnect"}
            self.consumed += 1
            size = min(CHUNK, remaining)
            remaining -= size
            return {
                "type": "http.request",
                "body": b"x" * size,
                "more_body": remaining > 0,
            }

        async def send(message: dict[str, Any]) -> None:
            self.messages.append(message)
            if message["type"] == "http.response.start":
                raise _Started

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "root_path": root_path,
            "headers": [
                *(
                    []
                    if any(k == b"host" for k, _ in headers or [])
                    else [(b"host", b"localhost")]
                ),
                *(headers or []),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
        }
        try:
            await asyncio.wait_for(app(scope, receive, send), timeout)
        except _Started:
            pass
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return int(start["status"])

    def header(self, name: bytes) -> bytes | None:
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return dict(start.get("headers", [])).get(name)


class _Started(Exception):
    """Arrête l'échange dès l'en-tête de réponse (évite d'attendre un flux)."""


MULTIPART = [
    (b"content-type", b"multipart/form-data; boundary=----fontsync"),
    (b"content-length", str(BODY_SIZE).encode()),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/fonts/upload", "/api/sync/push"])
async def test_upload_without_token_rejected_before_body(path: str) -> None:
    ex = Exchange()
    status = await ex.call("POST", path, headers=MULTIPART, body_size=BODY_SIZE)
    assert status == 401
    assert ex.consumed == 0
    assert ex.header(b"www-authenticate") == b"Bearer"
    # Connexion fermée : le serveur ne lira pas le reste du corps pour le jeter.
    assert ex.header(b"connection") == b"close"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/fonts/upload", "/api/sync/push"])
async def test_upload_with_wrong_token_rejected_before_body(path: str) -> None:
    ex = Exchange()
    headers = [*MULTIPART, (b"authorization", b"Bearer nope")]
    status = await ex.call("POST", path, headers=headers, body_size=BODY_SIZE)
    assert status == 401
    assert ex.consumed == 0


@pytest.mark.asyncio
async def test_json_body_without_token_rejected_before_body() -> None:
    ex = Exchange()
    headers = [(b"content-type", b"application/json"), (b"content-length", b"999999")]
    status = await ex.call("POST", "/api/sync/delta", headers=headers, body_size=999999)
    assert status == 401
    assert ex.consumed == 0


@pytest.mark.asyncio
async def test_sse_rejects_query_token() -> None:
    ex = Exchange()
    status = await ex.call(
        "GET", "/api/agent/dev-x/events", query=f"token={TOKEN}".encode()
    )
    assert status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/api/does-not-exist", "/api", "/api/fonts/x/nothing-here"]
)
async def test_every_api_path_requires_token_even_unrouted(path: str) -> None:
    """Le middleware couvre tout /api/*, routé ou non (défense hors routeurs)."""
    assert await Exchange().call("GET", path) == 401
    ok = Exchange()
    authorized = await ok.call(
        "GET", path, headers=[(b"authorization", f"Bearer {TOKEN}".encode())]
    )
    assert authorized == 404


@pytest.mark.asyncio
async def test_host_guard_runs_before_auth() -> None:
    ex = Exchange()
    scope_headers = [(b"host", b"evil.example")]
    # Host étranger sans token : la garde Host répond (400), jamais l'auth.
    status = await ex.call("GET", "/api/stats", headers=scope_headers)
    assert status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [b"Bearer test-secret-tok\xc3\xa9", b"Bearer \xff\xfe", b"Bearer"]
)
async def test_malformed_or_non_ascii_token_is_401_not_500(value: bytes) -> None:
    ex = Exchange()
    assert (
        await ex.call("GET", "/api/stats", headers=[(b"authorization", value)]) == 401
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health", "/", "/fonts", "/apiary"])
async def test_public_paths_stay_public(path: str) -> None:
    assert await Exchange().call("GET", path) != 401


# ---- docs d'API ----

DOC_PATHS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_api_docs_disabled_by_default(path: str) -> None:
    assert await Exchange().call("GET", path) == 404


def test_api_docs_enabled_with_setting() -> None:
    code = """
import json
from fastapi.testclient import TestClient
from backend.main import app
c = TestClient(app, base_url="http://localhost")
print(json.dumps({p: c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")}))
"""
    env = {k: v for k, v in os.environ.items() if k != "FONTSYNC_API_DOCS"}
    env["FONTSYNC_API_DOCS"] = "true"
    env["FONTSYNC_TOKEN"] = TOKEN
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "/docs": 200,
        "/redoc": 200,
        "/openapi.json": 200,
    }


# ---- root_path (uvicorn --root-path / UVICORN_ROOT_PATH) ----


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/fs/api/fonts/upload", "/fs/api/sync/push"])
async def test_root_path_does_not_bypass_the_middleware(path: str) -> None:
    """Sous un sous-chemin, Starlette route sur path − root_path (relecture A)."""
    ex = Exchange()
    status = await ex.call(
        "POST", path, headers=MULTIPART, body_size=BODY_SIZE, root_path="/fs"
    )
    assert status == 401
    assert ex.consumed == 0


@pytest.mark.parametrize(
    ("path", "root_path"),
    [
        ("/fs/api/stats", "/fs"),
        ("/api/stats", "/fs"),
        ("/fs", "/fs"),
        ("/fsapi/stats", "/fs"),
        ("/fs/api", "/fs"),
        ("/api/stats", ""),
        ("/x/y", "/x/y"),
    ],
)
def test_route_path_matches_starlette(path: str, root_path: str) -> None:
    from starlette._utils import get_route_path

    from backend.auth import _route_path

    scope = {"type": "http", "path": path, "root_path": root_path}
    assert _route_path(scope) == get_route_path(scope)


# ---- Le middleware seul (sans les dépendances des routeurs) ----


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "query", "expected"),
    [
        ([], f"token={TOKEN}".encode(), 401),
        ([(b"cookie", f"fontsync_token={TOKEN}".encode())], b"", 401),
        ([(b"authorization", f"Basic {TOKEN}".encode())], b"", 401),
        ([(b"authorization", f"Bearer {TOKEN}".encode())], b"", 200),
    ],
)
async def test_middleware_alone_accepts_only_the_bearer_header(
    headers: list[tuple[bytes, bytes]], query: bytes, expected: int
) -> None:
    """Défense en profondeur dans les deux sens : le middleware ne compte pas
    sur `require_auth` (ni l'inverse)."""
    from backend.auth import AuthMiddleware

    reached: list[bool] = []

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        raise AssertionError("body read")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/agent/x/events",
        "root_path": "",
        "query_string": query,
        "headers": headers,
    }
    await AuthMiddleware(inner)(scope, receive, send)
    assert messages[0]["status"] == expected
    assert reached == ([True] if expected == 200 else [])
