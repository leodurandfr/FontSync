"""Identité d'un appareil, fusion des doublons, et mise à jour du serveur.

Le hostname n'est pas une identité. macOS en change selon le réseau (`.local`
en Bonjour, `.home` en DHCP) et l'upsert par hostname créait une ligne par
variante — trois pour un même Mac mini en production, ce qui fausse toute règle
« quelles machines détiennent cette police ». L'agent persiste pourtant son
`device_id` depuis son premier enregistrement ; il suffisait de l'envoyer.

Reste à réparer l'existant : fusionner, pas supprimer. Le registre
`device_fonts` est réparti entre les doublons, et une survivante au registre
partiel rend la détection des suppressions aveugle sur ces polices-là.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from backend.config import settings
from backend.routers import system as system_router
from tests.backend.conftest import AUTH_HEADERS

_MISSING_UUID = "00000000-0000-0000-0000-000000000000"


async def _register(client: AsyncClient, **overrides) -> dict:
    payload = {"name": "Mac", "hostname": "mac", "os": "macos"}
    payload.update(overrides)
    resp = await client.post(
        "/api/devices/register", headers=AUTH_HEADERS, json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _push(client: AsyncClient, device_id: str, data: bytes, name: str) -> dict:
    resp = await client.post(
        "/api/sync/push",
        headers=AUTH_HEADERS,
        files={"file": (name, data, "font/ttf")},
        data={"device_id": device_id, "local_path": f"/Users/x/{name}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- Identité stable ----------


@pytest.mark.asyncio
async def test_changing_hostname_no_longer_creates_a_device(
    api_client: AsyncClient,
) -> None:
    """Le cas de production : `.local` puis `.home` pour le même Mac."""
    first = await _register(api_client, hostname="Mac-mini-de-Leo.local")

    second = await _register(
        api_client,
        hostname="mac-mini-de-leo1.home",
        deviceId=first["id"],
    )

    assert second["id"] == first["id"]
    assert second["hostname"] == "mac-mini-de-leo1.home"
    devices = (await api_client.get("/api/devices", headers=AUTH_HEADERS)).json()
    assert len(devices) == 1


@pytest.mark.asyncio
async def test_unknown_device_id_falls_back_to_hostname(
    api_client: AsyncClient,
) -> None:
    """Base repartie de zéro, appareil supprimé : l'agent se ré-enregistre.

    Échouer serait pire que réenregistrer — l'agent boucle sur `register` à
    chaque sync, et un `device_id` périmé le laisserait hors ligne pour de bon.
    """
    existing = await _register(api_client, hostname="mac")

    same = await _register(api_client, hostname="mac", deviceId=_MISSING_UUID)

    assert same["id"] == existing["id"]


@pytest.mark.asyncio
async def test_register_does_not_overwrite_server_side_settings(
    api_client: AsyncClient,
) -> None:
    """`propagate_deletions` est piloté depuis l'interface, pas par l'agent."""
    device = await _register(api_client)
    await api_client.patch(
        f"/api/devices/{device['id']}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True, "autoPull": True},
    )

    again = await _register(api_client, deviceId=device["id"])

    assert again["propagateDeletions"] is True
    assert again["autoPull"] is True


# ---------- Fusion des doublons ----------


@pytest.mark.asyncio
async def test_merge_moves_the_font_registry(
    api_client: AsyncClient, font_factory
) -> None:
    """Fusionner conserve le registre — c'est toute la différence avec supprimer."""
    keeper = await _register(api_client, hostname="mac-keep")
    stale = await _register(api_client, hostname="mac-stale")
    shared = font_factory(family="Shared")
    only_stale = font_factory(family="OnlyStale")
    await _push(api_client, keeper["id"], shared, "Shared.ttf")
    await _push(api_client, stale["id"], shared, "Shared.ttf")
    pushed = await _push(api_client, stale["id"], only_stale, "OnlyStale.ttf")

    resp = await api_client.post(
        f"/api/devices/{keeper['id']}/merge",
        headers=AUTH_HEADERS,
        json={"sourceDeviceIds": [stale["id"]]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # `Shared` était déjà connue de la cible : retirée du doublon, pas recomptée.
    assert body["fontsMoved"] == 1
    assert body["devicesRemoved"] == 1

    devices = (await api_client.get("/api/devices", headers=AUTH_HEADERS)).json()
    assert [d["id"] for d in devices] == [keeper["id"]]

    holders = (
        await api_client.get(
            f"/api/fonts/{pushed['fontId']}/devices", headers=AUTH_HEADERS
        )
    ).json()
    installed = [d["deviceId"] for d in holders if d["installed"]]
    assert installed == [keeper["id"]]


@pytest.mark.asyncio
async def test_merge_refuses_a_device_into_itself(api_client: AsyncClient) -> None:
    device = await _register(api_client)

    resp = await api_client.post(
        f"/api/devices/{device['id']}/merge",
        headers=AUTH_HEADERS,
        json={"sourceDeviceIds": [device["id"]]},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_merge_of_unknown_device_is_404(api_client: AsyncClient) -> None:
    device = await _register(api_client)

    resp = await api_client.post(
        f"/api/devices/{device['id']}/merge",
        headers=AUTH_HEADERS,
        json={"sourceDeviceIds": [_MISSING_UUID]},
    )

    assert resp.status_code == 404


# ---------- Version et mise à jour ----------


@pytest.mark.asyncio
async def test_info_reports_dev_without_a_build_version(
    api_client: AsyncClient, monkeypatch
) -> None:
    """Hors image publiée, l'interface dit « dev » plutôt que d'inventer."""
    monkeypatch.setattr(settings, "fontsync_version", "")

    resp = await api_client.get("/api/system/info", headers=AUTH_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"version": "dev", "updateAvailable": False}


@pytest.mark.asyncio
async def test_update_is_503_when_not_configured(
    api_client: AsyncClient, monkeypatch
) -> None:
    """Sans Watchtower, on le dit — et l'interface masque le bouton."""
    monkeypatch.setattr(settings, "watchtower_url", "")
    monkeypatch.setattr(settings, "watchtower_token", "")

    resp = await api_client.post("/api/system/update", headers=AUTH_HEADERS)

    assert resp.status_code == 503


def _fake_watchtower(monkeypatch, handler) -> None:
    """Branche un Watchtower factice sur le client HTTP du routeur.

    La vraie classe est capturée **avant** le patch : la remplacer par une
    lambda qui la rappellerait par son nom de module se rappellerait elle-même.
    """
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        system_router.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )


@pytest.mark.asyncio
async def test_update_relays_to_watchtower(
    api_client: AsyncClient, monkeypatch
) -> None:
    """Le contrat côté Watchtower : POST /v1/update, token en Bearer."""
    monkeypatch.setattr(settings, "watchtower_url", "http://watchtower:8080")
    monkeypatch.setattr(settings, "watchtower_token", "wt-secret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, text="Updates triggered")

    _fake_watchtower(monkeypatch, handler)

    resp = await api_client.post("/api/system/update", headers=AUTH_HEADERS)

    assert resp.status_code == 202, resp.text
    assert seen == {
        "url": "http://watchtower:8080/v1/update",
        "method": "POST",
        "auth": "Bearer wt-secret",
    }


@pytest.mark.asyncio
async def test_update_reports_an_unreachable_watchtower(
    api_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "watchtower_url", "http://watchtower:8080")
    monkeypatch.setattr(settings, "watchtower_token", "wt-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _fake_watchtower(monkeypatch, handler)

    resp = await api_client.post("/api/system/update", headers=AUTH_HEADERS)

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_update_reports_a_watchtower_rejection(
    api_client: AsyncClient, monkeypatch
) -> None:
    """Un token Watchtower désaccordé doit se voir, pas passer pour un succès."""
    monkeypatch.setattr(settings, "watchtower_url", "http://watchtower:8080")
    monkeypatch.setattr(settings, "watchtower_token", "mauvais-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    _fake_watchtower(monkeypatch, handler)

    resp = await api_client.post("/api/system/update", headers=AUTH_HEADERS)

    assert resp.status_code == 502
    assert "401" in resp.json()["detail"]
