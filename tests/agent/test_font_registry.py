"""Tests de la prise en compte système des fonts (`agent/font_registry.py`).

Le module agit sur la session macOS réelle : on ne teste donc **jamais** l'effet
lui-même, seulement le contrat qui l'encadre —

- les gardes (plateforme, `FONTSYNC_NO_REINDEX`, dossier non système) qui
  empêchent de toucher l'index d'une machine de dev ou de CI ;
- le fait que la réindexation est bien déclenchée quand la cible *est* le vrai
  ~/Library/Fonts, avec la bonne commande ;
- son caractère non bloquant : `killall` absent ou en échec ne lève jamais.

`subprocess.run` est systématiquement remplacé — aucun processus n'est tué.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent import font_registry


@pytest.fixture
def system_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fait passer `tmp_path` pour le vrai dossier de polices utilisateur."""
    monkeypatch.setattr(font_registry, "_SYSTEM_USER_FONTS_DIR", tmp_path)
    monkeypatch.delenv("FONTSYNC_NO_REINDEX", raising=False)
    monkeypatch.setattr(font_registry.sys, "platform", "darwin")
    return tmp_path


@pytest.fixture
def killall_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture les appels `subprocess.run` au lieu de les exécuter."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(font_registry.subprocess, "run", fake_run)
    return calls


def test_reindex_kills_font_services(
    system_dir: Path, killall_calls: list[list[str]]
) -> None:
    """Sur le vrai dossier de polices : `killall fontd fontworker`."""
    assert font_registry.reindex(system_dir) is True
    assert killall_calls == [["/usr/bin/killall", "fontd", "fontworker"]]


def test_reindex_skipped_for_non_system_dir(
    system_dir: Path, tmp_path: Path, killall_calls: list[list[str]]
) -> None:
    """Un device simulé (`FONTSYNC_FONTS_DIR`) ne perturbe pas la vraie session."""
    simulated = tmp_path / "device-2" / "Fonts"
    simulated.mkdir(parents=True)

    assert font_registry.reindex(simulated) is False
    assert killall_calls == []


def test_reindex_skipped_when_disabled_by_env(
    system_dir: Path, killall_calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FONTSYNC_NO_REINDEX", "1")

    assert font_registry.reindex(system_dir) is False
    assert killall_calls == []


def test_reindex_skipped_off_darwin(
    system_dir: Path, killall_calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(font_registry.sys, "platform", "linux")

    assert font_registry.reindex(system_dir) is False
    assert killall_calls == []


def test_reindex_tolerates_missing_services(
    system_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`killall` renvoie ≠ 0 si un service ne tourne pas : ce n'est pas un échec."""

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="No matching processes"
        )

    monkeypatch.setattr(font_registry.subprocess, "run", fake_run)
    assert font_registry.reindex(system_dir) is True


def test_reindex_never_raises(
    system_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `killall` introuvable ou bloqué ne fait jamais échouer un sync."""

    def boom(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        raise OSError("killall introuvable")

    monkeypatch.setattr(font_registry.subprocess, "run", boom)
    assert font_registry.reindex(system_dir) is False
