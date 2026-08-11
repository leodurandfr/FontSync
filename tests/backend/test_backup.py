"""Sauvegarde automatique : instantané de la base + miroir des polices.

`backup_database` et `mirror_blobs` sont testées comme des fonctions pures
(chemins en paramètre, comme `purge_expired` prend `storage`/`db`) : la
boucle de planification (`run_*_backup_loop`) ne fait que les brancher sur
`backend.config.settings`, elle n'a pas de logique propre à vérifier.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.services.backup import _rotate_snapshots, backup_database, mirror_blobs


def _make_sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE fonts (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO fonts VALUES ('1', 'Inter')")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backup_database_produces_a_valid_readable_snapshot(tmp_path) -> None:
    source = tmp_path / "fontsync.db"
    _make_sqlite_db(source)

    snapshot = await backup_database(source, tmp_path / "backups")

    assert snapshot.exists()
    conn = sqlite3.connect(str(snapshot))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT name FROM fonts WHERE id = '1'").fetchone() == (
            "Inter",
        )
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backup_database_names_snapshots_by_timestamp(tmp_path) -> None:
    source = tmp_path / "fontsync.db"
    _make_sqlite_db(source)

    snapshot = await backup_database(source, tmp_path / "backups")

    assert snapshot.parent == tmp_path / "backups"
    assert snapshot.name.startswith("fontsync-")
    assert snapshot.suffix == ".db"


def test_rotate_snapshots_keeps_only_the_most_recent(tmp_path) -> None:
    names = [
        "fontsync-20260101-030000.db",
        "fontsync-20260102-030000.db",
        "fontsync-20260103-030000.db",
        "fontsync-20260104-030000.db",
    ]
    for name in names:
        (tmp_path / name).write_bytes(b"")

    _rotate_snapshots(tmp_path, keep=2)

    remaining = sorted(p.name for p in tmp_path.glob("fontsync-*.db"))
    assert remaining == names[-2:]


def test_rotate_snapshots_disabled_when_keep_is_zero(tmp_path) -> None:
    (tmp_path / "fontsync-20260101-030000.db").write_bytes(b"")
    (tmp_path / "fontsync-20260102-030000.db").write_bytes(b"")

    _rotate_snapshots(tmp_path, keep=0)

    assert len(list(tmp_path.glob("fontsync-*.db"))) == 2


def test_mirror_blobs_copies_missing_files(tmp_path) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    (source / "ab").mkdir(parents=True)
    (source / "ab" / "abcdef.ttf").write_bytes(b"font-bytes")

    copied = mirror_blobs(source, dest)

    assert copied == 1
    assert (dest / "ab" / "abcdef.ttf").read_bytes() == b"font-bytes"


def test_mirror_blobs_is_incremental_and_never_overwrites(tmp_path) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    (source / "ab").mkdir(parents=True)
    (source / "ab" / "abcdef.ttf").write_bytes(b"original")

    first = mirror_blobs(source, dest)
    assert first == 1

    # Le miroir ne relit jamais un fichier déjà présent, même si son contenu
    # côté source a changé entre-temps — write-once, comme le stockage réel.
    (source / "ab" / "abcdef.ttf").write_bytes(b"tampered")
    (source / "cd").mkdir()
    (source / "cd" / "newfont.ttf").write_bytes(b"new")

    second = mirror_blobs(source, dest)

    assert second == 1
    assert (dest / "ab" / "abcdef.ttf").read_bytes() == b"original"
    assert (dest / "cd" / "newfont.ttf").read_bytes() == b"new"


def test_mirror_blobs_on_missing_source_returns_zero(tmp_path) -> None:
    assert mirror_blobs(tmp_path / "does-not-exist", tmp_path / "backups") == 0
