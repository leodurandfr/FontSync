"""État des sauvegardes exposé par `GET /api/system/backups` (P1-2b).

Le serveur ne doit plus être le seul à savoir qu'une sauvegarde échoue : la
date du dernier instantané est relue sur disque (elle survit aux
redémarrages), les erreurs et le bilan du miroir viennent des boucles.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest
from httpx import AsyncClient

from backend.config import settings
from backend.services import backup
from tests.backend.conftest import AUTH_HEADERS


@pytest.fixture(autouse=True)
def _fresh_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup, "status", backup.BackupStatus())


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE fonts (id TEXT PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def backup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "fontsync.db"
    _make_db(source)
    backups = tmp_path / "backups"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(backups))
    return backups


@pytest.mark.asyncio
async def test_backups_endpoint_requires_token(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/system/backups")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_backups_disabled_without_backup_dir(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "backup_dir", "")

    body = (await api_client.get("/api/system/backups", headers=AUTH_HEADERS)).json()

    assert body["enabled"] is False
    assert body["stale"] is False


@pytest.mark.asyncio
async def test_backups_reports_last_snapshot(
    api_client: AsyncClient, backup_env: Path
) -> None:
    source = Path(settings.database_url.split("///", 1)[1])
    snapshot = await backup.backup_database(source, backup_env)

    resp = await api_client.get("/api/system/backups", headers=AUTH_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["lastSnapshotAt"] is not None
    assert body["lastSnapshotBytes"] == snapshot.stat().st_size
    assert body["stale"] is False
    # Aucun chemin absolu de l'hôte dans la réponse.
    assert str(backup_env) not in resp.text


@pytest.mark.asyncio
async def test_backups_stale_without_any_snapshot(
    api_client: AsyncClient, backup_env: Path
) -> None:
    body = (await api_client.get("/api/system/backups", headers=AUTH_HEADERS)).json()

    assert body["enabled"] is True
    assert body["lastSnapshotAt"] is None
    assert body["stale"] is True


@pytest.mark.asyncio
async def test_backups_stale_after_36h(
    api_client: AsyncClient, backup_env: Path
) -> None:
    source = Path(settings.database_url.split("///", 1)[1])
    snapshot = await backup.backup_database(source, backup_env)
    old = time.time() - 37 * 3600
    os.utime(snapshot, (old, old))

    body = (await api_client.get("/api/system/backups", headers=AUTH_HEADERS)).json()

    assert body["stale"] is True


@pytest.mark.asyncio
async def test_backups_reports_last_error(
    api_client: AsyncClient, backup_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    backup_env.mkdir()
    backup_env.chmod(0o500)

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    try:
        with pytest.raises(asyncio.CancelledError):
            await backup.run_database_backup_loop()
    finally:
        backup_env.chmod(0o755)

    resp = await api_client.get("/api/system/backups", headers=AUTH_HEADERS)
    body = resp.json()
    assert body["lastError"]
    assert body["lastErrorAt"] is not None
    assert str(backup_env) not in resp.text


@pytest.mark.asyncio
async def test_successful_snapshot_clears_previous_error(
    api_client: AsyncClient, backup_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup.status.record_error("database", RuntimeError("disque plein"))

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    with pytest.raises(asyncio.CancelledError):
        await backup.run_database_backup_loop()

    body = (await api_client.get("/api/system/backups", headers=AUTH_HEADERS)).json()
    assert body["lastError"] is None
    assert body["stale"] is False


@pytest.mark.asyncio
async def test_backups_reports_mirror_result(
    api_client: AsyncClient,
    backup_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    font_factory,
) -> None:
    fonts = tmp_path / "fonts"
    (fonts / "ab").mkdir(parents=True)
    (fonts / "ab" / "x.ttf").write_bytes(font_factory(family="Mirror"))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    monkeypatch.setattr(settings, "font_storage_path", str(fonts))

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    with pytest.raises(asyncio.CancelledError):
        await backup.run_blob_backup_loop()

    body = (await api_client.get("/api/system/backups", headers=AUTH_HEADERS)).json()
    assert body["lastMirrorAt"] is not None
    assert body["mirrorCopied"] == 1
    assert body["mirrorRepaired"] == 0
    assert body["mirrorFailed"] == 0


async def _get(api_client: AsyncClient) -> dict:
    resp = await api_client.get("/api/system/backups", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    return resp.json()


def _snapshot(directory: Path, name: str, age_hours: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    _make_db(path)
    stamp = time.time() - age_hours * 3600
    os.utime(path, (stamp, stamp))
    return path


@pytest.mark.asyncio
async def test_backups_not_stale_at_30h(
    api_client: AsyncClient, backup_env: Path
) -> None:
    _snapshot(backup_env, "fontsync-20260101-000000.db", age_hours=30)

    assert (await _get(api_client))["stale"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_first", [True, False])
async def test_latest_snapshot_is_the_newest_by_date(
    api_client: AsyncClient, backup_env: Path, fresh_first: bool
) -> None:
    ages = (1, 40) if fresh_first else (40, 1)
    _snapshot(backup_env, "fontsync-20260101-000000.db", age_hours=ages[0])
    fresh = _snapshot(backup_env, "fontsync-20260102-000000.db", age_hours=ages[1])
    if fresh_first:
        fresh = backup_env / "fontsync-20260101-000000.db"

    body = await _get(api_client)

    assert body["stale"] is False
    assert body["lastSnapshotBytes"] == fresh.stat().st_size


@pytest.mark.asyncio
async def test_database_snapshots_not_applicable_outside_sqlite(
    api_client: AsyncClient, backup_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "database_url", "postgresql+asyncpg://db.invalid/fontsync"
    )
    monkeypatch.setattr(settings, "storage_backend", "filesystem")

    body = await _get(api_client)

    # Le miroir tourne encore : activé, mais pas d'instantané attendu.
    assert body["enabled"] is True
    assert body["stale"] is False
    assert body["lastSnapshotAt"] is None


@pytest.mark.asyncio
async def test_error_from_unreachable_backup_dir_hides_host_paths(
    api_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    source = tmp_path / "fontsync.db"
    _make_db(source)
    locked = tmp_path / "locked"
    locked.mkdir()
    # Le parent manquant de BACKUP_DIR ne peut pas être créé : l'erreur nomme
    # un ancêtre de BACKUP_DIR, pas BACKUP_DIR lui-même.
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{source}")
    monkeypatch.setattr(settings, "backup_dir", str(locked / "missing" / "backups"))
    locked.chmod(0o500)

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    try:
        with pytest.raises(asyncio.CancelledError):
            await backup.run_database_backup_loop()
    finally:
        locked.chmod(0o755)

    resp = await api_client.get("/api/system/backups", headers=AUTH_HEADERS)
    assert resp.json()["lastError"].startswith("PermissionError")
    assert str(tmp_path) not in resp.text


def test_error_paths_are_reduced_to_known_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backups = tmp_path / "backups"
    monkeypatch.setattr(settings, "backup_dir", str(backups))
    state = backup.BackupStatus()

    state.record_error(
        "database",
        PermissionError(13, "Permission denied", str(backups / "f.db.tmp")),
    )
    assert state.latest_error()[1] == (
        "PermissionError: Permission denied (BACKUP_DIR/f.db.tmp)"
    )

    state.record_error("database", RuntimeError(f"échec sur {tmp_path}/a/b.db"))
    message = state.latest_error()[1]
    assert str(tmp_path) not in message
    assert message.endswith("…/b.db")


def test_error_message_not_garbled_by_relative_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///fontsync.db")
    monkeypatch.setattr(settings, "backup_dir", ".")
    state = backup.BackupStatus()

    state.record_error(
        "database", sqlite3.OperationalError("unable to open database file")
    )

    assert state.latest_error()[1] == ("OperationalError: unable to open database file")


def test_error_whose_message_cannot_be_read_is_still_recorded() -> None:
    class Opaque(Exception):
        def __str__(self) -> str:
            raise ValueError("pas de message")

    state = backup.BackupStatus()
    state.record_error("database", Opaque())

    assert state.latest_error()[1] == "Opaque"


@pytest.mark.asyncio
async def test_mirror_error_survives_database_success(
    api_client: AsyncClient, backup_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup.status.record_error("mirror", RuntimeError("miroir en panne"))

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    with pytest.raises(asyncio.CancelledError):
        await backup.run_database_backup_loop()

    assert (await _get(api_client))["lastError"] == "RuntimeError: miroir en panne"


@pytest.mark.asyncio
async def test_mirror_success_clears_mirror_error(
    api_client: AsyncClient,
    backup_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backup.status.record_error("mirror", RuntimeError("miroir en panne"))
    (tmp_path / "fonts").mkdir()
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    monkeypatch.setattr(settings, "font_storage_path", str(tmp_path / "fonts"))

    async def _stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", _stop)
    with pytest.raises(asyncio.CancelledError):
        await backup.run_blob_backup_loop()

    assert (await _get(api_client))["lastError"] is None


def test_database_error_does_not_overwrite_mirror_error() -> None:
    state = backup.BackupStatus()
    state.record_error("mirror", RuntimeError("miroir en panne"))
    state.record_error("database", RuntimeError("base en panne"))

    assert state.latest_error()[1] == "RuntimeError: base en panne"
    state.record_success("database")

    assert state.latest_error()[1] == "RuntimeError: miroir en panne"


def test_openapi_version_follows_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import app

    monkeypatch.setattr(settings, "fontsync_version", "main+abc1234")
    assert app.openapi()["info"]["version"] == "main+abc1234"

    monkeypatch.setattr(settings, "fontsync_version", "")
    assert app.openapi()["info"]["version"] == "dev"
