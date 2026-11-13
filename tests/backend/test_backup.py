"""Sauvegarde automatique : instantané de la base + miroir des polices.

`backup_database` et `mirror_blobs` sont testées comme des fonctions pures
(chemins en paramètre, comme `purge_expired` prend `storage`/`db`) : la
boucle de planification (`run_*_backup_loop`) ne fait que les brancher sur
`backend.config.settings`, elle n'a pas de logique propre à vérifier.
"""

from __future__ import annotations

import hashlib
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

    copied = mirror_blobs(source, dest).copied

    assert copied == 1
    assert (dest / "ab" / "abcdef.ttf").read_bytes() == b"font-bytes"


def test_mirror_blobs_is_incremental_and_skips_same_size_copies(tmp_path) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    (source / "ab").mkdir(parents=True)
    (source / "ab" / "abcdef.ttf").write_bytes(b"original")

    first = mirror_blobs(source, dest).copied
    assert first == 1

    # Une copie déjà présente et de même taille n'est jamais relue, même si le
    # contenu source a changé entre-temps — write-once, comme le stockage réel.
    (source / "ab" / "abcdef.ttf").write_bytes(b"tampered")
    (source / "cd").mkdir()
    (source / "cd" / "newfont.ttf").write_bytes(b"new")

    second = mirror_blobs(source, dest).copied

    assert second == 1
    assert (dest / "ab" / "abcdef.ttf").read_bytes() == b"original"
    assert (dest / "cd" / "newfont.ttf").read_bytes() == b"new"


def test_mirror_blobs_on_missing_source_returns_zero(tmp_path) -> None:
    assert mirror_blobs(tmp_path / "does-not-exist", tmp_path / "backups").copied == 0


# ---------- Atomicité et robustesse (P1-2a) ----------


@pytest.mark.asyncio
async def test_failed_snapshot_leaves_no_file(tmp_path) -> None:
    """A source that is not a SQLite database: no snapshot, no leftover."""
    source = tmp_path / "not-a-db.db"
    source.write_bytes(b"this is not sqlite" * 100)
    dest = tmp_path / "backups"

    with pytest.raises(Exception):
        await backup_database(source, dest)

    leftovers = sorted(p.name for p in dest.iterdir()) if dest.exists() else []
    assert leftovers == []


@pytest.mark.asyncio
async def test_empty_source_is_refused(tmp_path) -> None:
    """An empty database (no table) passes integrity_check: it must be refused."""
    source = tmp_path / "empty.db"
    sqlite3.connect(str(source)).close()
    dest = tmp_path / "backups"

    with pytest.raises(RuntimeError):
        await backup_database(source, dest)
    assert not list(dest.glob("fontsync-*"))


def test_rotation_keeps_newest_with_same_second_suffix(tmp_path) -> None:
    for name in (
        "fontsync-20261101-120000.db",
        "fontsync-20261101-120000-1.db",
        "fontsync-20261101-120000-2.db",
    ):
        (tmp_path / name).write_bytes(b"x")

    _rotate_snapshots(tmp_path, keep=2)

    assert sorted(p.name for p in tmp_path.glob("fontsync-*.db")) == [
        "fontsync-20261101-120000-1.db",
        "fontsync-20261101-120000-2.db",
    ]


def test_rotation_removes_orphan_temporary_files(tmp_path) -> None:
    (tmp_path / "fontsync-20261101-120000.db").write_bytes(b"x")
    (tmp_path / "fontsync-20261101-130000.db.tmp").write_bytes(b"partial")
    (tmp_path / "fontsync-20261101-130000.db.tmp-journal").write_bytes(b"j")

    _rotate_snapshots(tmp_path, keep=5)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["fontsync-20261101-120000.db"]


def _blob_tree(source: Path, font_factory, count: int) -> list[Path]:
    paths = []
    for i in range(count):
        data = font_factory(family=f"Mirror{i}")
        digest = hashlib.sha256(data).hexdigest()
        path = source / digest[:2] / f"{digest}.ttf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        paths.append(path)
    return paths


def test_mirror_continues_past_unreadable_blob(tmp_path, font_factory) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("root reads chmod 000 files")
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    blobs = _blob_tree(source, font_factory, 30)
    blobs[9].chmod(0)
    try:
        result = mirror_blobs(source, dest)
    finally:
        blobs[9].chmod(0o644)

    assert result.copied == 29
    assert result.failed == 1
    assert not (dest / blobs[9].relative_to(source)).exists()


def test_mirror_repairs_truncated_copy(tmp_path, font_factory) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    (blob,) = _blob_tree(source, font_factory, 1)
    mirror_blobs(source, dest)
    copy = dest / blob.relative_to(source)
    copy.write_bytes(blob.read_bytes()[:100])

    result = mirror_blobs(source, dest)

    assert result.repaired == 1
    assert copy.read_bytes() == blob.read_bytes()


def test_no_tmp_left_after_success(tmp_path, font_factory) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    _blob_tree(source, font_factory, 5)

    mirror_blobs(source, dest)

    assert not [p for p in dest.rglob("*") if p.name.endswith(".tmp")]


@pytest.mark.asyncio
async def test_no_tmp_left_after_successful_snapshot(tmp_path) -> None:
    source = tmp_path / "source.db"
    _make_sqlite_db(source)
    dest = tmp_path / "backups"

    await backup_database(source, dest)

    assert not [p for p in dest.iterdir() if ".tmp" in p.name]


def test_mirror_never_repairs_from_a_source_that_fails_its_hash(
    tmp_path, font_factory
) -> None:
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    (blob,) = _blob_tree(source, font_factory, 1)
    mirror_blobs(source, dest)
    good = blob.read_bytes()
    copy = dest / blob.relative_to(source)
    # Source abîmée (écriture en cours, disque corrompu) : taille différente,
    # contenu qui ne correspond plus au nom.
    blob.write_bytes(good[:100])

    result = mirror_blobs(source, dest)

    assert result.repaired == 0
    assert result.failed == 1
    assert copy.read_bytes() == good


def test_mirror_counts_unreadable_directory(tmp_path, font_factory) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    source = tmp_path / "fonts"
    dest = tmp_path / "backups" / "fonts"
    blobs = _blob_tree(source, font_factory, 3)
    locked = blobs[0].parent
    locked.chmod(0)
    try:
        result = mirror_blobs(source, dest)
    finally:
        locked.chmod(0o755)

    assert result.failed >= 1
    assert result.copied == len({b.parent for b in blobs} - {locked})


def test_rotation_removes_orphan_wal_and_shm(tmp_path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    for suffix in ("", "-journal", "-wal", "-shm"):
        (backups / f"fontsync-20260101-000000.db.tmp{suffix}").write_bytes(b"x")
    kept = backups / "fontsync-20260101-000000.db"
    kept.write_bytes(b"x")

    _rotate_snapshots(backups, keep=14)

    assert sorted(p.name for p in backups.iterdir()) == [kept.name]


@pytest.mark.asyncio
async def test_snapshot_of_wal_source_leaves_no_sidecar(tmp_path) -> None:
    source = tmp_path / "fontsync.db"
    conn = sqlite3.connect(source)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE fonts (id INTEGER PRIMARY KEY)")
    conn.commit()
    try:
        snapshot = await backup_database(source, tmp_path / "backups")
    finally:
        conn.close()

    assert sorted(p.name for p in snapshot.parent.iterdir()) == [snapshot.name]
