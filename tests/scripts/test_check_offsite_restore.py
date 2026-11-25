"""`scripts/check-offsite-restore.sh` (P1-2f, H-01) : le contrôle échoue sur une
restauration vide ou abîmée, et passe sur une restauration plausible."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-offsite-restore.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("sqlite3") is None, reason="sqlite3 CLI absent"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def _restore(root: Path, live: int, files: int) -> Path:
    snaps = root / "fontsync-backups"
    snaps.mkdir(parents=True)
    db = sqlite3.connect(snaps / "fontsync-20261125.db")
    db.executescript(
        "CREATE TABLE alembic_version (version_num TEXT);"
        "INSERT INTO alembic_version VALUES ('b5d2e8f1c3a7');"
        "CREATE TABLE fonts (id TEXT, deleted_at TEXT, purged_at TEXT);"
    )
    db.executemany(
        "INSERT INTO fonts VALUES (?, NULL, NULL)", [(str(i),) for i in range(live)]
    )
    db.commit()
    db.close()
    mirror = root / "mirror" / "ab"
    mirror.mkdir(parents=True)
    for i in range(files):
        (mirror / f"ab{i:04d}.ttf").write_bytes(b"\0")
    return root


def test_fails_on_empty_folder(tmp_path: Path) -> None:
    result = _run(str(tmp_path))
    assert result.returncode == 1
    assert "aucun instantané" in result.stdout


def test_passes_on_plausible_restore(tmp_path: Path) -> None:
    root = _restore(tmp_path, live=10, files=10)
    result = _run(str(root), "10")
    assert result.returncode == 0, result.stdout


def test_fails_when_counts_drift_from_prod(tmp_path: Path) -> None:
    root = _restore(tmp_path, live=10, files=10)
    result = _run(str(root), "200")
    assert result.returncode == 1
    assert "écart avec la prod" in result.stdout


def test_fails_without_font_mirror(tmp_path: Path) -> None:
    root = _restore(tmp_path, live=10, files=0)
    result = _run(str(root))
    assert result.returncode == 1
    assert "miroir" in result.stdout


def test_fails_on_corrupt_snapshot(tmp_path: Path) -> None:
    snaps = tmp_path / "b"
    snaps.mkdir()
    (snaps / "broken.db").write_bytes(b"not a database" * 100)
    result = _run(str(tmp_path))
    assert result.returncode == 1
