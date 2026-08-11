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
