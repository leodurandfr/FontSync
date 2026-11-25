"""Comptes : premier admin, connexion, jetons d'appareil, rôles, invitations.

Chaque test part d'une instance sans aucun compte (nouvelle installation).
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

ADMIN = {"email": "Admin@Example.org", "password": "correct horse battery"}
MEMBER_PASSWORD = "member password 1"
ORIGIN = {"Origin": "http://test"}


@pytest_asyncio.fixture
async def client(
    bare_api_client: AsyncClient,
) -> AsyncGenerator[AsyncClient, None]:
    """Nouvelle installation : aucun compte."""
    login_rate_limiter.clear()
    yield bare_api_client
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
    """Crée un lien (session admin du `client`) ; l'invité l'ouvre dans un client
    neuf et y saisit `email`."""
    resp = await client.post("/api/invitations", json={}, headers=ORIGIN)
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    member = AsyncClient(transport=client._transport, base_url="http://test")
    info = await member.post("/api/auth/invitations/lookup", json={"token": token})
    assert info.json() == {"email": None, "role": "member"}
    resp = await member.post(
        "/api/auth/invitations/accept",
        json={"token": token, "email": email, "password": MEMBER_PASSWORD},
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
    assert set(status) == {"setupRequired", "me"}
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


# ---------- Serveur installé avant les comptes ----------


async def _orphan_device(name: str) -> str:
    """Un Mac enregistré avant les comptes : sans propriétaire."""
    async for db in app.dependency_overrides[get_db]():
        device = Device(name=name, hostname=name, os="macos")
        db.add(device)
        await db.commit()
        return str(device.id)
    raise AssertionError("no database")


@pytest.mark.asyncio
async def test_existing_install_setup_adopts_devices_without_any_token(
    client: AsyncClient,
) -> None:
    """Serveur déjà installé : la création de l'admin ne demande rien d'autre
    qu'un email et un mot de passe, et l'admin récupère les Mac existants."""
    device_id = await _orphan_device("old-mac")
    assert (await client.get("/api/auth/status")).json()["setupRequired"] is True
    await _setup(client)
    devices = (await client.get("/api/devices")).json()
    assert [d["id"] for d in devices] == [device_id]


@pytest.mark.asyncio
async def test_device_login_keeps_the_existing_device_id(
    client: AsyncClient,
) -> None:
    device_id = await _orphan_device("old-mac")
    await _setup(client)
    token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    again = await _register(client, token, "old-mac.local", deviceId=device_id)
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
        json={},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403
    same = await client.post("/api/invitations", json={}, headers=ORIGIN)
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
    resp = await client.post("/api/invitations", json={}, headers=ORIGIN)
    token = resp.json()["token"]
    first = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "email": "m@x.y", "password": MEMBER_PASSWORD},
    )
    assert first.status_code == 201
    again = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "email": "n@x.y", "password": MEMBER_PASSWORD},
    )
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_invitation_needs_a_free_email(client: AsyncClient) -> None:
    """Le lien ne fixe pas l'adresse : l'invité la saisit, et elle doit être libre."""
    await _setup(client)
    token = (await client.post("/api/invitations", json={}, headers=ORIGIN)).json()[
        "token"
    ]
    missing = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": MEMBER_PASSWORD},
    )
    assert missing.status_code == 422
    taken = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "email": ADMIN["email"], "password": MEMBER_PASSWORD},
    )
    assert taken.status_code == 409
    ok = await client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "email": "M@X.y", "password": MEMBER_PASSWORD},
    )
    assert ok.status_code == 201
    assert ok.json()["user"]["email"] == "m@x.y"


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


@pytest.mark.asyncio
async def test_admin_creates_an_account_directly(client: AsyncClient) -> None:
    await _setup(client)
    resp = await client.post(
        "/api/users",
        json={"email": "Direct@Example.org", "password": "given by admin"},
        headers=ORIGIN,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "member"
    dup = await client.post(
        "/api/users",
        json={"email": "direct@example.org", "password": "given by admin"},
        headers=ORIGIN,
    )
    assert dup.status_code == 409
    login = await client.post(
        "/api/auth/login",
        json={"email": "direct@example.org", "password": "given by admin"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_only_the_admin_trashes_and_restores(
    client: AsyncClient, font_factory
) -> None:
    await _setup(client)
    upload = await client.post(
        "/api/fonts/upload",
        files={"files": ("Shared.ttf", font_factory(family="Shared"), "font/ttf")},
        headers=ORIGIN,
    )
    assert upload.status_code == 200, upload.text
    font_id = upload.json()["imported"][0]["id"]

    async with aclosing(await _invite_member(client, "m@example.org")) as member:
        trash = await member.delete(f"/api/fonts/{font_id}", headers=ORIGIN)
        assert trash.status_code == 403
        dupes = await member.post(
            "/api/fonts/duplicates/resolve", json={"groups": []}, headers=ORIGIN
        )
        assert dupes.status_code == 403

    assert (
        await client.delete(f"/api/fonts/{font_id}", headers=ORIGIN)
    ).status_code == 204
    restore = await client.post(f"/api/fonts/{font_id}/restore", headers=ORIGIN)
    assert restore.status_code == 200


async def _push_as(client: AsyncClient, token: str, device: str, data: bytes) -> dict:
    resp = await client.post(
        "/api/sync/push",
        headers=_bearer(token),
        files={"file": ("f.ttf", data, "font/ttf")},
        data={"device_id": device, "local_path": "/Users/x/Library/Fonts/f.ttf"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _delta_as(
    client: AsyncClient, token: str, device: str, hashes: list[str]
) -> dict:
    resp = await client.post(
        "/api/sync/delta",
        headers=_bearer(token),
        json={
            "deviceId": device,
            "fonts": [{"hash": h, "filename": f"{h[:8]}.ttf"} for h in hashes],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_a_deletion_on_my_mac_never_reaches_someone_else(
    client: AsyncClient, font_factory
) -> None:
    """Le membre supprime une police chez lui : seuls ses Mac sont concernés.

    Le Mac de l'admin, qui accepte pourtant les suppressions, la garde ; la
    bibliothèque partagée aussi. Et l'admin ne voit ni ne gère ce retrait.
    """
    await _setup(client)
    admin_token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    admin_mac = await _register(client, admin_token, "admin-mac")
    async with aclosing(await _invite_member(client, "m@example.org")) as member:
        # Un jeton par Mac : un jeton d'appareil est lié à un seul appareil.
        member_token = await _device_token(client, "m@example.org", MEMBER_PASSWORD)
        mini_token = await _device_token(client, "m@example.org", MEMBER_PASSWORD)
        member_mac = await _register(client, member_token, "member-mac")
        member_mini = await _register(client, mini_token, "member-mini")
        for token, device in ((mini_token, member_mini), (admin_token, admin_mac)):
            resp = await client.patch(
                f"/api/devices/{device}",
                headers=_bearer(token),
                json={"propagateDeletions": True},
            )
            assert resp.status_code == 200, resp.text

        gone = await _push_as(
            client, member_token, member_mac, font_factory(family="Gone")
        )
        kept = await _push_as(
            client, member_token, member_mac, font_factory(family="Kept")
        )
        both = [gone["fileHash"], kept["fileHash"]]
        await _delta_as(client, admin_token, admin_mac, both)
        await _delta_as(client, mini_token, member_mini, both)

        # Le membre la supprime sur son Mac.
        await _delta_as(client, member_token, member_mac, [kept["fileHash"]])

        mini = await _delta_as(client, mini_token, member_mini, both)
        assert [r["fileHash"] for r in mini["toUninstall"]] == [gone["fileHash"]]
        admin = await _delta_as(client, admin_token, admin_mac, both)
        assert admin["toUninstall"] == []

        mine = (await member.get("/api/me/removals")).json()
        assert [r["fontId"] for r in mine] == [gone["fontId"]]

    assert (await client.get("/api/me/removals")).json() == []
    assert (
        await client.delete(f"/api/me/removals/{gone['fontId']}", headers=ORIGIN)
    ).status_code == 404
    library = (await client.get("/api/fonts")).json()
    assert library["total"] == 2


# ---------- Maintenance (restauration) ----------


@pytest.mark.asyncio
async def test_maintenance_refuses_macs_but_not_the_web(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pendant une restauration, les Mac attendent (503) ; l'admin audite dans
    l'interface avec son compte."""
    await _setup(client)
    token = await _device_token(client, ADMIN["email"], ADMIN["password"])
    monkeypatch.setattr(settings, "fontsync_maintenance", True)

    assert (await client.get("/health")).json()["maintenance"] is True
    assert (await client.get("/api/stats", headers=_bearer(token))).status_code == 503
    relogin = await client.post(
        "/api/auth/device-login",
        json={"email": ADMIN["email"], "password": ADMIN["password"]},
    )
    assert relogin.status_code == 503
    assert (await client.get("/api/stats")).status_code == 200  # cookie web

    monkeypatch.setattr(settings, "fontsync_maintenance", False)
    assert (await client.get("/api/stats", headers=_bearer(token))).status_code == 200
