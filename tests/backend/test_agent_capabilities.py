"""Ce que le serveur déduit et accepte selon les capacités de l'agent.

M-32 / B-112 (P1-6c) : une absence dans un delta ne prouve une suppression que si
l'agent garantit de déclarer toute sa bibliothèque (`full-declaration`). Un agent
antérieur (≤ 0.1.2) omet par exemple les polices désactivées : revenu sur un Mac,
il les ferait passer pour supprimées. Et le premier delta d'un agent capable sert
de ligne de base : le registre hérité n'est pas comparé à lui.

B-32 (P1-6d) : désactiver une police, ou activer la propagation des suppressions,
n'a de sens que si l'agent applique l'ordre. Sans la capacité, l'API refuse (409)
au lieu de promettre un effet qui n'aura pas lieu.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.database import get_db
from backend.main import app
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from tests.backend.conftest import AGENT_CAPABILITIES, AUTH_HEADERS

# Corps exacts d'un agent v0.0.1 (`git show v0.0.1:agent/sync_client.py`) :
# snake_case, sans `capabilities`, delta sans `ingestible`.
_V001_REGISTER = {
    "name": "Mac de Léo",
    "hostname": "mac-v001",
    "os": "macos",
    "os_version": "15.5",
    "agent_version": "0.0.1",
    "font_directories": ["/Users/x/Library/Fonts"],
    "auto_pull": True,
    "auto_push": True,
}


async def _register(
    client: AsyncClient, *, hostname: str = "mac", caps: bool = True, **extra
) -> str:
    payload: dict = {"name": hostname, "hostname": hostname, "os": "macos", **extra}
    if caps:
        payload["capabilities"] = list(AGENT_CAPABILITIES)
    resp = await client.post(
        "/api/devices/register", headers=AUTH_HEADERS, json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _push(client: AsyncClient, device_id: str, data: bytes, name: str) -> dict:
    resp = await client.post(
        "/api/sync/push",
        headers=AUTH_HEADERS,
        files={"file": (name, data, "font/ttf")},
        data={"device_id": device_id, "local_path": f"/Users/x/Library/Fonts/{name}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _delta(client: AsyncClient, device_id: str, hashes: list[str]) -> dict:
    resp = await client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={
            "deviceId": device_id,
            "fonts": [{"hash": h, "filename": f"{h[:8]}.ttf"} for h in hashes],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _removals(client: AsyncClient) -> list[dict]:
    resp = await client.get("/api/me/removals", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _device(device_id: str) -> Device:
    gen = app.dependency_overrides[get_db]()
    session = await gen.__anext__()
    try:
        device = await session.get(Device, uuid.UUID(device_id))
        assert device is not None
        session.expunge(device)
        return device
    finally:
        await gen.aclose()


async def _registry(device_id: str) -> set[uuid.UUID]:
    gen = app.dependency_overrides[get_db]()
    session = await gen.__anext__()
    try:
        rows = await session.execute(
            select(DeviceFont.font_id).where(
                DeviceFont.device_id == uuid.UUID(device_id)
            )
        )
        return set(rows.scalars().all())
    finally:
        await gen.aclose()


# ---------- P1-6c : déduction des suppressions ----------


@pytest.mark.asyncio
async def test_downgrade_v001_disabled_font_not_deleted(
    api_client: AsyncClient, font_factory
) -> None:
    """Une police désactivée, puis l'agent v0.0.1 revient : rien n'est retiré.

    v0.0.1 ne voit pas le dossier des polices désactivées ; son delta l'omet.
    Avant P1-6c, cette absence devenait un retrait personnel.
    """
    device_id = await _register(api_client, hostname="mac-v001")
    kept = font_factory(family="Kept")
    disabled = font_factory(family="Disabled")
    kept_hash = (await _push(api_client, device_id, kept, "Kept.ttf"))["fileHash"]
    disabled_font = await _push(api_client, device_id, disabled, "Disabled.ttf")
    await _delta(api_client, device_id, [kept_hash, disabled_font["fileHash"]])

    resp = await api_client.post(
        f"/api/fonts/{disabled_font['fontId']}/deactivate/{device_id}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    # Retour d'un agent v0.0.1 sur le même Mac.
    resp = await api_client.post(
        "/api/devices/register", headers=AUTH_HEADERS, json=_V001_REGISTER
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == device_id
    resp = await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={
            "device_id": device_id,
            "fonts": [{"hash": kept_hash, "filename": "Kept.ttf"}],
        },
    )
    assert resp.status_code == 200, resp.text

    assert await _removals(api_client) == []
    assert (await _device(device_id)).full_declaration_since is None


@pytest.mark.asyncio
async def test_delta_without_capability_writes_no_inventory(
    api_client: AsyncClient, font_factory
) -> None:
    """Sans la capacité : ni réconciliation ni avancement de la déclaration."""
    device_id = await _register(api_client, caps=False)
    data = font_factory(family="Old")
    pushed = await _push(api_client, device_id, data, "Old.ttf")

    delta = await _delta(api_client, device_id, [])
    delta = await _delta(api_client, device_id, ["0" * 64])

    assert await _removals(api_client) == []
    device = await _device(device_id)
    assert device.last_declaration_at is None
    # Le registre n'a pas été réconcilié : la police poussée y reste.
    assert await _registry(device_id) == {uuid.UUID(pushed["fontId"])}
    # Le delta reste servi.
    assert delta["unknownToServer"] == ["0" * 64]


@pytest.mark.asyncio
async def test_first_capable_declaration_is_baseline(
    api_client: AsyncClient, font_factory
) -> None:
    """Un Mac connu d'un ancien agent passe à un agent capable : son premier
    delta remplace le registre hérité, sans rien retirer."""
    device_id = await _register(api_client, caps=False)
    kept = font_factory(family="Kept")
    gone = font_factory(family="GoneBefore")
    kept_hash = (await _push(api_client, device_id, kept, "Kept.ttf"))["fileHash"]
    await _push(api_client, device_id, gone, "GoneBefore.ttf")

    await _register(api_client)  # même hostname, agent à jour
    assert (await _device(device_id)).full_declaration_since is None

    await _delta(api_client, device_id, [kept_hash])

    assert await _removals(api_client) == []
    device = await _device(device_id)
    assert device.full_declaration_since is not None
    assert device.last_declaration_at == device.full_declaration_since
    # Le registre est devenu le miroir de la déclaration : la police absente
    # n'est pas jugée au delta suivant non plus.
    assert len(await _registry(device_id)) == 1
    await _delta(api_client, device_id, [kept_hash])
    assert await _removals(api_client) == []


@pytest.mark.asyncio
async def test_second_capable_delta_detects_normally(
    api_client: AsyncClient, font_factory
) -> None:
    """Après la ligne de base, une absence redevient une suppression."""
    device_id = await _register(api_client, caps=False)
    kept = font_factory(family="Kept")
    gone = font_factory(family="GoneAfter")
    kept_hash = (await _push(api_client, device_id, kept, "Kept.ttf"))["fileHash"]
    gone_font = await _push(api_client, device_id, gone, "GoneAfter.ttf")

    await _register(api_client)
    await _delta(api_client, device_id, [kept_hash, gone_font["fileHash"]])
    await _delta(api_client, device_id, [kept_hash])

    assert [r["fontId"] for r in await _removals(api_client)] == [gone_font["fontId"]]


@pytest.mark.asyncio
async def test_new_capable_device_detects_from_the_start(
    api_client: AsyncClient, font_factory
) -> None:
    """Un appareil neuf n'a pas de registre hérité : pas besoin de ligne de base."""
    device_id = await _register(api_client)
    assert (await _device(device_id)).full_declaration_since is not None
    kept = font_factory(family="Kept")
    gone = font_factory(family="Gone")
    kept_hash = (await _push(api_client, device_id, kept, "Kept.ttf"))["fileHash"]
    gone_font = await _push(api_client, device_id, gone, "Gone.ttf")

    await _delta(api_client, device_id, [kept_hash])

    assert [r["fontId"] for r in await _removals(api_client)] == [gone_font["fontId"]]


@pytest.mark.asyncio
async def test_capability_loss_resets_baseline(api_client: AsyncClient) -> None:
    device_id = await _register(api_client)
    assert (await _device(device_id)).full_declaration_since is not None

    await _register(api_client, caps=False)

    assert (await _device(device_id)).full_declaration_since is None


@pytest.mark.asyncio
async def test_merge_resets_target_baseline(
    api_client: AsyncClient, font_factory
) -> None:
    """Le registre fusionné vient d'une autre machine : le prochain delta de la
    cible ne doit pas lire ses polices comme supprimées."""
    keeper = await _register(api_client, hostname="mac-keep")
    stale = await _register(api_client, hostname="mac-stale")
    mine = font_factory(family="Mine")
    theirs = font_factory(family="Theirs")
    mine_hash = (await _push(api_client, keeper, mine, "Mine.ttf"))["fileHash"]
    await _push(api_client, stale, theirs, "Theirs.ttf")

    resp = await api_client.post(
        f"/api/devices/{keeper}/merge",
        headers=AUTH_HEADERS,
        json={"sourceDeviceIds": [stale]},
    )
    assert resp.status_code == 200, resp.text

    await _delta(api_client, keeper, [mine_hash])

    assert await _removals(api_client) == []
    assert (await _device(keeper)).full_declaration_since is not None


# ---------- P1-6d : actions refusées aux agents sans la capacité ----------


@pytest.mark.asyncio
async def test_deactivate_409_without_capability(
    api_client: AsyncClient, font_factory
) -> None:
    device_id = await _register(api_client, caps=False)
    pushed = await _push(api_client, device_id, font_factory(family="D"), "D.ttf")

    resp = await api_client.post(
        f"/api/fonts/{pushed['fontId']}/deactivate/{device_id}",
        headers=AUTH_HEADERS,
    )

    assert resp.status_code == 409
    assert "trop ancien" in resp.json()["detail"]
    # Réactiver reste permis : c'est l'état par défaut, sans risque.
    resp = await api_client.post(
        f"/api/fonts/{pushed['fontId']}/activate/{device_id}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_propagate_toggle_409_without_capability(api_client: AsyncClient) -> None:
    device_id = await _register(api_client, caps=False)

    resp = await api_client.patch(
        f"/api/devices/{device_id}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True},
    )
    assert resp.status_code == 409
    assert "trop ancien" in resp.json()["detail"]

    # Couper la propagation reste toujours possible, comme les autres réglages.
    resp = await api_client.patch(
        f"/api/devices/{device_id}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": False, "autoPull": True},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_capable_agent_can_deactivate_and_propagate(
    api_client: AsyncClient, font_factory
) -> None:
    device_id = await _register(api_client)
    pushed = await _push(api_client, device_id, font_factory(family="C"), "C.ttf")

    resp = await api_client.post(
        f"/api/fonts/{pushed['fontId']}/deactivate/{device_id}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    resp = await api_client.patch(
        f"/api/devices/{device_id}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_contract_v001_register_and_delta(
    api_client: AsyncClient, font_factory
) -> None:
    """Les corps d'un agent v0.0.1 restent acceptés tels quels (contrat)."""
    resp = await api_client.post(
        "/api/devices/register", headers=AUTH_HEADERS, json=_V001_REGISTER
    )
    assert resp.status_code == 201, resp.text
    device = resp.json()
    assert device["capabilities"] is None
    assert device["agentVersion"] == "0.0.1"

    data = font_factory(family="Contract")
    pushed = await _push(api_client, device["id"], data, "Contract.ttf")
    resp = await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={
            "device_id": device["id"],
            "fonts": [{"hash": pushed["fileHash"], "filename": "Contract.ttf"}],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["unknownToServer"] == []
    assert body["alreadySynced"] == 1
