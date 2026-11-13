"""Contrôles avant `alembic upgrade head` dans l'entrypoint (P1-2c).

Une migration ratée en production ne laissait aucun point de retour : la
boucle de sauvegarde ne démarre qu'après, dans le lifespan. `premigrate`
prend un instantané avant toute migration en attente, répare une migration
SQLite interrompue (`_alembic_tmp_*`) quand c'est sans danger, et refuse
explicitement une base plus récente que l'image.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from backend import premigrate
from backend.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _previous() -> str:
    script = ScriptDirectory.from_config(_config())
    return script.get_revision(script.get_current_head()).down_revision


@pytest.fixture
def db_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "data" / "fontsync.db"
    db_path.parent.mkdir()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path / "backups"))
    return db_path


def _upgrade(revision: str) -> None:
    command.upgrade(_config(), revision)


def _snapshots(directory: Path) -> list[Path]:
    return sorted(directory.glob("pre-migrate-*.db")) if directory.is_dir() else []


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_nothing_to_do_without_database(db_env: Path, tmp_path: Path) -> None:
    assert premigrate.main() == 0
    assert not db_env.exists()
    assert _snapshots(tmp_path / "backups") == []


def test_snapshot_taken_when_migration_pending(db_env: Path, tmp_path: Path) -> None:
    previous = _previous()
    _upgrade(previous)

    assert premigrate.main() == 0

    (snapshot,) = _snapshots(tmp_path / "backups")
    assert snapshot.name.startswith(f"pre-migrate-{previous}-")
    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            previous,
        )
    finally:
        conn.close()
    assert not list((tmp_path / "backups").glob("*.tmp*"))


def test_snapshot_next_to_database_without_backup_dir(
    db_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "backup_dir", "")
    _upgrade(_previous())

    assert premigrate.main() == 0

    assert len(_snapshots(db_env.parent)) == 1


def test_no_snapshot_when_up_to_date(db_env: Path, tmp_path: Path) -> None:
    _upgrade("head")

    assert premigrate.main() == 0

    assert _snapshots(tmp_path / "backups") == []
    assert _snapshots(db_env.parent) == []


def test_unknown_revision_exits_with_message(
    db_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _upgrade("head")
    conn = sqlite3.connect(db_env)
    conn.execute("UPDATE alembic_version SET version_num = 'ffffffffffff'")
    conn.commit()
    conn.close()
    before = _sha(db_env)

    code = premigrate.main()

    assert code != 0
    assert "ffffffffffff" in capsys.readouterr().err
    assert _sha(db_env) == before
    assert _snapshots(tmp_path / "backups") == []


def test_alembic_tmp_dropped_when_original_intact(db_env: Path, tmp_path: Path) -> None:
    _upgrade("head")
    conn = sqlite3.connect(db_env)
    conn.execute("CREATE TABLE _alembic_tmp_device_fonts AS SELECT * FROM device_fonts")
    conn.commit()
    conn.close()

    assert premigrate.main() == 0

    conn = sqlite3.connect(db_env)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "_alembic_tmp_device_fonts" not in tables
    assert "device_fonts" in tables
    # L'instantané précède le DROP : il contient encore la table temporaire.
    (snapshot,) = _snapshots(tmp_path / "backups")
    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='_alembic_tmp_device_fonts'"
        ).fetchone() == (1,)
    finally:
        conn.close()
    _upgrade("head")


def test_alembic_tmp_without_original_aborts_untouched(
    db_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _upgrade("head")
    conn = sqlite3.connect(db_env)
    conn.execute("CREATE TABLE _alembic_tmp_device_fonts AS SELECT * FROM device_fonts")
    conn.execute("DROP TABLE device_fonts")
    conn.commit()
    conn.close()
    before = _sha(db_env)

    code = premigrate.main()

    assert code != 0
    assert "_alembic_tmp_device_fonts" in capsys.readouterr().err
    assert _sha(db_env) == before
    assert _snapshots(tmp_path / "backups") == []


def test_snapshot_failure_aborts(
    db_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    _upgrade(_previous())
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setattr(settings, "backup_dir", str(locked))
    try:
        code = premigrate.main()
    finally:
        locked.chmod(0o755)

    assert code != 0
    assert list(locked.iterdir()) == []


def test_wal_database_snapshot_includes_uncheckpointed_rows(
    db_env: Path, tmp_path: Path
) -> None:
    _upgrade(_previous())
    writer = sqlite3.connect(db_env)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE probe (x TEXT)")
        writer.execute("INSERT INTO probe VALUES ('dans le WAL')")
        writer.commit()
        assert Path(f"{db_env}-wal").stat().st_size > 0

        assert premigrate.main() == 0
    finally:
        writer.close()

    (snapshot,) = _snapshots(tmp_path / "backups")
    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute("SELECT x FROM probe").fetchone() == ("dans le WAL",)
    finally:
        conn.close()


def test_hot_journal_is_rolled_back_not_fatal(db_env: Path, tmp_path: Path) -> None:
    import subprocess
    import sys

    _upgrade(_previous())
    crash = (
        "import os, sqlite3, sys\n"
        "c = sqlite3.connect(sys.argv[1])\n"
        "c.execute('PRAGMA journal_mode=DELETE')\n"
        "c.execute('PRAGMA cache_size=1')\n"
        "c.execute('BEGIN')\n"
        "c.execute('CREATE TABLE big (x)')\n"
        "for _ in range(2000):\n"
        "    c.execute('INSERT INTO big VALUES (randomblob(500))')\n"
        "os._exit(9)\n"
    )
    subprocess.run([sys.executable, "-c", crash, str(db_env)], check=False)
    assert Path(f"{db_env}-journal").exists()

    assert premigrate.main() == 0

    (snapshot,) = _snapshots(tmp_path / "backups")
    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'big'"
        ).fetchall()
    finally:
        conn.close()


def test_unreadable_database_exits_with_message(
    db_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_env.write_bytes(b"ceci n'est pas une base SQLite" * 100)

    assert premigrate.main() == premigrate.EXIT_UNREADABLE
    assert "base illisible" in capsys.readouterr().err


def test_failing_migration_loop_stops_snapshotting(
    db_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import os
    import time

    previous = _previous()
    _upgrade(previous)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = time.time() - 25 * 3600
    stale = backups / f"pre-migrate-{previous}-20260101-000000.db"
    stale.write_bytes(b"x")
    os.utime(stale, (old, old))

    for _ in range(premigrate.MAX_SNAPSHOTS_PER_DAY):
        assert premigrate.main() == 0
    before = _sha(db_env)
    count = len(_snapshots(backups))

    assert premigrate.main() == premigrate.EXIT_RETRY_LIMIT

    assert len(_snapshots(backups)) == count
    assert _sha(db_env) == before
    assert "en boucle" in capsys.readouterr().err


def test_truncated_temp_name_of_long_table_is_not_an_orphan(
    db_env: Path, tmp_path: Path
) -> None:
    _upgrade("head")
    long_name = "a_rather_long_table_name_for_alembic_batch"
    temp_name = f"_alembic_tmp_{long_name}"[:50]
    conn = sqlite3.connect(db_env)
    conn.execute(f"CREATE TABLE {long_name} (x)")
    conn.execute(f"CREATE TABLE {temp_name} (x)")
    conn.commit()
    conn.close()

    assert premigrate.main() == 0

    conn = sqlite3.connect(db_env)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()
    assert temp_name not in names
    assert long_name in names
