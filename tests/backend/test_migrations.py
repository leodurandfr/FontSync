"""Un `alembic upgrade head` doit produire le schéma que l'ORM décrit.

Les migrations ne sont exercées par aucun autre test (`conftest.py` construit
la base des tests via `Base.metadata.create_all`, jamais via Alembic) et ne
tournent qu'au démarrage réel du conteneur : leur première exécution a
aujourd'hui lieu en production. C'est le seul garde-fou contre une révision qui
diverge en silence du modèle ORM qu'elle prétend refléter (cf.
`docs/PLAN-ETATS-FONTS.md` §7.5).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from backend.config import settings
from backend.models import Base

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_head(db_path: Path, monkeypatch) -> None:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    # `alembic/env.py` lit `settings.database_url` au moment de l'exécution :
    # le faire pointer vers la base jetable du test le temps de la migration.
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _columns(inspector, table: str) -> set[tuple[str, str, bool]]:
    return {
        (c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(table)
    }


def _indexes(inspector, table: str) -> set[tuple[str, tuple[str, ...], bool]]:
    return {
        (idx["name"], tuple(idx["column_names"]), idx["unique"])
        for idx in inspector.get_indexes(table)
    }


def _foreign_keys(inspector, table: str) -> set[tuple]:
    return {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
        )
        for fk in inspector.get_foreign_keys(table)
    }


def test_alembic_head_matches_orm_metadata(tmp_path, monkeypatch) -> None:
    """Colonnes, types, nullabilité, index et contraintes uniques : identiques."""
    migrated_path = tmp_path / "migrated.db"
    _upgrade_head(migrated_path, monkeypatch)
    migrated_inspector = inspect(create_engine(f"sqlite:///{migrated_path}"))

    reference_path = tmp_path / "reference.db"
    reference_engine = create_engine(f"sqlite:///{reference_path}")
    Base.metadata.create_all(reference_engine)
    reference_inspector = inspect(reference_engine)

    reference_tables = set(reference_inspector.get_table_names())
    migrated_tables = set(migrated_inspector.get_table_names()) - {"alembic_version"}
    assert migrated_tables == reference_tables

    for table in sorted(reference_tables):
        assert _columns(migrated_inspector, table) == _columns(
            reference_inspector, table
        ), f"colonnes divergentes sur {table}"
        assert _indexes(migrated_inspector, table) == _indexes(
            reference_inspector, table
        ), f"index divergents sur {table}"
        assert migrated_inspector.get_unique_constraints(
            table
        ) == reference_inspector.get_unique_constraints(table), (
            f"contraintes uniques divergentes sur {table}"
        )
        assert _foreign_keys(migrated_inspector, table) == _foreign_keys(
            reference_inspector, table
        ), f"clés étrangères divergentes sur {table}"


def test_upgrade_keeps_app_loggers_enabled(tmp_path, monkeypatch) -> None:
    """`alembic upgrade` in-process must not disable the app's existing loggers."""
    import logging

    import backend.auth  # noqa: F401  (creates the "backend.auth" logger)

    logger = logging.getLogger("backend.auth")
    assert logger.disabled is False
    _upgrade_head(tmp_path / "loggers.db", monkeypatch)
    assert logging.getLogger("backend.auth").disabled is False


def _upgrade_to(db_path: Path, monkeypatch, revision: str) -> None:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(cfg, revision)


def test_upgrade_drops_associations_to_active_web_fonts(tmp_path, monkeypatch) -> None:
    """Old pulls registered WOFF/WOFF2 as held: drop those rows, never tombstones'."""
    import sqlite3

    db_path = tmp_path / "woff.db"
    _upgrade_to(db_path, monkeypatch, "a43134c85b44")

    device = "d" * 32
    fonts = {
        # id: (file_format, deleted_at)
        "a" * 32: ("woff", None),
        "b" * 32: ("WOFF2", None),
        "c" * 32: ("woff", "2026-10-01 00:00:00"),
        "e" * 32: ("ttf", None),
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO devices (id, name, hostname, os, auto_pull, auto_push) "
            "VALUES (?, 'Mac', 'mac', 'macos', 1, 1)",
            (device,),
        )
        for font_id, (fmt, deleted_at) in fonts.items():
            conn.execute(
                "INSERT INTO fonts (id, file_hash, original_filename, file_size, "
                "file_format, is_italic, is_oblique, is_variable, source, deleted_at) "
                "VALUES (?, ?, ?, 1, ?, 0, 0, 0, 'upload', ?)",
                (font_id, font_id * 2, f"{font_id[:4]}.{fmt.lower()}", fmt, deleted_at),
            )
            conn.execute(
                "INSERT INTO device_fonts (device_id, font_id, local_path) "
                "VALUES (?, ?, 'x')",
                (device, font_id),
            )

    _upgrade_head(db_path, monkeypatch)

    with sqlite3.connect(db_path) as conn:
        kept = {row[0] for row in conn.execute("SELECT font_id FROM device_fonts")}
        font_count = conn.execute("SELECT count(*) FROM fonts").fetchone()[0]
    # Active web fonts lose their association; the WOFF tombstone and the TTF keep theirs.
    assert kept == {"c" * 32, "e" * 32}
    assert font_count == 4


def test_harvested_fingerprints_upgrade_downgrade(tmp_path, monkeypatch) -> None:
    """M-29 : la table d'empreintes s'ajoute et se retire sans toucher aux
    données existantes (le downgrade est le chemin de retour de P1-2d)."""
    import sqlite3

    db_path = tmp_path / "fingerprints.db"
    _upgrade_to(db_path, monkeypatch, "5e2b7c9d1f40")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fonts (id, file_hash, original_filename, file_size, "
            "file_format, is_italic, is_oblique, is_variable, source) "
            "VALUES (?, ?, 'kept.ttf', 1, 'ttf', 0, 0, 0, 'upload')",
            ("f" * 32, "h" * 64),
        )

    _upgrade_head(db_path, monkeypatch)
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "harvested_fingerprints" in tables
        conn.execute(
            "INSERT INTO harvested_fingerprints (id, file_hash, harvested_at) "
            "VALUES (?, ?, '2026-11-13 00:00:00')",
            ("e" * 32, "g" * 64),
        )
        assert conn.execute("SELECT count(*) FROM fonts").fetchone()[0] == 1

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    command.downgrade(cfg, "5e2b7c9d1f40")
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert "harvested_fingerprints" not in tables
        assert conn.execute("SELECT file_hash FROM fonts").fetchall() == [("h" * 64,)]
