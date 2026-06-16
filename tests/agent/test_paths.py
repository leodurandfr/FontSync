"""Tests de la résolution de chemins surchargeable par l'environnement.

`FONTSYNC_HOME` (état) et `FONTSYNC_FONTS_DIR` (dossier d'install) permettent
d'isoler un device simulé en dev ; non définis → chemins de production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.paths import fonts_dir, state_dir


def test_state_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FONTSYNC_HOME", raising=False)
    assert state_dir() == Path.home() / ".fontsync"


def test_state_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FONTSYNC_HOME", str(tmp_path / "devA"))
    assert state_dir() == tmp_path / "devA"


def test_fonts_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FONTSYNC_FONTS_DIR", raising=False)
    assert fonts_dir() == Path.home() / "Library" / "Fonts"


def test_fonts_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FONTSYNC_FONTS_DIR", str(tmp_path / "devA" / "fonts"))
    assert fonts_dir() == tmp_path / "devA" / "fonts"


def test_override_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FONTSYNC_HOME", "~/some-dev-home")
    assert state_dir() == Path.home() / "some-dev-home"
