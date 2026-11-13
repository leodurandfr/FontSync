"""Appareil « en retard » : connecté, mais son sync périodique ne passe plus.

Cas réel (M-39) : le job `sync` du Mac mini échouait au lancement depuis des
jours, mais son process `listen` survivait — l'API et l'UI l'affichaient
« Connecté ». La présence SSE ne dit rien du sync : il faut la date du dernier
passage de l'agent, et ne la faire avancer que par l'agent (un réglage changé
depuis l'interface n'est pas un sync).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from backend.config import Settings, settings
from backend.database import get_db
from backend.main import app
from backend.models.device import Device
from backend.services.device_activity import sync_overdue
from backend.services.ws_manager import ws_manager
from tests.backend.conftest import AUTH_HEADERS


async def _register(client: AsyncClient, hostname: str = "mac") -> dict:
    resp = await client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac", "hostname": hostname, "os": "macos"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_last_seen(device_id: str, when: datetime | None) -> None:
    """Recule `last_seen_at` dans la base du client API (même session factory)."""
    sessions = app.dependency_overrides[get_db]()
    session = await sessions.__anext__()
    try:
        device = await session.get(Device, uuid.UUID(device_id))
        assert device is not None
        device.last_seen_at = when
        await session.commit()
    finally:
        await sessions.aclose()


async def _device(client: AsyncClient, device_id: str) -> dict:
    resp = await client.get("/api/devices", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    return next(d for d in resp.json() if d["id"] == device_id)


def _age(device: dict) -> timedelta:
    return datetime.now(timezone.utc) - datetime.fromisoformat(device["lastSeenAt"])


@pytest.mark.asyncio
async def test_online_but_stale_device_is_overdue(api_client: AsyncClient) -> None:
    """Le cas du mini : `listen` connecté, aucun sync depuis 2 h."""
    device = await _register(api_client)
    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))
    queue = ws_manager.subscribe_agent_events(device["id"])
    try:
        listed = await _device(api_client, device["id"])
    finally:
        ws_manager.unsubscribe_agent_events(device["id"], queue)

    assert listed["isOnline"] is True
    assert listed["syncOverdue"] is True


@pytest.mark.asyncio
async def test_recent_sync_is_not_overdue(api_client: AsyncClient) -> None:
    device = await _register(api_client)

    assert (await _device(api_client, device["id"]))["syncOverdue"] is False


@pytest.mark.asyncio
async def test_never_seen_device_is_overdue(api_client: AsyncClient) -> None:
    device = await _register(api_client)
    await _set_last_seen(device["id"], None)

    assert (await _device(api_client, device["id"]))["syncOverdue"] is True


@pytest.mark.asyncio
async def test_overdue_threshold_is_a_setting(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3 × StartInterval (600 s) par défaut ; réglable pour un intervalle allongé."""
    assert settings.device_overdue_minutes == 30
    device = await _register(api_client)
    await _set_last_seen(
        device["id"], datetime.now(timezone.utc) - timedelta(minutes=45)
    )
    assert (await _device(api_client, device["id"]))["syncOverdue"] is True

    monkeypatch.setattr(settings, "device_overdue_minutes", 60)

    assert (await _device(api_client, device["id"]))["syncOverdue"] is False


@pytest.mark.asyncio
async def test_delta_refreshes_last_seen(api_client: AsyncClient) -> None:
    """Le delta est le sync lui-même : il fait avancer `last_seen_at`."""
    device = await _register(api_client)
    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))

    resp = await api_client.post(
        "/api/sync/delta",
        headers=AUTH_HEADERS,
        json={"deviceId": device["id"], "fonts": []},
    )
    assert resp.status_code == 200, resp.text

    listed = await _device(api_client, device["id"])
    assert _age(listed) < timedelta(minutes=1)
    assert listed["syncOverdue"] is False


@pytest.mark.asyncio
async def test_patch_does_not_refresh_last_seen(api_client: AsyncClient) -> None:
    """Changer un réglage depuis l'interface n'est pas un passage de l'agent."""
    device = await _register(api_client)
    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))

    resp = await api_client.patch(
        f"/api/devices/{device['id']}", headers=AUTH_HEADERS, json={"autoPull": True}
    )
    assert resp.status_code == 200, resp.text

    listed = await _device(api_client, device["id"])
    assert _age(listed) > timedelta(hours=1)
    assert listed["syncOverdue"] is True
    assert resp.json()["syncOverdue"] is True


@pytest.mark.asyncio
async def test_register_of_known_device_does_not_refresh_last_seen(
    api_client: AsyncClient,
) -> None:
    """Le register précède le delta : un delta qui échoue à chaque sync ne doit
    pas être masqué par le register qui l'a précédé."""
    device = await _register(api_client)
    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))

    again = await _register(api_client)

    assert again["id"] == device["id"]
    assert _age(again) > timedelta(hours=1)
    assert again["syncOverdue"] is True


async def _push(client: AsyncClient, device_id: str, data: bytes) -> dict:
    resp = await client.post(
        "/api/sync/push",
        headers=AUTH_HEADERS,
        files={"file": ("A.ttf", data, "font/ttf")},
        data={"device_id": device_id, "local_path": "/Users/x/A.ttf"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_push_and_pull_count_as_sync_activity(
    api_client: AsyncClient, font_factory
) -> None:
    """Un premier sync de milliers de polices dure plus que le seuil : l'appareil
    ne doit pas passer « en retard » pendant qu'il travaille."""
    device = await _register(api_client)
    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))

    pushed = await _push(api_client, device["id"], font_factory(family="Active"))
    assert _age(await _device(api_client, device["id"])) < timedelta(minutes=1)

    await _set_last_seen(device["id"], datetime.now(timezone.utc) - timedelta(hours=2))
    resp = await api_client.get(
        f"/api/sync/pull/{pushed['fontId']}",
        headers=AUTH_HEADERS,
        params={"device_id": device["id"]},
    )
    assert resp.status_code == 200, resp.text
    listed = await _device(api_client, device["id"])
    assert _age(listed) < timedelta(minutes=1)
    assert listed["syncOverdue"] is False


@pytest.mark.asyncio
async def test_pull_writes_activity_at_most_once_a_minute(
    api_client: AsyncClient, font_factory
) -> None:
    device = await _register(api_client)
    pushed = await _push(api_client, device["id"], font_factory(family="Throttle"))
    recent = datetime.now(timezone.utc) - timedelta(seconds=30)
    await _set_last_seen(device["id"], recent)

    resp = await api_client.get(
        f"/api/sync/pull/{pushed['fontId']}",
        headers=AUTH_HEADERS,
        params={"device_id": device["id"]},
    )
    assert resp.status_code == 200, resp.text

    listed = await _device(api_client, device["id"])
    assert datetime.fromisoformat(listed["lastSeenAt"]) == recent


def test_naive_utc_timestamps_on_a_non_utc_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite rend des datetimes naïfs (UTC). Sur un hôte à UTC+14, une
    comparaison à l'heure locale naïve se tromperait de 14 h."""
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    try:
        naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
        assert sync_overdue(naive_now - timedelta(minutes=20)) is False
        assert sync_overdue(naive_now - timedelta(minutes=40)) is True
    finally:
        monkeypatch.undo()
        time.tzset()


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(device_overdue_minutes=0)
