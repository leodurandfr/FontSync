"""Host header guard (DNS rebinding): unexpected hosts are refused before the app.

Only generic example values are used here (public repository): RFC 2606 / RFC
5737 names and addresses, never the real deployment's host names.
"""

from __future__ import annotations

import pytest
from fastapi import WebSocketDisconnect
from starlette.testclient import TestClient

from backend.config import settings
from backend.host_guard import host_is_allowed
from backend.main import app
from tests.backend.conftest import API_TOKEN

EVIL = "evil.example"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("path", ["/health", "/settings/devices", "/api/stats"])
def test_evil_host_is_rejected_with_400(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Host": EVIL})
    assert response.status_code == 400
    assert "ALLOWED_HOSTS" in response.text


def test_evil_host_with_port_is_rejected(client: TestClient) -> None:
    assert client.get("/health", headers={"Host": f"{EVIL}:8070"}).status_code == 400


@pytest.mark.usefixtures("_api_token")
def test_websocket_handshake_with_evil_host_is_refused() -> None:
    # websocket_connect ignores base_url: the Host comes from an absolute URL.
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(f"ws://{EVIL}/ws/client?token={API_TOKEN}"):
            pass
    assert excinfo.value.code == 1008


@pytest.mark.usefixtures("_api_token")
def test_websocket_handshake_with_allowed_host_still_works() -> None:
    client = TestClient(app)
    url = f"ws://localhost:8070/ws/client?token={API_TOKEN}"
    with client.websocket_connect(url) as ws:
        ws.close()


@pytest.mark.parametrize(
    "host",
    [
        "fontsync.example.ts.net",
        "192.0.2.10:8070",
        "localhost:8070",
        "127.0.0.1:8000",
        "[::1]:8000",
        "nas.local",
        "NAS.Local:8070",
    ],
)
def test_default_hosts_are_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", "")
    response = client.get("/health", headers={"Host": host})
    assert response.status_code == 200


def test_star_disables_the_guard(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", "*")
    assert client.get("/health", headers={"Host": EVIL}).status_code == 200


def test_configured_host_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", "nas.home.lan")
    assert client.get("/health", headers={"Host": "nas.home.lan"}).status_code == 200
    assert client.get("/health", headers={"Host": EVIL}).status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        [(b"host", b"localhost:8070"), (b"host", b"evil.example")],
        [(b"host", b"evil.example"), (b"host", b"localhost:8070")],
        [],
    ],
)
async def test_duplicate_or_missing_host_is_rejected(
    monkeypatch: pytest.MonkeyPatch, headers: list[tuple[bytes, bytes]]
) -> None:
    from backend.host_guard import HostGuardMiddleware

    monkeypatch.setattr(settings, "allowed_hosts", "")
    reached: list[bool] = []

    async def inner(scope: object, receive: object, send: object) -> None:
        reached.append(True)

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "path": "/health", "headers": headers}
    await HostGuardMiddleware(inner)(scope, receive, send)  # type: ignore[arg-type]
    assert not reached
    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    ("host", "allowed", "expected"),
    [
        (None, "", False),
        ("", "", False),
        ("localhost.evil.example", "", False),
        ("evil.local.example", "", False),
        ("ts.net.evil.example", "", False),
        ("127.0.0.1:abc", "", False),
        ("[::1", "", False),
        ("[::1]x", "", False),
        ("::1", "", False),
        ("localhost.", "", True),
        ("[2001:db8::1]", "", True),
        ("a.home.lan", "*.home.lan", True),
        ("home.lan", "*.home.lan", False),
        ("a.home.lan.evil.example", "*.home.lan", False),
        ("Nas.Home.Lan:8070", " nas.home.lan , other.example ", True),
        (EVIL, "", False),
        ("evilts.net", "", False),
        ("notlocal", "", False),
        ("nas.home.arpa", "nas.home.arpa:9000", True),
        ("nas", "", False),
        ("evil.example#.local", "", False),
        ("evil.example/.local", "", False),
        ("evil.example\\.local", "", False),
        ("evil.example?.local", "", False),
        (".local", "", False),
        ("localhost..", "", False),
        ("localhost:\u00b2", "", False),
        ("\u00a0localhost", "", False),
        ("[127.0.0.1]", "", False),
        ("1.2.3.4.", "", True),
        ("x-y.example.ts.net:443", "", True),
    ],
)
def test_host_is_allowed_matrix(host: str | None, allowed: str, expected: bool) -> None:
    assert host_is_allowed(host, allowed) is expected


def test_lifespan_passes_through_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup must still run: the guard only filters http and websocket scopes."""
    from backend import main

    calls: list[str] = []

    async def fake_backup_loop() -> None:
        calls.append("started")

    monkeypatch.setattr(main, "run_database_backup_loop", fake_backup_loop)
    monkeypatch.setattr(main, "run_blob_backup_loop", fake_backup_loop)
    monkeypatch.setattr(main, "run_purge_loop", lambda *_: fake_backup_loop())
    with TestClient(app):
        pass
    assert calls == ["started", "started", "started"]
