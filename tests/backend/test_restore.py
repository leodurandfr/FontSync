"""Restauration d'un instantané de base (P1-2d).

La logique fichier de `scripts/restore-from-backup.sh` vit dans
`backend.maintenance.restore` pour être testée : poser un instantané à la
place de la base sans jamais rien supprimer, et sans laisser l'ancien journal
WAL se rejouer par-dessus (il annulerait la restauration en silence).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from backend import premigrate
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.maintenance import restore as restore_module
from backend.maintenance.restore import RestoreError, restore_snapshot
from backend.services.backup import write_snapshot
from backend.services.font_importer import import_font
from backend.services.storage import FilesystemStorage
from tests.backend.conftest import AUTH_HEADERS
from tests.backend.test_premigrate import _config


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count(db_path: Path, table: str = "rows") -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_restore_moves_stale_wal_aside(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    db = live / "fontsync.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO rows (v) VALUES (?)", [("x",)] * 3000)
    conn.commit()
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(db, snapshot)

    # Après l'instantané : -1500 / +2000, sans checkpoint, puis « crash » :
    # la base et son -wal sont copiés connexion ouverte.
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("DELETE FROM rows WHERE id <= 1500")
    conn.executemany("INSERT INTO rows (v) VALUES (?)", [("y",)] * 2000)
    conn.commit()
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    for suffix in ("", "-wal", "-shm"):
        shutil.copy2(f"{db}{suffix}", crashed / f"fontsync.db{suffix}")
    conn.close()
    stale_wal = _sha(crashed / "fontsync.db-wal")

    result = restore_snapshot(snapshot, crashed / "fontsync.db")

    assert _count(crashed / "fontsync.db") == 3000
    assert result.set_aside.parent == crashed
    assert result.set_aside.name.startswith("pre-restore-")
    assert _sha(result.set_aside / "fontsync.db-wal") == stale_wal
    assert not (crashed / "fontsync.db-wal").exists()


def test_restore_never_deletes_damaged_db(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    db.write_bytes(b"base abimee" * 1000)
    damaged = _sha(db)
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO rows DEFAULT VALUES")
    conn.commit()
    conn.close()
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    result = restore_snapshot(snapshot, db)

    assert _sha(result.set_aside / "fontsync.db") == damaged
    assert _count(db) == 1
    assert snapshot.exists()


def test_restore_refuses_invalid_snapshot_and_keeps_db(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    before = _sha(db)
    bogus = tmp_path / "fontsync-20260101-000000.db"
    bogus.write_bytes(b"pas une base" * 100)

    with pytest.raises(RestoreError):
        restore_snapshot(bogus, db)

    assert _sha(db) == before
    assert not list(tmp_path.glob("pre-restore-*"))


@pytest.fixture
def file_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "data" / "fontsync.db"
    db_path.parent.mkdir()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    command.upgrade(_config(), "head")
    return db_path


async def _import(
    db_path: Path, storage: FilesystemStorage, font_factory, names
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for name in names:
                await import_font(
                    f"{name}.ttf", font_factory(family=name), storage, session
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_restored_db_boots_app(
    file_db: Path, tmp_path: Path, font_factory, _api_token
) -> None:
    storage = FilesystemStorage(base_path=str(tmp_path / "fonts"))
    await _import(file_db, storage, font_factory, ["Alpha", "Beta", "Gamma"])
    snapshot = tmp_path / "backups" / "fontsync-20260101-000000.db"
    snapshot.parent.mkdir()
    write_snapshot(file_db, snapshot)
    await _import(file_db, storage, font_factory, ["Delta", "Epsilon"])
    assert _count(file_db, "fonts") == 5

    restore_snapshot(snapshot, file_db)

    assert premigrate.main() == 0
    engine = create_async_engine(f"sqlite+aiosqlite:///{file_db}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/stats", headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
    assert resp.status_code == 200
    assert resp.json()["totalFonts"] == 3


def _small_db(path: Path, rows: int = 1) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO rows DEFAULT VALUES", [()] * rows)
        conn.commit()
    finally:
        conn.close()


def test_restore_puts_everything_back_when_the_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db, rows=7)
    (tmp_path / "fontsync.db-wal").write_bytes(b"ancien wal")
    before = {
        name: _sha(tmp_path / name) for name in ("fontsync.db", "fontsync.db-wal")
    }
    source = tmp_path / "source.db"
    _small_db(source)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    def _disk_full(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(restore_module, "write_snapshot", _disk_full)
    with pytest.raises(OSError):
        restore_snapshot(snapshot, db)

    assert {name: _sha(tmp_path / name) for name in before} == before
    assert not list(tmp_path.glob("pre-restore-*"))


def test_restored_snapshot_copy_is_kept_aside(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    source = tmp_path / "source.db"
    _small_db(source, rows=3)
    conn = sqlite3.connect(source)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)
    # En-tête SQLite, octets 18-19 = 2 : instantané marqué WAL.
    assert snapshot.read_bytes()[18:20] == b"\x02\x02"

    result = restore_snapshot(snapshot, db)

    kept = result.set_aside / f"restored-{snapshot.name}"
    assert _sha(kept) == _sha(snapshot)
    assert not Path(f"{snapshot}-wal").exists()
    assert not Path(f"{snapshot}-shm").exists()


def test_main_check_does_not_touch_anything(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    before = _sha(db)
    source = tmp_path / "source.db"
    _small_db(source)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)
    bogus = tmp_path / "bogus.db"
    bogus.write_bytes(b"pas une base" * 50)

    assert restore_module.main([str(snapshot), "--check", "--db", str(db)]) == 0
    assert restore_module.main([str(bogus), "--check", "--db", str(db)]) == 1
    assert restore_module.main([str(bogus), "--db", str(db)]) == 1
    assert _sha(db) == before
    assert not list(tmp_path.glob("pre-restore-*"))


def test_main_restores_and_reports_incomplete_mirror(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    source = tmp_path / "source.db"
    _small_db(source, rows=4)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)
    mirror = tmp_path / "mirror"
    (mirror / "ab").mkdir(parents=True)
    (mirror / "ab" / "good.ttf").write_bytes(b"font")
    locked = mirror / "cd"
    locked.mkdir()
    (locked / "x.ttf").write_bytes(b"font")
    fonts = tmp_path / "fonts"

    import os

    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    locked.chmod(0)
    try:
        code = restore_module.main(
            [
                str(snapshot),
                "--db",
                str(db),
                "--fonts-from",
                str(mirror),
                "--fonts-to",
                str(fonts),
            ]
        )
    finally:
        locked.chmod(0o755)

    assert code == restore_module.EXIT_RESTORED_WITH_WARNINGS
    assert _count(db) == 4
    assert (fonts / "ab" / "good.ttf").read_bytes() == b"font"


def _devices_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT, auto_pull BOOLEAN, "
            "auto_push BOOLEAN, propagate_deletions BOOLEAN, deleted_at DATETIME)"
        )
        conn.executemany(
            "INSERT INTO devices VALUES (?, ?, 1, 1, 1, ?)",
            [("a", "Mac A", None), ("b", "Mac B (masqué)", "2026-11-01 00:00:00")],
        )
        conn.commit()
    finally:
        conn.close()


def test_restore_cuts_device_settings_in_the_restored_db(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    source = tmp_path / "source.db"
    _devices_db(source)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    result = restore_snapshot(snapshot, db)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT id, auto_pull, propagate_deletions, auto_push FROM devices ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("a", 0, 0, 1), ("b", 0, 0, 1)]
    assert {
        d["id"]: (d["auto_pull"], d["propagate_deletions"])
        for d in result.devices_before
    } == {
        "a": (1, 1),
        "b": (1, 1),
    }
    # L'instantané lui-même n'est pas modifié.
    conn = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True)
    try:
        assert conn.execute("SELECT sum(auto_pull) FROM devices").fetchone() == (2,)
    finally:
        conn.close()


def test_restore_shelters_daily_snapshots_from_rotation(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = data / "fontsync.db"
    _small_db(db)
    backups = tmp_path / "backups"
    backups.mkdir()
    source = tmp_path / "source.db"
    _small_db(source)
    chosen = backups / "fontsync-20260105-000000.db"
    write_snapshot(source, chosen)
    for day in ("01", "02", "03"):
        write_snapshot(source, backups / f"fontsync-202601{day}-000000.db")
    premigrate_snap = backups / "pre-migrate-abc-20260101-000000.db"
    write_snapshot(source, premigrate_snap)

    result = restore_snapshot(chosen, db, protect_backups=backups)

    assert result.protected is not None
    assert sorted(p.name for p in result.protected.iterdir()) == [
        "fontsync-20260101-000000.db",
        "fontsync-20260102-000000.db",
        "fontsync-20260103-000000.db",
    ]
    assert chosen.exists() and premigrate_snap.exists()
    assert not list(backups.glob("fontsync-2026010[123]-*.db"))


def test_main_reports_restored_when_a_later_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    source = tmp_path / "source.db"
    _small_db(source, rows=5)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    def _interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(restore_module, "mirror_blobs", _interrupted)
    code = restore_module.main(
        [str(snapshot), "--db", str(db), "--fonts-from", str(tmp_path / "mirror")]
    )

    assert code == restore_module.EXIT_RESTORED_WITH_WARNINGS
    assert _count(db) == 5
    assert "EST restaurée" in capsys.readouterr().err


def test_main_interrupted_copy_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db, rows=2)
    before = _sha(db)
    source = tmp_path / "source.db"
    _small_db(source, rows=5)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    def _interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(restore_module, "write_snapshot", _interrupted)
    code = restore_module.main([str(snapshot), "--db", str(db)])

    assert code == restore_module.EXIT_REFUSED
    assert _sha(db) == before
    assert "base inchangée" in capsys.readouterr().err


def test_main_reports_uncertain_state_when_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    source = tmp_path / "source.db"
    _small_db(source, rows=5)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)
    real_replace = os.replace

    def _flaky_replace(src: object, dst: object) -> None:
        source = Path(str(src))
        if source.parent.name.startswith("pre-restore-") and source.suffix != ".tmp":
            raise OSError(5, "Input/output error")
        real_replace(src, dst)

    monkeypatch.setattr(restore_module.os, "replace", _flaky_replace)
    code = restore_module.main([str(snapshot), "--db", str(db)])

    assert code == restore_module.EXIT_UNCERTAIN


def test_check_refuses_empty_database(tmp_path: Path) -> None:
    empty = tmp_path / "fontsync-20260101-000000.db"
    sqlite3.connect(empty).close()
    empty.write_bytes(empty.read_bytes() or b"")
    conn = sqlite3.connect(empty)
    conn.execute("PRAGMA user_version = 1")
    conn.close()

    assert restore_module.main([str(empty), "--check"]) == restore_module.EXIT_REFUSED


def test_restore_moves_shm_aside_and_refuses_self(tmp_path: Path) -> None:
    db = tmp_path / "fontsync.db"
    _small_db(db)
    Path(f"{db}-shm").write_bytes(b"ancien shm")
    source = tmp_path / "source.db"
    _small_db(source)
    snapshot = tmp_path / "fontsync-20260101-000000.db"
    write_snapshot(source, snapshot)

    with pytest.raises(RestoreError):
        restore_snapshot(db, db)
    result = restore_snapshot(snapshot, db)

    assert (result.set_aside / "fontsync.db-shm").read_bytes() == b"ancien shm"
    assert not Path(f"{db}-shm").exists()
