"""ARCHITECTURE.md §4.1 décrit le schéma que l'ORM définit (M-12, B-54).

Chaque table documentée par un tableau de colonnes dans §4.1 doit lister
exactement les colonnes du modèle, dans les deux sens : une colonne retirée
(`storage_path`, `deleted_reason`…) ne doit pas y survivre, une colonne ajoutée
(`full_declaration_since`…) doit y apparaître.

Exceptions assumées : les tables résumées ailleurs en une ligne (§4.2 familles,
§4.6 comptes) ne sont pas des tableaux de colonnes complets.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import backend.models as models_pkg
from backend.models.base import Base

ROOT = Path(__file__).resolve().parents[1]

for _mod in pkgutil.iter_modules(models_pkg.__path__):
    importlib.import_module(f"backend.models.{_mod.name}")


def _section_4_1() -> str:
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    start = text.index("### 4.1 MVP tables")
    end = text.index("### 4.2", start)
    return text[start:end]


def _documented_tables() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    current: str | None = None
    for line in _section_4_1().splitlines():
        heading = re.match(r"^#### `([a-z_]+)`", line)
        if heading:
            current = heading.group(1)
            tables[current] = set()
            continue
        row = re.match(r"^\| `([a-z_]+)` \|", line)
        if current and row:
            tables[current].add(row.group(1))
    return tables


def test_section_documents_tables() -> None:
    documented = _documented_tables()
    assert {"fonts", "devices", "device_fonts"} <= set(documented)
    for name in documented:
        assert name in Base.metadata.tables, (
            f"§4.1 documente une table inconnue : {name}"
        )


@pytest.mark.parametrize("table", sorted(_documented_tables()))
def test_documented_columns_match_orm(table: str) -> None:
    documented = _documented_tables()[table]
    actual = {c.name for c in Base.metadata.tables[table].columns}
    assert documented - actual == set(), (
        f"{table} : colonnes documentées absentes de l'ORM"
    )
    assert actual - documented == set(), f"{table} : colonnes de l'ORM absentes de §4.1"
