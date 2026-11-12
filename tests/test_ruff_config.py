"""Regression tests for the explicit ruff setup (lint baseline L0).

The lint baseline must not depend on whatever ruff version happens to be
installed nor on its moving default rule set: `pyproject.toml` declares the
rule set explicitly and `requirements-dev.txt` pins ruff.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_DEV = REPO_ROOT / "requirements-dev.txt"
RUFF_PIN = re.compile(r"^\s*ruff\s*==\s*\d+\.\d+\.\d+\s*(#.*)?$", re.MULTILINE)


def _ruff_lint_section() -> dict[str, Any]:
    """Return `[tool.ruff.lint]` from pyproject.toml (empty dict if missing)."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("ruff", {}).get("lint", {})


def test_pyproject_declares_explicit_ruff_rule_set() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    ruff = data.get("tool", {}).get("ruff")
    assert ruff is not None, "pyproject.toml has no [tool.ruff] section"
    assert ruff.get("target-version") == "py312", (
        f"[tool.ruff] target-version must be 'py312', got {ruff.get('target-version')!r}"
    )

    lint = _ruff_lint_section()
    assert lint, "pyproject.toml has no [tool.ruff.lint] section"
    select = lint.get("select")
    assert isinstance(select, list) and select, (
        f"[tool.ruff.lint] must declare an explicit, non-empty `select`, got {select!r}"
    )
    # Sorted imports are a project rule: I001 is fixed, never ignored.
    assert any("I001".startswith(code) for code in select), (
        f"[tool.ruff.lint] select must enable I001 (sorted imports), got {select!r}"
    )
    ignored = [*lint.get("ignore", []), *lint.get("extend-ignore", [])]
    assert not any("I001".startswith(code) for code in ignored), (
        f"I001 must not be ignored, got ignore/extend-ignore {ignored!r}"
    )


def test_requirements_dev_pins_ruff() -> None:
    assert REQUIREMENTS_DEV.is_file(), "requirements-dev.txt is missing"
    content = REQUIREMENTS_DEV.read_text(encoding="utf-8")
    assert RUFF_PIN.search(content), (
        "requirements-dev.txt must pin ruff to an exact version (ruff==X.Y.Z)"
    )


def test_ruff_check_is_clean() -> None:
    if importlib.util.find_spec("ruff") is None:
        pytest.skip("ruff is not installed (pip install -r requirements-dev.txt)")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "backend",
            "agent",
            "tests",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"`ruff check backend agent tests` failed (exit {result.returncode}):\n"
        f"{result.stdout[-4000:]}{result.stderr[-2000:]}"
    )
