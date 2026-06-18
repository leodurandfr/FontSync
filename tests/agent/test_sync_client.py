"""Tests du client HTTP `SyncClient` (B6 — HTTP propre).

On pilote le client avec un `httpx.MockTransport` injecté : aucune connexion
réseau réelle. On vérifie la configuration du client (base_url, en-têtes,
timeouts), la lecture **camelCase** des réponses, le découpage du
`Content-Disposition`, et la politique de réessai sur erreurs transitoires.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Le client réel s'appuie sur `httpx` (et son `MockTransport`) : ces tests sont
# sautés si la dépendance n'est pas installée, comme le reste de la suite agent
# qui reste exécutable sans httpx.
httpx = pytest.importorskip("httpx")

from agent.config import AGENT_VERSION, AgentConfig  # noqa: E402
from agent.hashing import ScannedFont  # noqa: E402
from agent.sync_client import (  # noqa: E402
    MAX_ATTEMPTS,
    SyncClient,
    SyncClientError,
    _filename_from_disposition,
)


def _config() -> AgentConfig:
    return AgentConfig(server_url="http://nas.local:8080/")


def _client(handler, *, sleep=lambda _d: None) -> SyncClient:
    """Construit un SyncClient branché sur un MockTransport pilotant `handler`."""
    return SyncClient(
        _config(),
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )


def _font(tmp_path: Path, name: str, content: bytes, file_hash: str) -> ScannedFont:
    path = tmp_path / name
    path.write_bytes(content)
    return ScannedFont(
        path=path, filename=name, file_hash=file_hash, file_size=len(content)
    )


# ---- Configuration du client ----


def test_client_configured_with_base_url_and_default_headers() -> None:
    client = _client(lambda req: httpx.Response(200, json={}))
    try:
        assert str(client._client.base_url) == "http://nas.local:8080"
        headers = client._client.headers
        assert headers["user-agent"] == f"fontsync-agent/{AGENT_VERSION}"
        assert headers["accept"] == "application/json"
        # Sans token configuré (cf. `_config`), pas d'en-tête d'auth.
        assert "authorization" not in headers
    finally:
        client.close()


def test_client_sets_bearer_header_when_token_present() -> None:
    """P1.3 : le token partagé d'instance part en `Authorization: Bearer`."""
    config = AgentConfig(server_url="http://nas.local:8080/", server_token="sek-1")
    client = SyncClient(
        config, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    try:
        assert client._client.headers["authorization"] == "Bearer sek-1"
    finally:
        client.close()


def test_bearer_header_is_sent_on_each_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(201, json={"id": "dev-1", "name": "Mac"})

    config = AgentConfig(server_url="http://nas.local:8080/", server_token="sek-2")
    client = SyncClient(
        config, sleep=lambda _d: None, transport=httpx.MockTransport(handler)
    )
    try:
        client.register_device()
    finally:
        client.close()

    assert seen["auth"] == "Bearer sek-2"


# ---- register / delta ----


def test_register_device_posts_payload_and_returns_json() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={"id": "dev-1", "name": "Mac", "autoPull": True, "autoPush": False},
        )

    with _client(handler) as client:
        data = client.register_device()

    assert seen["url"] == "http://nas.local:8080/api/devices/register"
    assert seen["method"] == "POST"
    assert seen["body"]["os"] == "macos"  # type: ignore[index]
    assert data["id"] == "dev-1"
    assert data["autoPull"] is True


def test_delta_sync_builds_camelcase_entries() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "unknownToServer": ["h1"],
                "missingOnDevice": [],
                "alreadySynced": 2,
            },
        )

    font = ScannedFont(
        path=Path("/fonts/Inter.ttf"),
        filename="Inter.ttf",
        file_hash="h1",
        file_size=10,
    )
    with _client(handler) as client:
        delta = client.delta_sync("dev-1", [font])

    body = captured["body"]
    assert body["device_id"] == "dev-1"  # type: ignore[index]
    entry = body["fonts"][0]  # type: ignore[index]
    assert entry["hash"] == "h1"
    assert entry["filename"] == "Inter.ttf"
    assert entry["localPath"] == "/fonts/Inter.ttf"
    assert delta["alreadySynced"] == 2


# ---- push ----


def test_push_font_reads_camelcase_keys(tmp_path: Path) -> None:
    font = _font(tmp_path, "A.ttf", b"data", "hashA")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/sync/push"
        return httpx.Response(
            200,
            json={
                "fontId": "f-1",
                "fileHash": "hashA",
                "isDuplicate": False,
                "familyName": "A",
            },
        )

    with _client(handler) as client:
        result = client.push_font("dev-1", font)

    assert result["fontId"] == "f-1"
    assert result["isDuplicate"] is False


def test_push_fonts_dedups_and_counts(tmp_path: Path) -> None:
    f1 = _font(tmp_path, "A.ttf", b"a", "hashA")
    f1bis = _font(tmp_path, "A-copy.ttf", b"a", "hashA")  # même hash → dédupe local
    f2 = _font(tmp_path, "B.ttf", b"b", "hashB")

    def handler(request: httpx.Request) -> httpx.Response:
        # hashB renvoyé comme doublon serveur ; hashA comme nouveau.
        body = request.content
        is_b = b"B.ttf" in body
        return httpx.Response(
            200,
            json={
                "fontId": "x",
                "fileHash": "h",
                "isDuplicate": is_b,
            },
        )

    with _client(handler) as client:
        pushed, duplicates, errors = client.push_fonts(
            "dev-1", [f1, f1bis, f2], {"hashA", "hashB"}
        )

    assert (pushed, duplicates, errors) == (1, 1, 0)


def test_push_fonts_counts_http_error(tmp_path: Path) -> None:
    font = _font(tmp_path, "A.ttf", b"a", "hashA")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "bad"})

    with _client(handler) as client:
        pushed, duplicates, errors = client.push_fonts("dev-1", [font], {"hashA"})

    assert (pushed, duplicates, errors) == (0, 0, 1)


# ---- pull ----


def test_pull_font_parses_rfc5987_filename() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("device_id") == "dev-1"
        return httpx.Response(
            200,
            content=b"FONTBYTES",
            headers={
                "content-disposition": "attachment; filename*=UTF-8''Inter%20Bold.ttf"
            },
        )

    with _client(handler) as client:
        filename, data = client.pull_font("f-1", "dev-1")

    assert filename == "Inter Bold.ttf"
    assert data == b"FONTBYTES"


@pytest.mark.parametrize(
    "header,expected",
    [
        ('attachment; filename="Roboto.otf"', "Roboto.otf"),
        ("attachment; filename*=UTF-8''Caf%C3%A9.ttf", "Café.ttf"),
        ("", "unknown.ttf"),
    ],
)
def test_filename_from_disposition(header: str, expected: str) -> None:
    assert _filename_from_disposition(header) == expected


# ---- réessais ----


def test_transient_error_is_retried_then_succeeds() -> None:
    calls = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(201, json={"id": "dev-1", "name": "Mac"})

    client = _client(handler, sleep=slept.append)
    try:
        data = client.register_device()
    finally:
        client.close()

    assert calls["n"] == 2
    assert data["id"] == "dev-1"
    assert slept == [pytest.approx(1.0)]


def test_transient_error_exhausts_retries_and_raises() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("nope", request=request)

    client = _client(handler)
    try:
        with pytest.raises(SyncClientError):
            client.register_device()
    finally:
        client.close()

    assert calls["n"] == MAX_ATTEMPTS


def test_http_status_error_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"detail": "Device non trouvé."})

    client = _client(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.delta_sync_hashes("dev-1", [])
    finally:
        client.close()

    assert calls["n"] == 1
