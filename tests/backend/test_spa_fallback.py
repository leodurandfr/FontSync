"""SPA fallback: only known root files of `dist` are served, never a path built from the URL.

Each test mounts the frontend on a fresh FastAPI app over a temporary `dist`
(`index.html`, `vite.svg`, `assets/app.js`) next to a canary file that lives
OUTSIDE `dist`: no request may ever return the canary's content.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

CANARY = "CANARY-outside-dist-6f1c"
INDEX_HTML = "<!doctype html><title>FontSync test index</title>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """`tmp/site/dist` plus canaries outside `dist`.

    Canaries sit in `tmp/site` and `tmp`, some named like root files of `dist`
    (`vite.svg`, `index.html`), and in a sibling directory `site/dist-evil`
    whose name shares `dist` as a string prefix.
    """
    site = tmp_path / "site"
    dist_dir = site / "dist"
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist_dir / "vite.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
    )
    (dist_dir / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (site / "secret.txt").write_text(CANARY, encoding="utf-8")
    (tmp_path / "secret.txt").write_text(CANARY, encoding="utf-8")
    (site / "vite.svg").write_text(CANARY, encoding="utf-8")
    (site / "index.html").write_text(CANARY, encoding="utf-8")
    (site / "dist-evil").mkdir()
    (site / "dist-evil" / "x.txt").write_text(CANARY, encoding="utf-8")
    return dist_dir


@pytest.fixture
def client(dist: Path) -> Iterator[TestClient]:
    from backend.main import mount_frontend

    app = FastAPI()
    mount_frontend(app, dist)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    [
        "/..%2fsecret.txt",
        "/..%2fvite.svg",
        "/..%2findex.html",
        "/%2e%2e/vite.svg",
        "/..%2fdist-evil%2fx.txt",
        "/%2e%2e/secret.txt",
        "/%2e%2e%2fsecret.txt",
        "/..%2f..%2fsecret.txt",
        "/..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd",
        "/assets/..%2f..%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/%2fetc%2fpasswd",
        "//etc/passwd",
    ],
)
def test_traversal_never_serves_a_file_outside_dist(
    client: TestClient, path: str
) -> None:
    response = client.get(path)
    assert CANARY not in response.text
    assert "root:" not in response.text
    if response.status_code == 200:
        assert response.text in (INDEX_HTML, "console.log(1)")


async def _raw_asgi_get(app: FastAPI, raw_path: str) -> tuple[int, bytes]:
    """Call the ASGI app with an un-normalised path (httpx would fold `..`)."""
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": raw_path,
        "raw_path": raw_path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    return int(status), body  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_path",
    [
        "/../secret.txt",
        "/../vite.svg",
        "/../dist-evil/x.txt",
        "/../../secret.txt",
        "/assets/../../secret.txt",
    ],
)
async def test_raw_dotdot_path_never_serves_canary(dist: Path, raw_path: str) -> None:
    from backend.main import mount_frontend

    app = FastAPI()
    mount_frontend(app, dist)
    _status, body = await _raw_asgi_get(app, raw_path)
    assert CANARY.encode() not in body


def test_known_root_file_is_served(client: TestClient) -> None:
    response = client.get("/vite.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "no-cache"


def test_client_route_gets_index(client: TestClient) -> None:
    response = client.get("/settings/devices")
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    for path in ("/api", "/api/nope"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


def test_assets_are_immutable(client: TestClient) -> None:
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_file_added_after_mount_is_not_served(client: TestClient, dist: Path) -> None:
    """The set of root files is frozen at mount time."""
    (dist / "late.txt").write_text(CANARY, encoding="utf-8")
    response = client.get("/late.txt")
    assert CANARY not in response.text
    assert response.text == INDEX_HTML


def test_symlink_in_dist_is_not_served(dist: Path) -> None:
    from backend.main import mount_frontend

    (dist / "evil").symlink_to(dist.parent / "secret.txt")
    app = FastAPI()
    mount_frontend(app, dist)
    with TestClient(app) as test_client:
        response = test_client.get("/evil")
    assert CANARY not in response.text
    assert response.text == INDEX_HTML


def test_real_app_has_a_single_catch_all_from_mount_frontend() -> None:
    from backend import main

    if not main.FRONTEND_DIR.is_dir():
        pytest.skip("frontend/dist absent (npm run build): no SPA route mounted")
    catch_all = [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/{full_path:path}"
    ]
    assert len(catch_all) == 1
    endpoint = catch_all[0].endpoint  # type: ignore[attr-defined]
    assert endpoint.__qualname__.startswith("mount_frontend.")


@pytest.mark.parametrize(
    "path",
    [
        "/..%2fbackend%2fmain.py",
        "/..%2f..%2fbackend%2fmain.py",
        "/%2e%2e/%2e%2e/backend/main.py",
        "/..%2f..%2fpyproject.toml",
    ],
)
def test_real_app_never_serves_repository_files(path: str) -> None:
    """Behavioural check on the real app: dist sits in `frontend/`, the code next to it."""
    from backend import main

    if not main.FRONTEND_DIR.is_dir():
        pytest.skip("frontend/dist absent (npm run build): no SPA route mounted")
    # No `with`: the app's lifespan (purge/backup loops) is not needed here.
    response = TestClient(main.app).get(path)
    assert "mount_frontend" not in response.text
    assert "[tool.ruff]" not in response.text
    index = (main.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert response.text == index
