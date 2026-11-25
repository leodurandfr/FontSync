"""Comptes : premier admin, connexion, jetons d'appareil, rôles, invitations.

Chaque test part d'une instance SANS token hérité (nouvelle installation),
sauf ceux qui vérifient la migration depuis `FONTSYNC_TOKEN`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from starlette.testclient import TestClient

from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models.device import Device
from backend.services import accounts
from backend.services.accounts import login_rate_limiter
from tests.backend.conftest import API_TOKEN

ADMIN = {"email": "Admin@Example.org", "password": "correct horse battery"}
MEMBER_PASSWORD = "member password 1"
ORIGIN = {"Origin": "http://test"}


@pytest_asyncio.fixture
async def client(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """`api_client` sur une nouvelle installation : pas de `FONTSYNC_TOKEN`."""
    monkeypatch.setattr(settings, "fontsync_token", "")
    login_rate_limiter.clear()
    yield api_client
    login_rate_limiter.clear()


async def _setup(client: AsyncClient) -> dict:
    resp = await client.post("/api/auth/setup", json=ADMIN)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _device_token(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/auth/device-login",
        json={"email": email, "password": password, "deviceName": "Mac"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, token: str, hostname: str, **extra) -> str:
    resp = await client.post(
        "/api/devices/register",
        headers=_bearer(token),
        json={"name": hostname, "hostname": hostname, "os": "macos", **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _invite_member(client: AsyncClient, email: str) -> AsyncClient:
    """Invite `email` (session admin du `client`), et l'accepte dans un client neuf."""
    resp = await client.post(
        "/api/invitations", json={"email": email, "role": "member"}, headers=ORIGIN
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    member = AsyncClient(transport=client._transport, base_url="http://test")
    info = await member.post("/api/auth/invitations/lookup", json={"token": token})
    assert info.json() == {"email": email.lower(), "role": "member"}
    resp = await member.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": MEMBER_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    return member


# ---------- Premier lancement ----------


@pytest.mark.asyncio
async def test_fresh_install_requires_setup_and_nothing_else_is_open(
    client: AsyncClient,
) -> None:
    status = (await client.get("/api/auth/status")).json()
    assert status["setupRequired"] is True
    assert status["setupNeedsLegacyToken"] is False
    assert status["legacyTokenEnabled"] is False
    assert (await client.get("/api/stats")).status_code == 401


@pytest.mark.asyncio
async def test_setup_creates_admin_logs_in_and_closes(client: AsyncClient) -> None:
    me = await _setup(client)
    assert me["user"]["email"] == "admin@example.org"
    assert me["role"] == "admin"
    cookie = client.cookies.get("fontsync_session")
    assert cookie
    assert (await client.get("/api/stats")).status_code == 200
    status = (await client.get("/api/auth/status")).json()
    assert status["setupRequired"] is False
    assert status["me"]["user"]["email"] == "admin@example.org"

    again = await client.post(
        "/api/auth/setup", json={"email": "x@y.z", "password": "another password"}
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_setup_rejects_short_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/setup", json={"email": "a@b.c", "password": "short"}
    )
    assert resp.status_code == 422


# ---------- Migration depuis FONTSYNC_TOKEN ----------


@pytest.mark.asyncio
async def test_existing_install_setup_needs_the_legacy_token_and_adopts_devices(
    api_client: AsyncClient,
) -> None:
    """Serveur déjà installé : les Mac existants continuent avec le token, le
    premier admin doit prouver qu'il le connaît, et récupère les appareils."""
    legacy = _bearer(API_TOKEN)
    device_id = await _register(api_client, API_TOKEN, "old-mac")

    status = (await api_client.get("/api/auth/status")).json()
    assert status["setupNeedsLegacyToken"] is True
    assert (await api_client.post("/api/auth/setup", json=ADMIN)).status_code == 403

    resp = await api_client.post(
        "/api/auth/setup", json={**ADMIN, "legacyToken": API_TOKEN}
    )
    assert resp.status_code == 201, resp.text

    # Le token hérité marche toujours, avec les droits admin.
    assert (await api_client.get("/api/users", headers=legacy)).status_code == 200
    devices = (await api_client.get("/api/devices")).json()
    assert [d["id"] for d in devices] == [device_id]


@pytest.mark.asyncio
async def test_device_login_keeps_the_existing_device_id(
    api_client: AsyncClient,
) -> None:
    device_id = await _register(api_client, API_TOKEN, "old-mac")
    await api_client.post("/api/auth/setup", json={**ADMIN, "legacyToken": API_TOKEN})
    token = await _device_token(api_client, ADMIN["email"], ADMIN["password"])
    again = await _register(api_client, token, "old-mac.local", deviceId=device_id)
    assert again == device_id


# ---------- Connexion ----------


@pytest.mark.asyncio
async def test_login_logout_and_wrong_password(client: AsyncClient) -> None:
    await _setup(client)
    client.cookies.clear()
    assert (await client.get("/api/stats")).status_code == 401

    bad = await client.post(
        "/api/auth/login", json={"email": ADMIN["email"], "password": "nope"}
    )
    assert bad.status_code == 401
    unknown = await client.post(
        "/api/auth/login", json={"email": "who@x.y", "password": "nope"}
    )
    assert unknown.status_code == 401
    assert bad.json() == unknown.json()

    ok = await client.post("/api/auth/login", json=ADMIN)
    assert ok.status_code == 200
    cookie = client.cookies.get("fontsync_session")
    assert (await client.get("/api/stats")).status_code == 200

    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set("fontsync_session", cookie)
    assert (await client.get("/api/stats")).status_code == 401


@pytest.mark.asyncio
async def test_login_is_rate_limited(client: AsyncClient) -> None:
    await _setup(client)
    for _ in range(5):
        resp = await client.post(
            "/api/auth/login", json={"email": ADMIN["email"], "password": "nope"}
        )
        assert resp.status_code == 401
    blocked = await client.post("/api/auth/login", json=ADMIN)
    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_cookie_write_from_a_foreign_origin_is_refused(
    client: AsyncClient,
) -> None:
    await _setup(client)
    resp = await client.post(
        "/api/invitations",
        json={"email": "m@x.y"},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403
    same = await client.post(
        "/api/invitations", json={"email": "m@x.y"}, headers=ORIGIN
    )
    assert same.status_code == 201


@pytest.mark.asyncio
async def test_changing_password_revokes_other_sessions(client: AsyncClient) -> None:
    await _setup(client)
    token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    resp = await client.post(
        "/api/auth/me/password",
        json={
            "currentPassword": ADMIN["password"],
            "newPassword": "brand new password",
        },
        headers=ORIGIN,
    )
    assert resp.status_code == 204
    assert (await client.get("/api/stats")).status_code == 200  # session courante
    assert (await client.get("/api/stats", headers=_bearer(token))).status_code == 401


# ---------- Jetons d'appareil ----------


@pytest.mark.asyncio
async def test_one_account_on_several_macs(client: AsyncClient) -> None:
    await _setup(client)
    t1 = await _device_token(client, ADMIN["email"], ADMIN["password"])
    t2 = await _device_token(client, ADMIN["email"], ADMIN["password"])
    assert t1 != t2
    d1 = await _register(client, t1, "mac-1")
    d2 = await _register(client, t2, "mac-2")
    assert d1 != d2

    sessions = (await client.get("/api/auth/sessions")).json()
    devices = {s["deviceId"] for s in sessions if s["kind"] == "device"}
    assert devices == {d1, d2}

    # Révoquer un Mac ne coupe pas l'autre.
    s1 = next(s["id"] for s in sessions if s["deviceId"] == d1)
    assert (
        await client.delete(f"/api/auth/sessions/{s1}", headers=ORIGIN)
    ).status_code == 204
    assert (await client.get("/api/stats", headers=_bearer(t1))).status_code == 401
    assert (await client.get("/api/stats", headers=_bearer(t2))).status_code == 200


@pytest.mark.asyncio
async def test_device_token_only_acts_for_its_own_device(client: AsyncClient) -> None:
    await _setup(client)
    t1 = await _device_token(client, ADMIN["email"], ADMIN["password"])
    t2 = await _device_token(client, ADMIN["email"], ADMIN["password"])
    d1 = await _register(client, t1, "mac-1")
    d2 = await _register(client, t2, "mac-2")

    own = await client.post(
        "/api/sync/delta", headers=_bearer(t1), json={"deviceId": d1, "fonts": []}
    )
    assert own.status_code == 200, own.text
    other = await client.post(
        "/api/sync/delta", headers=_bearer(t1), json={"deviceId": d2, "fonts": []}
    )
    assert other.status_code == 403

    # Un jeton lié ne peut pas se ré-enregistrer comme un autre appareil.
    assert await _register(client, t1, "mac-2", deviceId=d2) == d1


@pytest.mark.asyncio
async def test_device_token_of_an_admin_has_no_admin_rights(
    client: AsyncClient,
) -> None:
    await _setup(client)
    token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    assert (await client.get("/api/users", headers=_bearer(token))).status_code == 403
    resp = await client.post("/api/fonts/trash/empty", headers=_bearer(token))
    assert resp.status_code == 403


# ---------- Membres et rôles ----------


@pytest.mark.asyncio
async def test_member_sees_only_own_devices_and_no_admin_routes(
    client: AsyncClient,
) -> None:
    await _setup(client)
    admin_token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    admin_device = await _register(client, admin_token, "admin-mac")

    async with aclosing(await _invite_member(client, "Member@Example.org")) as member:
        token = await _device_token(member, "member@example.org", MEMBER_PASSWORD)
        member_device = await _register(member, token, "member-mac")

        listed = (await member.get("/api/devices")).json()
        assert [d["id"] for d in listed] == [member_device]
        assert (
            await member.get("/api/fonts")
        ).status_code == 200  # bibliothèque partagée

        patch = await member.patch(
            f"/api/devices/{admin_device}", json={"autoPull": True}, headers=ORIGIN
        )
        assert patch.status_code == 403
        assert (await member.get("/api/users")).status_code == 403
        empty = await member.post("/api/fonts/trash/empty", headers=ORIGIN)
        assert empty.status_code == 403

        # Un membre ne reprend pas l'appareil d'un autre par son hostname.
        assert await _register(member, token, "admin-mac") == member_device

    all_devices = {d["id"] for d in (await client.get("/api/devices")).json()}
    assert all_devices == {admin_device, member_device}


@pytest.mark.asyncio
async def test_admin_disables_member_and_keeps_one_admin(client: AsyncClient) -> None:
    me = await _setup(client)
    async with aclosing(await _invite_member(client, "m@example.org")) as member:
        users = (await client.get("/api/users")).json()
        member_id = next(u["id"] for u in users if u["email"] == "m@example.org")

        resp = await client.patch(
            f"/api/users/{member_id}", json={"disabled": True}, headers=ORIGIN
        )
        assert resp.status_code == 200
        assert resp.json()["disabledAt"] is not None
        assert (await member.get("/api/stats")).status_code == 401

    self_demote = await client.patch(
        f"/api/users/{me['user']['id']}", json={"role": "member"}, headers=ORIGIN
    )
    assert self_demote.status_code == 400


@pytest.mark.asyncio
async def test_admin_resets_member_password(client: AsyncClient) -> None:
    await _setup(client)
    async with aclosing(await _invite_member(client, "m@example.org")) as member:
        users = (await client.get("/api/users")).json()
        member_id = next(u["id"] for u in users if u["email"] == "m@example.org")
        resp = await client.post(
            f"/api/users/{member_id}/password",
            json={"password": "reset by admin"},
            headers=ORIGIN,
        )
        assert resp.status_code == 204
        assert (await member.get("/api/stats")).status_code == 401
        login = await member.post(
            "/api/auth/login",
            json={"email": "m@example.org", "password": "reset by admin"},
        )
        assert login.status_code == 200


@pytest.mark.asyncio
async def test_invitation_is_single_use(client: AsyncClient) -> None:
    await _setup(client)
    resp = await client.post(
        "/api/invitations", json={"email": "m@x.y"}, headers=ORIGIN
    )
    token = resp.json()["token"]
    first = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": MEMBER_PASSWORD},
    )
    assert first.status_code == 201
    again = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": MEMBER_PASSWORD},
    )
    assert again.status_code == 404


# ---------- WebSocket et démarrage ----------


@pytest.mark.asyncio
async def test_websocket_accepts_the_session_cookie(client: AsyncClient) -> None:
    await _setup(client)
    cookie = client.cookies.get("fontsync_session")
    ws_client = TestClient(app)
    ws_client.cookies.set("fontsync_session", cookie)
    with ws_client.websocket_connect("/ws/client") as ws:
        ws.close()


@pytest.mark.asyncio
async def test_bootstrap_admin_from_env(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "fontsync_admin_email", "Boot@Example.org")
    monkeypatch.setattr(settings, "fontsync_admin_password", "from the env file")
    override = app.dependency_overrides[get_db]
    gen = override()
    db = await gen.__anext__()
    try:
        db.add(Device(name="old", hostname="old", os="macos"))
        await db.commit()
        user = await accounts.bootstrap_admin_from_env(db)
        assert user is not None and user.email == "boot@example.org"
        device = (await db.execute(select(Device))).scalar_one()
        assert device.owner_user_id == user.id
        assert await accounts.bootstrap_admin_from_env(db) is None  # une seule fois
    finally:
        await gen.aclose()
    login = await client.post(
        "/api/auth/login",
        json={"email": "boot@example.org", "password": "from the env file"},
    )
    assert login.status_code == 200
