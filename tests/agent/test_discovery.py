"""Tests de la découverte de fonts de l'agent (B11).

Couvrent le scan dossiers (`discover_via_directories`) — filtrage par extension,
patterns d'exclusion, déduplication des chemins, dossier inexistant ignoré,
récursion — ainsi que la logique de bascule de `discover_fonts` (Core Text puis
repli dossiers) et le repli silencieux de `discover_via_core_text` quand pyobjc
n'est pas disponible.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from agent import discovery
from agent.discovery import (
    DiscoveredFont,
    discover_fonts,
    discover_via_core_text,
    discover_via_directories,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"font")
    return path


def test_directories_collects_only_font_extensions(tmp_path: Path) -> None:
    _touch(tmp_path / "Inter.ttf")
    _touch(tmp_path / "Roboto.otf")
    _touch(tmp_path / "notes.txt")  # ignoré : pas une font
    _touch(tmp_path / "README.md")  # ignoré

    fonts = discover_via_directories([str(tmp_path)])

    names = sorted(f.filename for f in fonts)
    assert names == ["Inter.ttf", "Roboto.otf"]


def test_directories_extension_match_is_case_insensitive(tmp_path: Path) -> None:
    _touch(tmp_path / "Upper.TTF")

    fonts = discover_via_directories([str(tmp_path)])

    assert [f.filename for f in fonts] == ["Upper.TTF"]


def test_directories_recurses_subfolders(tmp_path: Path) -> None:
    _touch(tmp_path / "a" / "b" / "Deep.ttf")

    fonts = discover_via_directories([str(tmp_path)])

    assert [f.filename for f in fonts] == ["Deep.ttf"]


def test_directories_honors_ignore_patterns(tmp_path: Path) -> None:
    _touch(tmp_path / "Keep.ttf")
    _touch(tmp_path / ".DS_Store.ttf")
    _touch(tmp_path / "temp-Skip.ttf")

    fonts = discover_via_directories([str(tmp_path)], ignore_patterns=[".*", "temp-*"])

    assert [f.filename for f in fonts] == ["Keep.ttf"]


def test_directories_deduplicates_overlapping_inputs(tmp_path: Path) -> None:
    _touch(tmp_path / "Inter.ttf")

    # Le même dossier passé deux fois ne doit pas dédoubler la font.
    fonts = discover_via_directories([str(tmp_path), str(tmp_path)])

    assert len(fonts) == 1


def test_directories_skips_missing_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _touch(real / "Inter.ttf")
    missing = tmp_path / "does_not_exist"

    fonts = discover_via_directories([str(missing), str(real)])

    assert [f.filename for f in fonts] == ["Inter.ttf"]


def test_directories_expands_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(tmp_path / "Inter.ttf")
    monkeypatch.setenv("HOME", str(tmp_path))

    fonts = discover_via_directories(["~"])

    assert [f.filename for f in fonts] == ["Inter.ttf"]


def test_discover_fonts_falls_back_to_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Core Text vide → repli sur le scan dossiers."""
    _touch(tmp_path / "Inter.ttf")
    monkeypatch.setattr(discovery, "discover_via_core_text", lambda: [])

    fonts = discover_fonts([str(tmp_path)])

    assert [f.filename for f in fonts] == ["Inter.ttf"]


def test_discover_fonts_prefers_core_text_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Core Text non vide → le scan dossiers n'est pas exécuté."""
    _touch(tmp_path / "OnDisk.ttf")
    ct_result = [DiscoveredFont(path=Path("/Library/Fonts/X.ttf"), filename="X.ttf")]
    monkeypatch.setattr(discovery, "discover_via_core_text", lambda: ct_result)

    fonts = discover_fonts([str(tmp_path)])

    assert fonts == ct_result  # le dossier n'a pas été scanné


def test_discover_fonts_forced_directories_skips_core_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FONTSYNC_DISCOVERY=directories → Core Text court-circuité (simulation dev)."""
    _touch(tmp_path / "Inter.ttf")

    def _boom() -> list[DiscoveredFont]:
        raise AssertionError("Core Text ne doit pas être appelé en mode forcé")

    monkeypatch.setattr(discovery, "discover_via_core_text", _boom)
    monkeypatch.setenv("FONTSYNC_DISCOVERY", "directories")

    fonts = discover_fonts([str(tmp_path)])

    assert [f.filename for f in fonts] == ["Inter.ttf"]


def test_core_text_returns_empty_without_pyobjc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans pyobjc-framework-CoreText, la découverte Core Text renvoie [] (non bloquant)."""
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "CoreText":
            raise ImportError("simulated missing pyobjc")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    assert discover_via_core_text() == []
