"""Suppression propagée : pierre tombale, corbeille, quarantaine.

Le défaut d'origine, vérifié bout en bout ici : **aucune suppression n'était
durable**. Une police supprimée côté serveur restait « inconnue » du delta pour
la machine qui détenait encore le fichier, celle-ci la repoussait, et l'import
la ressuscitait. Trois maillons, un seul suffisait à annuler le geste.

Les tests suivent cet enchaînement plutôt que le découpage des modules :

1. la pierre tombale tient (delta, push, import) ;
2. la corbeille rend le geste réversible sans le rendre illusoire (vider retire
   le fichier, garde l'empreinte) ;
3. la quarantaine détecte une disparition locale — et s'arrête au seuil.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.config import settings
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import (
    DELETION_MANUAL,
    DELETION_PENDING,
    DELETION_QUARANTINE,
    Font,
)
from backend.schemas.sync import DeviceFontEntry
from backend.services.deletion_propagation import (
    detect_local_deletions,
    propagation_limit,
)
from backend.services.font_importer import import_font
from backend.services.sync_manager import compute_delta, register_device_font
from backend.services.trash import purge_expired, purge_font
from tests.backend.conftest import AUTH_HEADERS


# ---------- Helpers API ----------


async def _register_device(client: AsyncClient, hostname: str = "mac-test") -> str:
    resp = await client.post(
        "/api/devices/register",
        headers=AUTH_HEADERS,
        json={"name": "Mac de test", "hostname": hostname, "os": "macos"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(client: AsyncClient, data: bytes, name: str) -> dict:
    resp = await client.post(
        "/api/fonts/upload",
        headers=AUTH_HEADERS,
        files=[("files", (name, data, "font/ttf"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["imported"]) == 1, resp.text
    return body["imported"][0]


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


# ---------- Helpers modèle (tests unitaires) ----------


async def _make_device(db, *, propagate: bool = True, hostname: str = "mac") -> Device:
    device = Device(
        name="Mac", hostname=hostname, os="macos", propagate_deletions=propagate
    )
    db.add(device)
    await db.flush()
    return device


async def _make_font(db, storage, font_factory, family: str) -> Font:
    font, _ = await import_font(
        f"{family}.ttf", font_factory(family=family), storage, db
    )
    return font


# =====================================================================
# 1. Pierre tombale — la suppression tient
# =====================================================================


@pytest.mark.asyncio
async def test_deleted_font_is_not_offered_for_push(db, storage, font_factory) -> None:
    """Le delta doit dire « connue, supprimée », pas « inconnue ».

    C'est le maillon qui bouclait : listée comme inconnue, la police était
    repoussée à *chaque* sync par la machine qui détenait encore le fichier.
    """
    font = await _make_font(db, storage, font_factory, "Gone")
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()

    delta = await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="Gone.ttf")], db
    )

    assert delta.unknown_to_server == []
    assert delta.missing_on_device == []
    assert delta.already_synced == 0
    assert delta.deleted_on_server == 1


@pytest.mark.asyncio
async def test_agent_push_does_not_revive_a_deleted_font(
    db, storage, font_factory
) -> None:
    """Un push d'agent ne réveille jamais une pierre tombale."""
    data = font_factory(family="Phoenix")
    font, _ = await import_font("phoenix.ttf", data, storage, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()

    same, is_duplicate = await import_font(
        "phoenix.ttf", data, storage, db, source="local_scan", revive_deleted=False
    )

    assert is_duplicate is True
    assert same.id == font.id
    assert same.deleted_at is not None


@pytest.mark.asyncio
async def test_web_upload_still_revives(db, storage, font_factory) -> None:
    """Ré-uploader depuis l'interface reste une restauration délibérée.

    La règle n'est pas « ne jamais réveiller » mais « ne jamais réveiller par
    accident » : c'est le geste de l'utilisateur qui fait la différence.
    """
    data = font_factory(family="Revive")
    font, _ = await import_font("revive.ttf", data, storage, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()

    revived, is_duplicate = await import_font("revive.ttf", data, storage, db)

    assert revived.deleted_at is None
    assert revived.deleted_reason is None
    # Pas un doublon inerte : la police vient de rentrer dans la bibliothèque,
    # l'interface et les agents doivent l'apprendre.
    assert is_duplicate is False


@pytest.mark.asyncio
async def test_push_of_deleted_font_is_refused_not_errored(
    api_client: AsyncClient, font_factory
) -> None:
    """Le refus est signalé pour ce qu'il est ; l'agent ne le compte pas en erreur."""
    device_id = await _register_device(api_client)
    data = font_factory(family="Tomb")
    font = await _upload(api_client, data, "Tomb.ttf")

    resp = await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)
    assert resp.status_code == 204

    pushed = await _push(api_client, device_id, data, "Tomb.ttf")

    assert pushed["refusedDeleted"] is True
    assert pushed["fontId"] == font["id"]
    # HTTP 200 : un refus n'est pas une panne.
    assert (
        await api_client.get(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)
    ).status_code == 404


@pytest.mark.asyncio
async def test_full_loop_deletion_survives_a_resync(
    api_client: AsyncClient, font_factory
) -> None:
    """Le scénario complet : supprimer, re-synchroniser, la police reste partie."""
    device_id = await _register_device(api_client)
    data = font_factory(family="Durable")
    font = await _upload(api_client, data, "Durable.ttf")
    file_hash = font["fileHash"]

    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)

    # La machine détient encore le fichier et se re-synchronise.
    delta = await _delta(api_client, device_id, [file_hash])
    assert delta["unknownToServer"] == []

    # Même si elle poussait quand même (course, agent sans delta) : refus.
    assert (await _push(api_client, device_id, data, "Durable.ttf"))[
        "refusedDeleted"
    ] is True

    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 0


# =====================================================================
# 2. Corbeille
# =====================================================================


@pytest.mark.asyncio
async def test_trash_lists_deleted_fonts(api_client: AsyncClient, font_factory) -> None:
    font = await _upload(api_client, font_factory(family="Bin"), "Bin.ttf")
    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)

    resp = await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == font["id"]
    assert body["items"][0]["deletedReason"] == DELETION_MANUAL
    assert body["pendingConfirmation"] == 0


@pytest.mark.asyncio
async def test_restore_puts_the_font_back(
    api_client: AsyncClient, font_factory
) -> None:
    font = await _upload(api_client, font_factory(family="Back"), "Back.ttf")
    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)

    resp = await api_client.post(
        f"/api/fonts/{font['id']}/restore", headers=AUTH_HEADERS
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["deletedAt"] is None
    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 1


@pytest.mark.asyncio
async def test_emptying_trash_keeps_the_fingerprint(
    api_client: AsyncClient, font_factory
) -> None:
    """Vider retire le fichier et **garde la ligne**.

    Supprimer la ligne aussi ferait revenir la police au premier push d'une
    machine qui la détient encore — et une purge au jour 30 la ferait
    réapparaître au jour 31, indéfiniment.
    """
    device_id = await _register_device(api_client)
    data = font_factory(family="Purged")
    font = await _upload(api_client, data, "Purged.ttf")
    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)

    resp = await api_client.post("/api/fonts/trash/empty", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["purged"] == 1

    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert trash["total"] == 1
    assert trash["items"][0]["purgedAt"] is not None

    # L'empreinte fait son travail : la machine ne peut pas la ramener.
    assert (await _push(api_client, device_id, data, "Purged.ttf"))[
        "refusedDeleted"
    ] is True


@pytest.mark.asyncio
async def test_restoring_a_purged_font_is_refused(
    api_client: AsyncClient, font_factory
) -> None:
    """Sans fichier, restaurer ne rendrait qu'une ligne creuse."""
    font = await _upload(api_client, font_factory(family="NoFile"), "NoFile.ttf")
    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)
    await api_client.post("/api/fonts/trash/empty", headers=AUTH_HEADERS)

    resp = await api_client.post(
        f"/api/fonts/{font['id']}/restore", headers=AUTH_HEADERS
    )

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reuploading_a_purged_font_restores_the_file(
    api_client: AsyncClient, font_factory
) -> None:
    """Le seul chemin de retour après vidage : fournir à nouveau le fichier."""
    data = font_factory(family="Reup")
    font = await _upload(api_client, data, "Reup.ttf")
    await api_client.delete(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)
    await api_client.post("/api/fonts/trash/empty", headers=AUTH_HEADERS)

    resp = await api_client.post(
        "/api/fonts/upload",
        headers=AUTH_HEADERS,
        files=[("files", ("Reup.ttf", data, "font/ttf"))],
    )
    assert resp.status_code == 200, resp.text
    # Comptée comme un ajout, pas comme un doublon ignoré : c'est un retour dans
    # la bibliothèque, et l'interface doit le refléter tout de suite.
    assert [f["id"] for f in resp.json()["imported"]] == [font["id"]]
    assert resp.json()["duplicates"] == []

    detail = await api_client.get(f"/api/fonts/{font['id']}", headers=AUTH_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["purgedAt"] is None
    # Le fichier est bien de retour au stockage.
    file_resp = await api_client.get(
        f"/api/fonts/{font['id']}/file", headers=AUTH_HEADERS
    )
    assert file_resp.status_code == 200
    assert file_resp.content == data


@pytest.mark.asyncio
async def test_purging_an_active_font_is_refused(
    api_client: AsyncClient, font_factory
) -> None:
    font = await _upload(api_client, font_factory(family="Alive"), "Alive.ttf")

    resp = await api_client.post(f"/api/fonts/{font['id']}/purge", headers=AUTH_HEADERS)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_purge_is_idempotent(db, storage, font_factory) -> None:
    font = await _make_font(db, storage, font_factory, "Twice")
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()

    assert await purge_font(font, storage, db) is True
    assert await purge_font(font, storage, db) is False


@pytest.mark.asyncio
async def test_auto_purge_is_off_by_default(db, storage, font_factory) -> None:
    """Rien ne supprime de fichier tout seul sans qu'on l'ait demandé."""
    font = await _make_font(db, storage, font_factory, "Old")
    font.deleted_at = datetime.now(timezone.utc) - timedelta(days=365)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()

    assert settings.trash_retention_days == 0
    assert await purge_expired(storage, db) == 0
    assert font.purged_at is None


@pytest.mark.asyncio
async def test_auto_purge_respects_retention(db, storage, font_factory) -> None:
    old = await _make_font(db, storage, font_factory, "Ancient")
    recent = await _make_font(db, storage, font_factory, "Fresh")
    now = datetime.now(timezone.utc)
    old.deleted_at = now - timedelta(days=40)
    old.deleted_reason = DELETION_MANUAL
    recent.deleted_at = now - timedelta(days=2)
    recent.deleted_reason = DELETION_MANUAL
    await db.commit()

    assert await purge_expired(storage, db, retention_days=30) == 1
    assert old.purged_at is not None
    assert recent.purged_at is None


# =====================================================================
# 3. Quarantaine — détection des suppressions locales
# =====================================================================


@pytest.mark.asyncio
async def test_disappeared_font_is_quarantined(db, storage, font_factory) -> None:
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Local")
    await register_device_font(device.id, font.id, "/Users/x/Local.ttf", db)
    other = await _make_font(db, storage, font_factory, "Kept")
    await register_device_font(device.id, other.id, "/Users/x/Kept.ttf", db)
    await db.commit()

    detection = await detect_local_deletions(device.id, {other.file_hash}, db)

    assert [f.id for f in detection.quarantined] == [font.id]
    assert font.deleted_reason == DELETION_QUARANTINE
    assert other.deleted_at is None


@pytest.mark.asyncio
async def test_quarantine_drops_the_stale_association(
    db, storage, font_factory
) -> None:
    """Le registre doit refléter le disque : la machine n'a plus le fichier.

    Garder l'association ferait re-détecter la même disparition à chaque sync —
    et surtout, restaurer la police depuis la corbeille la ferait re-quarantiner
    au sync suivant, une boucle qu'aucun clic ne casse.
    """
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Stale")
    keeper = await _make_font(db, storage, font_factory, "Keeper")
    await register_device_font(device.id, font.id, "/Users/x/Stale.ttf", db)
    await register_device_font(device.id, keeper.id, "/Users/x/Keeper.ttf", db)
    await db.commit()

    await detect_local_deletions(device.id, {keeper.file_hash}, db)

    rows = await db.execute(
        select(DeviceFont.font_id).where(DeviceFont.device_id == device.id)
    )
    assert list(rows.scalars().all()) == [keeper.id]


@pytest.mark.asyncio
async def test_empty_declaration_never_deletes_anything(
    db, storage, font_factory
) -> None:
    """Une machine qui ne déclare rien n'a pas vidé sa bibliothèque.

    Dossier démonté, scan en échec, configuration cassée : autant de causes plus
    probables qu'une suppression volontaire de tout.
    """
    device = await _make_device(db)
    font = await _make_font(db, storage, font_factory, "Safe")
    await register_device_font(device.id, font.id, "/Users/x/Safe.ttf", db)
    await db.commit()

    detection = await detect_local_deletions(device.id, set(), db)

    assert detection.total == 0
    assert font.deleted_at is None


@pytest.mark.asyncio
async def test_unassociated_font_is_never_quarantined(
    db, storage, font_factory
) -> None:
    """Une police jamais transférée ici ne peut pas en avoir disparu."""
    device = await _make_device(db)
    mine = await _make_font(db, storage, font_factory, "Mine")
    theirs = await _make_font(db, storage, font_factory, "Theirs")
    await register_device_font(device.id, mine.id, "/Users/x/Mine.ttf", db)
    await db.commit()

    await detect_local_deletions(device.id, {mine.file_hash}, db)

    assert theirs.deleted_at is None


@pytest.mark.asyncio
async def test_mass_disappearance_quarantines_without_propagating(
    db, storage, font_factory, monkeypatch
) -> None:
    """Le cas réel : 625 fichiers disparus d'un coup lors d'un nettoyage manuel.

    Les polices sortent de la bibliothèque — récupérables d'un clic — mais aucune
    autre machine ne les désinstalle tant que l'utilisateur n'a pas confirmé.
    """
    monkeypatch.setattr(settings, "deletion_propagation_max_fonts", 3)
    device = await _make_device(db)
    fonts = [await _make_font(db, storage, font_factory, f"Mass{i}") for i in range(6)]
    survivors = [
        await _make_font(db, storage, font_factory, f"Alive{i}") for i in range(30)
    ]
    for f in fonts + survivors:
        await register_device_font(device.id, f.id, f"/Users/x/{f.id}.ttf", db)
    await db.commit()

    detection = await detect_local_deletions(
        device.id, {f.file_hash for f in survivors}, db
    )

    assert detection.quarantined == []
    assert len(detection.pending) == 6
    assert all(f.deleted_reason == DELETION_PENDING for f in fonts)


@pytest.mark.asyncio
async def test_pending_quarantine_is_not_propagated(db, storage, font_factory) -> None:
    """Une quarantaine en attente n'apparaît pas dans `to_uninstall`."""
    font = await _make_font(db, storage, font_factory, "Held")
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_PENDING
    await db.commit()

    delta = await compute_delta(
        [DeviceFontEntry(hash=font.file_hash, filename="Held.ttf")],
        db,
        propagate_deletions=True,
    )

    assert delta.to_uninstall == []
    assert delta.deleted_on_server == 1


@pytest.mark.asyncio
async def test_to_uninstall_requires_the_device_setting(
    db, storage, font_factory
) -> None:
    """Sans le réglage, la machine apprend la suppression mais n'efface rien."""
    font = await _make_font(db, storage, font_factory, "Told")
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    await db.commit()
    entries = [DeviceFontEntry(hash=font.file_hash, filename="Told.ttf")]

    off = await compute_delta(entries, db, propagate_deletions=False)
    on = await compute_delta(entries, db, propagate_deletions=True)

    assert off.to_uninstall == []
    assert off.deleted_on_server == 1
    assert [ref.file_hash for ref in on.to_uninstall] == [font.file_hash]


def test_propagation_limit_takes_the_strictest_bound(monkeypatch) -> None:
    """Les deux seuils s'appliquent ensemble, relevés par un plancher."""
    monkeypatch.setattr(settings, "deletion_propagation_max_fonts", 25)
    monkeypatch.setattr(settings, "deletion_propagation_max_ratio", 0.05)
    monkeypatch.setattr(settings, "deletion_propagation_min_fonts", 3)

    # Grosse bibliothèque : 5 % ferait 200, l'absolu tranche.
    assert propagation_limit(4000) == 25
    # Petite machine : l'absolu serait trop permissif, le pourcentage tranche.
    assert propagation_limit(200) == 10
    # Très petite machine : le plancher évite que supprimer une police paraisse
    # cassé (5 % de 30 vaudrait 1).
    assert propagation_limit(30) == 3


# ---------- Bout en bout, par le delta ----------


@pytest.mark.asyncio
async def test_delta_quarantines_then_asks_other_device_to_uninstall(
    api_client: AsyncClient, font_factory
) -> None:
    """Deux machines : l'une perd la police, l'autre reçoit l'ordre de l'effacer."""
    laptop = await _register_device(api_client, hostname="laptop")
    desktop = await _register_device(api_client, hostname="desktop")
    for device_id in (laptop, desktop):
        resp = await api_client.patch(
            f"/api/devices/{device_id}",
            headers=AUTH_HEADERS,
            json={"propagateDeletions": True},
        )
        assert resp.status_code == 200, resp.text

    data = font_factory(family="Shared")
    pushed = await _push(api_client, laptop, data, "Shared.ttf")
    file_hash = pushed["fileHash"]
    # Une seconde police reste en place : le laptop doit continuer de déclarer
    # quelque chose, sinon c'est le garde-fou « déclaration vide » qui répond.
    kept = await _push(api_client, laptop, font_factory(family="Kept"), "Kept.ttf")
    # Le desktop récupère la première → il en devient détenteur enregistré.
    pull = await api_client.get(
        f"/api/sync/pull/{pushed['fontId']}?device_id={desktop}", headers=AUTH_HEADERS
    )
    assert pull.status_code == 200, pull.text

    # Le laptop la supprime localement : il ne la déclare plus.
    delta_laptop = await _delta(api_client, laptop, [kept["fileHash"]])
    assert delta_laptop["unknownToServer"] == []
    assert delta_laptop["missingOnDevice"] == []

    # Le desktop l'a encore → on lui demande de la désinstaller.
    delta_desktop = await _delta(api_client, desktop, [file_hash])
    assert [ref["fileHash"] for ref in delta_desktop["toUninstall"]] == [file_hash]

    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert trash["total"] == 1
    assert trash["items"][0]["deletedReason"] == DELETION_QUARANTINE


@pytest.mark.asyncio
async def test_restore_after_propagated_delete_does_not_loop(
    api_client: AsyncClient, font_factory
) -> None:
    """Restaurer ne doit pas être défait par le sync suivant.

    Sans nettoyage des associations à la suppression, la police restaurée
    redeviendrait active alors qu'un appareil qui l'a désinstallée y reste
    associé : lue comme disparue, elle repartirait en quarantaine. Une boucle
    qu'aucun clic ne casse.
    """
    laptop = await _register_device(api_client, hostname="laptop")
    await api_client.patch(
        f"/api/devices/{laptop}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True},
    )
    gone = await _push(api_client, laptop, font_factory(family="Loop"), "Loop.ttf")
    kept = await _push(api_client, laptop, font_factory(family="Stay"), "Stay.ttf")

    await api_client.delete(f"/api/fonts/{gone['fontId']}", headers=AUTH_HEADERS)
    # L'appareil applique la désinstallation : il ne la déclare plus.
    delta = await _delta(api_client, laptop, [kept["fileHash"]])
    assert [ref["fileHash"] for ref in delta["toUninstall"]] == []

    resp = await api_client.post(
        f"/api/fonts/{gone['fontId']}/restore", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200, resp.text

    # Nouveau sync : l'appareil ne l'a toujours pas, mais rien ne la re-supprime.
    delta = await _delta(api_client, laptop, [kept["fileHash"]])
    assert [ref["fileHash"] for ref in delta["missingOnDevice"]] == [gone["fileHash"]]
    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert trash["total"] == 0


@pytest.mark.asyncio
async def test_local_deletion_is_recorded_without_the_setting(
    api_client: AsyncClient, font_factory
) -> None:
    """Sans le réglage, la disparition est **enregistrée** — mais rien n'est effacé.

    C'est la moitié qui manquait : conditionner l'écoute à `propagate_deletions`
    rendait toute suppression locale impossible (le serveur ne concluait rien,
    la police restait offerte au pull, `auto_pull` la réinstallait). Enregistrer
    ne détruit rien : la police part en corbeille, récupérable.
    """
    laptop = await _register_device(api_client, hostname="laptop")
    gone = await _push(api_client, laptop, font_factory(family="Gone"), "Gone.ttf")
    # Une seconde police reste : sans elle c'est le garde-fou « déclaration
    # vide » qui répondrait, et le test ne prouverait rien.
    kept = await _push(api_client, laptop, font_factory(family="Kept"), "Kept.ttf")

    delta = await _delta(api_client, laptop, [kept["fileHash"]])

    # Sortie de la bibliothèque, et plus jamais re-proposée au pull.
    assert [ref["fileHash"] for ref in delta["missingOnDevice"]] == []
    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 1
    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert [item["fileHash"] for item in trash["items"]] == [gone["fileHash"]]


@pytest.mark.asyncio
async def test_deletion_recorded_here_is_not_applied_there(
    api_client: AsyncClient, font_factory
) -> None:
    """L'appareil qui n'a pas opté ne reçoit jamais d'ordre de désinstallation.

    Le pendant du test précédent : enregistrer se fait toujours, *appliquer*
    reste derrière `propagate_deletions`. C'est bien la moitié destructrice qui
    est gardée, et elle seule.
    """
    laptop = await _register_device(api_client, hostname="laptop")
    desktop = await _register_device(api_client, hostname="desktop")
    pushed = await _push(api_client, laptop, font_factory(family="Both"), "Both.ttf")
    kept = await _push(api_client, laptop, font_factory(family="Kept"), "Kept.ttf")
    pull = await api_client.get(
        f"/api/sync/pull/{pushed['fontId']}?device_id={desktop}", headers=AUTH_HEADERS
    )
    assert pull.status_code == 200, pull.text

    # Le laptop la perd → quarantaine propageable (sous le seuil).
    await _delta(api_client, laptop, [kept["fileHash"]])

    # Le desktop la détient toujours, mais n'a pas opté : on ne lui demande rien.
    delta_desktop = await _delta(api_client, desktop, [pushed["fileHash"]])
    assert delta_desktop["toUninstall"] == []
    assert delta_desktop["deletedOnServer"] == 1


@pytest.mark.asyncio
async def test_confirming_pending_resumes_propagation(
    api_client: AsyncClient, font_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "deletion_propagation_max_fonts", 0)
    monkeypatch.setattr(settings, "deletion_propagation_min_fonts", 0)
    laptop = await _register_device(api_client, hostname="laptop")
    await api_client.patch(
        f"/api/devices/{laptop}",
        headers=AUTH_HEADERS,
        json={"propagateDeletions": True},
    )
    data = font_factory(family="Held")
    pushed = await _push(api_client, laptop, data, "Held.ttf")

    await _delta(api_client, laptop, ["a" * 64])
    trash = (await api_client.get("/api/fonts/trash", headers=AUTH_HEADERS)).json()
    assert trash["pendingConfirmation"] == 1

    resp = await api_client.post("/api/fonts/trash/confirm", headers=AUTH_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmed"] == 1

    delta = await _delta(api_client, laptop, [pushed["fileHash"]])
    assert [ref["fileHash"] for ref in delta["toUninstall"]] == [pushed["fileHash"]]


# =====================================================================
# 4. Hygiène — endpoints réparés
# =====================================================================


@pytest.mark.asyncio
async def test_rescan_signals_over_sse(api_client: AsyncClient, monkeypatch) -> None:
    """`/rescan` passait par le canal WebSocket agent, mort : 503 permanent."""
    from backend.routers import devices as devices_router
    from backend.services.ws_manager import WebSocketManager

    manager = WebSocketManager()
    monkeypatch.setattr(devices_router, "ws_manager", manager)
    device_id = await _register_device(api_client)
    queue = manager.subscribe_agent_events(device_id)

    resp = await api_client.post(
        f"/api/devices/{device_id}/rescan", headers=AUTH_HEADERS
    )

    assert resp.status_code == 202, resp.text
    assert queue.get_nowait() == "sync"


@pytest.mark.asyncio
async def test_device_with_fonts_can_be_deleted(
    api_client: AsyncClient, font_factory
) -> None:
    """La suppression échouait sur la clé étrangère dès le premier transfert."""
    device_id = await _register_device(api_client)
    await _push(api_client, device_id, font_factory(family="Held"), "Held.ttf")

    resp = await api_client.delete(f"/api/devices/{device_id}", headers=AUTH_HEADERS)

    assert resp.status_code == 204, resp.text
    # La bibliothèque n'est pas amputée : le serveur reste la source de vérité.
    listing = await api_client.get("/api/fonts", headers=AUTH_HEADERS)
    assert listing.json()["total"] == 1
