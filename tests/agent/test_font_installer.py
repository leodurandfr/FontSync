"""Tests de la sécurité install/désinstall de l'agent (B7).

Vérifie les deux invariants de `agent/font_installer.py` :
- **install** : ne jamais écraser une font homonyme au contenu différent
  (désambiguïsation par hash), idempotence sur contenu identique, refus d'un
  contenu corrompu (hash attendu ≠ reçu), formats non installables ignorés.
- **uninstall** : suppression gardée par le hash — un homonyme au contenu
  différent n'est jamais supprimé ; un fichier renommé mais de même contenu
  l'est (repli par balayage).

Vérifie aussi que toute mise en place ou tout retrait de fichier déclenche la
**réindexation macOS** (macOS 14+ n'indexe plus ~/Library/Fonts tout seul) : sans
elle, la copie ne vaut pas installation. L'effet réel n'est pas testable ici —
`font_registry` est espionné, cf. `test_font_registry.py` pour son contrat.

Tout passe par un vrai filesystem en `tmp_path` (INSTALL_DIR/DISABLED_DIR
redirigés par fixture), aucun réseau.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent import font_installer


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Redirige INSTALL_DIR/DISABLED_DIR vers tmp_path."""
    install = tmp_path / "Fonts"
    disabled = tmp_path / "disabled"
    monkeypatch.setattr(font_installer, "INSTALL_DIR", install)
    monkeypatch.setattr(font_installer, "DISABLED_DIR", disabled)
    return install, disabled


class _RegistrySpy:
    """Enregistre les appels à `font_registry` au lieu de toucher la session."""

    def __init__(self) -> None:
        self.reindexed: list[Path] = []

    def reindex(self, directory: Path) -> bool:
        self.reindexed.append(directory)
        return True


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> _RegistrySpy:
    spy = _RegistrySpy()
    monkeypatch.setattr(font_installer, "font_registry", spy)
    return spy


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_install_fresh(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    data = b"INTER-REGULAR"
    dest = font_installer.install_font("Inter.ttf", data)
    assert dest == install / "Inter.ttf"
    assert dest.read_bytes() == data


def test_install_strips_directory_components(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    dest = font_installer.install_font("../../evil/Inter.ttf", b"X")
    assert dest == install / "Inter.ttf"
    assert dest.parent == install


def test_install_unsupported_format(dirs: tuple[Path, Path]) -> None:
    assert font_installer.install_font("Inter.woff2", b"X") is None


def test_install_idempotent_same_content(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    data = b"SAME"
    first = font_installer.install_font("Inter.ttf", data)
    second = font_installer.install_font("Inter.ttf", data)
    assert first == second == install / "Inter.ttf"
    # Un seul fichier, contenu intact.
    assert list(install.iterdir()) == [install / "Inter.ttf"]


def test_install_preserves_local_homonym(dirs: tuple[Path, Path]) -> None:
    """Une font locale homonyme au contenu différent n'est jamais écrasée."""
    install, _ = dirs
    local = b"USER-LOCAL-FONT"
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(local)

    server = b"SERVER-FONT"
    dest = font_installer.install_font("Inter.ttf", server)

    # La font locale est intacte...
    assert (install / "Inter.ttf").read_bytes() == local
    # ...et la font serveur est posée sous un nom désambiguïsé.
    assert dest is not None
    assert dest.name == f"Inter__fontsync-{_sha(server)[:12]}.ttf"
    assert dest.read_bytes() == server


def test_install_disambiguated_idempotent(dirs: tuple[Path, Path]) -> None:
    """Réinstaller après désambiguïsation ne crée pas de second fichier."""
    install, _ = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"USER-LOCAL")
    server = b"SERVER-FONT"

    first = font_installer.install_font("Inter.ttf", server)
    second = font_installer.install_font("Inter.ttf", server)

    assert first == second
    names = sorted(p.name for p in install.iterdir())
    assert names == ["Inter.ttf", f"Inter__fontsync-{_sha(server)[:12]}.ttf"]


def test_install_rejects_corrupt_content(dirs: tuple[Path, Path]) -> None:
    """expected_hash ≠ hash réel → refus, rien d'écrit."""
    install, _ = dirs
    dest = font_installer.install_font("Inter.ttf", b"CORRUPT", expected_hash="0" * 64)
    assert dest is None
    assert not install.exists() or list(install.iterdir()) == []


def test_install_accepts_matching_expected_hash(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    data = b"GOOD"
    dest = font_installer.install_font("Inter.ttf", data, expected_hash=_sha(data))
    assert dest == install / "Inter.ttf"


def test_uninstall_removes_matching_hash(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    data = b"INTER"
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(data)

    assert font_installer.uninstall_font("Inter.ttf", _sha(data)) is True
    assert not (install / "Inter.ttf").exists()


def test_uninstall_spares_local_homonym(dirs: tuple[Path, Path]) -> None:
    """Un homonyme au contenu différent (font de l'utilisateur) n'est pas supprimé."""
    install, _ = dirs
    user_data = b"USER-FONT"
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(user_data)

    # On demande la désinstallation d'un AUTRE contenu (hash serveur).
    removed = font_installer.uninstall_font("Inter.ttf", _sha(b"SERVER-FONT"))

    assert removed is False
    assert (install / "Inter.ttf").read_bytes() == user_data


def test_uninstall_also_clears_disabled(dirs: tuple[Path, Path]) -> None:
    install, disabled = dirs
    data = b"INTER"
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(data)

    assert font_installer.uninstall_font("Inter.ttf", _sha(data)) is True
    assert not (disabled / "Inter.ttf").exists()


def test_uninstall_fallback_scan_for_renamed_file(dirs: tuple[Path, Path]) -> None:
    """Un fichier renommé par l'utilisateur mais de même contenu est retrouvé par hash."""
    install, _ = dirs
    data = b"INTER"
    install.mkdir(parents=True)
    (install / "MaPoliceRenommee.ttf").write_bytes(data)

    assert font_installer.uninstall_font("Inter.ttf", _sha(data)) is True
    assert not (install / "MaPoliceRenommee.ttf").exists()


def test_uninstall_nothing_matches(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    (install / "Other.ttf").write_bytes(b"OTHER")

    assert font_installer.uninstall_font("Inter.ttf", _sha(b"INTER")) is False
    assert (install / "Other.ttf").exists()


# ---------- Prise en compte par macOS (le fichier posé ne suffit pas) ----------


def test_install_triggers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, _ = dirs
    font_installer.install_font("Inter.ttf", b"INTER")

    assert registry.reindexed == [install]


def test_install_batch_defers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """En lot : une seule réindexation à la fin, pas une par fichier.

    Relancer `fontd` par font ferait repartir de zéro une reconstruction qui
    coûte des dizaines de secondes.
    """
    install, _ = dirs
    for i in range(3):
        font_installer.install_font(
            f"Font{i}.ttf", f"DATA{i}".encode(), refresh_index=False
        )

    assert registry.reindexed == []

    assert font_installer.reindex_installed() is True
    assert registry.reindexed == [install]


def test_reinstall_of_already_present_font_still_reindexes(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Fichier déjà là mais jamais indexé (l'état du bug) : on réindexe quand même."""
    install, _ = dirs
    data = b"INTER"
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(data)

    dest = font_installer.install_font("Inter.ttf", data)

    assert dest == install / "Inter.ttf"
    assert registry.reindexed == [install]


def test_failed_install_does_not_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Rien n'a été posé (format refusé, contenu corrompu) → rien à réindexer."""
    assert font_installer.install_font("Inter.woff2", b"X") is None
    assert (
        font_installer.install_font("Inter.ttf", b"X", expected_hash="0" * 64) is None
    )
    assert registry.reindexed == []


def test_uninstall_reindexes(dirs: tuple[Path, Path], registry: _RegistrySpy) -> None:
    """Retirer le fichier ne suffit pas : macOS continue de servir la font."""
    install, _ = dirs
    data = b"INTER"
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(data)

    assert font_installer.uninstall_font("Inter.ttf", _sha(data)) is True
    assert registry.reindexed == [install]


def test_uninstall_from_disabled_does_not_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """`disabled/` est hors du champ de macOS : rien à réindexer."""
    _, disabled = dirs
    data = b"INTER"
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(data)

    assert font_installer.uninstall_font("Inter.ttf", _sha(data)) is True
    assert registry.reindexed == []


def test_uninstall_nothing_removed_does_not_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"USER-FONT")

    assert font_installer.uninstall_font("Inter.ttf", _sha(b"AUTRE")) is False
    assert registry.reindexed == []


def test_activate_triggers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Déplacer le fichier n'active rien sur macOS 14+ : la réindexation le fait."""
    install, disabled = dirs
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(b"INTER")

    assert font_installer.activate_font("Inter.ttf") is True
    assert (install / "Inter.ttf").exists()
    assert registry.reindexed == [install]


def test_activate_already_in_place_still_reindexes(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Présent dans ~/Library/Fonts ≠ pris en compte : on redemande l'indexation."""
    install, _ = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"INTER")

    assert font_installer.activate_font("Inter.ttf") is True
    assert registry.reindexed == [install]


def test_deactivate_triggers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Sans réindexation, les applications continuent de servir la font déplacée."""
    install, disabled = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"INTER")

    assert font_installer.deactivate_font("Inter.ttf") is True
    assert (disabled / "Inter.ttf").exists()
    assert registry.reindexed == [install]


def test_deactivate_already_disabled_does_not_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Rien n'a bougé dans ~/Library/Fonts : inutile de relancer fontd."""
    _, disabled = dirs
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(b"INTER")

    assert font_installer.deactivate_font("Inter.ttf") is True
    assert registry.reindexed == []


def test_activate_batch_defers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """En lot : une seule réindexation à la fin, comme pour install/uninstall."""
    install, disabled = dirs
    disabled.mkdir(parents=True)
    for i in range(3):
        (disabled / f"Font{i}.ttf").write_bytes(f"DATA{i}".encode())

    for i in range(3):
        assert font_installer.activate_font(f"Font{i}.ttf", refresh_index=False) is True

    assert registry.reindexed == []
    assert all((install / f"Font{i}.ttf").exists() for i in range(3))

    assert font_installer.reindex_installed() is True
    assert registry.reindexed == [install]


def test_deactivate_batch_defers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """En lot : une seule réindexation à la fin, comme pour install/uninstall."""
    install, disabled = dirs
    install.mkdir(parents=True)
    for i in range(3):
        (install / f"Font{i}.ttf").write_bytes(f"DATA{i}".encode())

    for i in range(3):
        assert (
            font_installer.deactivate_font(f"Font{i}.ttf", refresh_index=False) is True
        )

    assert registry.reindexed == []
    assert all((disabled / f"Font{i}.ttf").exists() for i in range(3))

    assert font_installer.reindex_installed() is True
    assert registry.reindexed == [install]
