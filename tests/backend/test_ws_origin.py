"""Origin au handshake /ws/client et retrait de la voie cookie (P1-5f, B-158, B-54).

Le navigateur pose `Origin` sur tout handshake WebSocket, sans que la page
puisse le falsifier. Sans contrôle, une page d'un autre site pouvait ouvrir le
WebSocket de FontSync avec ce que le navigateur y joint d'office (un cookie) :
la voie cookie est retirée, et un `Origin` étranger est refusé (1008) même
avec un bon token. `Origin` absent (client hors navigateur) : le token suffit.
"""

from __future__ import annotations

import time

import pytest
from fastapi import WebSocketDisconnect
from starlette.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.routers import agent_events
from backend.routers import ws as ws_router
from backend.services.ws_manager import WebSocketManager
from tests.backend.conftest import API_TOKEN as TOKEN

WS = f"/ws/client?token={TOKEN}"
LOCAL = "http://localhost:8080"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch, auth_db: object) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", "")
    if hasattr(settings, "allowed_origins"):
        monkeypatch.setattr(settings, "allowed_origins", "")
    # Un manager neuf par test (cf. test_auth.py : files et tâches liées à une boucle).
    mgr = WebSocketManager()
    monkeypatch.setattr(agent_events, "ws_manager", mgr)
    monkeypatch.setattr(ws_router, "ws_manager", mgr)


def ws_url(base: str, url: str = WS) -> str:
    """URL absolue : seul moyen de fixer le Host d'un handshake du TestClient
    (il ignore base_url pour le WebSocket et enverrait « testserver »)."""
    return base.replace("http", "ws", 1) + url


def connect(
    base: str, url: str = WS, client: TestClient | None = None, **headers: str
) -> None:
    client = client or TestClient(app)
    with client.websocket_connect(ws_url(base, url), headers=headers) as ws:
        ws.close()


def refused(
    base: str, url: str = WS, client: TestClient | None = None, **headers: str
) -> int:
    # Le TestClient ne lève à la connexion que si le serveur ferme AVANT
    # accept() : un refus après accept() ferait échouer `pytest.raises`.
    client = client or TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(ws_url(base, url), headers=headers):
            pass
    return exc.value.code


# ---- Origin ----


def test_ws_rejects_foreign_origin() -> None:
    assert refused(LOCAL, origin="https://evil.example") == 1008


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://localhost:5000",  # même hôte, autre port (DSM, autre service)
        "https://localhost",  # autre port implicite (443 ≠ 8080)
        "https://other-tailnet.ts.net",  # défauts de la garde Host : pas des origines
        "http://198.51.100.50:8080",
        "ftp://localhost:8080",
        "http://localhost:8080.evil.example",
        "http://localhost:8080@evil.example",  # infra-leak: allow (userinfo, pas un e-mail)
        "not a url",
    ],
)
def test_ws_rejects_other_origins(origin: str) -> None:
    assert refused(LOCAL, origin=origin) == 1008


@pytest.mark.parametrize(
    ("base", "origin"),
    [
        (LOCAL, "http://localhost:8080"),
        (LOCAL, "HTTP://LOCALHOST:8080"),
        # Proxy TLS (Tailscale Serve, DSM) : Host sans port, page en https.
        ("http://fontsync.example.ts.net", "https://fontsync.example.ts.net"),
        ("http://192.0.2.140:8070", "http://192.0.2.140:8070"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        # Proxy Vite (`/ws` sans changeOrigin) : Host et Origin = le serveur de dev.
        ("http://localhost:5173", "http://localhost:5173"),
    ],
)
def test_ws_accepts_same_origin(base: str, origin: str) -> None:
    connect(base, origin=origin)


def test_ws_hostname_without_port_does_not_accept_any_port() -> None:
    """Host sans port (proxy TLS) = port par défaut du schéma, pas « tout port »."""
    base = "http://fontsync.example.ts.net"
    assert refused(base, origin="https://fontsync.example.ts.net:8443") == 1008
    assert refused(base, origin="http://fontsync.example.ts.net:8080") == 1008


@pytest.mark.parametrize("port", ["0", "65536", "99999"])
def test_ws_rejects_impossible_ports(port: str) -> None:
    assert (
        refused(f"http://localhost:{port}", origin=f"http://localhost:{port}") == 1008
    )


@pytest.mark.asyncio
async def test_ws_rejects_duplicate_origin_headers() -> None:
    """Deux en-têtes Origin (même identiques) : refus. ASGI brut, le TestClient
    ne sait pas en envoyer deux."""
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws/client",
        "raw_path": b"/ws/client",
        "root_path": "",
        "query_string": f"token={TOKEN}".encode(),
        "headers": [
            (b"host", b"localhost:8080"),
            (b"origin", b"http://localhost:8080"),
            (b"origin", b"http://localhost:8080"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8080),
        "subprotocols": [],
    }
    await app(scope, receive, send)
    assert sent and sent[0]["type"] == "websocket.close"
    assert sent[0]["code"] == 1008


def test_ws_origin_refusal_is_logged_without_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="backend.routers.ws"):
        refused(LOCAL, origin="https://evil.example")
    (record,) = [r for r in caplog.records if "WebSocket refusé" in r.getMessage()]
    assert "https://evil.example" in record.getMessage()
    assert "localhost:8080" in record.getMessage()
    assert TOKEN not in record.getMessage()


def test_ws_accepts_without_origin() -> None:
    """Client hors navigateur (pas d'Origin) : le token suffit."""
    connect(LOCAL)


def test_ws_accepts_origin_listed_in_allowed_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxy qui réécrit Host : l'hôte public déclaré dans ALLOWED_HOSTS passe."""
    monkeypatch.setattr(settings, "allowed_hosts", "fontsync.example.com")
    connect(LOCAL, origin="https://fontsync.example.com")
    assert refused(LOCAL, origin="https://evil.example") == 1008


def test_ws_wildcard_allowed_hosts_does_not_open_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ALLOWED_HOSTS=*` coupe la garde Host, pas le contrôle d'Origin."""
    monkeypatch.setattr(settings, "allowed_hosts", "*")
    connect(LOCAL, origin="http://localhost:8080")
    assert refused(LOCAL, origin="https://evil.example") == 1008


def test_ws_accepts_origin_listed_in_allowed_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "allowed_origins", "https://app.example:8443")
    connect(LOCAL, origin="https://app.example:8443")
    assert refused(LOCAL, origin="https://app.example") == 1008


# ---- Cookie ----


def test_ws_rejects_cookie_only() -> None:
    """L'ancien cookie `fontsync_token` n'ouvre rien : seul le cookie de session
    (posé par la connexion) identifie un navigateur."""
    client = TestClient(app)
    client.cookies.set("fontsync_token", TOKEN)
    assert refused(LOCAL, "/ws/client", client=client) == 1008


def test_ws_query_token_still_accepted_with_a_cookie() -> None:
    client = TestClient(app)
    client.cookies.set("fontsync_session", "whatever")
    connect(LOCAL, client=client)


def test_ws_header_token_still_accepted() -> None:
    connect(LOCAL, "/ws/client", authorization=f"Bearer {TOKEN}")


# ---- Route /ws/client et gestionnaire (P1-7a) ----


def test_ws_route_sends_initial_presence_then_unregisters() -> None:
    """La présence initiale passe par la file du client ; à la fermeture, le
    client est retiré du gestionnaire (`finally: disconnect`)."""
    mgr = ws_router.ws_manager
    mgr._sse_subscribers["dev-1"] = set()  # un agent `listen` connecté
    with TestClient(app).websocket_connect(ws_url(LOCAL)) as ws:
        assert ws.receive_json() == {
            "type": "device.connected",
            "data": {"deviceId": "dev-1"},
        }
        assert mgr.client_count == 1
    for _ in range(100):
        if mgr.client_count == 0:
            break

        time.sleep(0.01)
    assert mgr.client_count == 0
