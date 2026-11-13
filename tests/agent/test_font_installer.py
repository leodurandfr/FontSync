"""Tests de la sécurité install/désinstall de l'agent (B7).

Vérifie les deux invariants de `agent/font_installer.py` :
- **install** : ne jamais écraser une font homonyme au contenu différent
  (désambiguïsation par hash), idempotence sur contenu identique, refus d'un
  contenu corrompu (hash attendu ≠ reçu), formats non installables ignorés.
- **uninstall** (`remove_verified`) : suppression gardée par le hash, revérifiée
  juste avant le retrait, jamais hors de ~/Library/Fonts et disabled/ (les
  cibles viennent du scan du sync : cf. test_sync_command.py).

Vérifie aussi que toute mise en place ou tout retrait de fichier déclenche la
**réindexation macOS** (macOS 14+ n'indexe plus ~/Library/Fonts tout seul) : sans
elle, la copie ne vaut pas installation. L'effet réel n'est pas testable ici —
`font_registry` est espionné, cf. `test_font_registry.py` pour son contrat.

Tout passe par un vrai filesystem en `tmp_path` (INSTALL_DIR/DISABLED_DIR
redirigés par fixture), aucun réseau.
"""

from __future__ import annotations

import functools
import hashlib
import os
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


def test_activate_triggers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Déplacer le fichier n'active rien sur macOS 14+ : la réindexation le fait."""
    install, disabled = dirs
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(b"INTER")

    assert font_installer.activate_font("Inter.ttf") == font_installer.MoveResult.MOVED
    assert (install / "Inter.ttf").exists()
    assert registry.reindexed == [install]


def test_activate_already_in_place_is_a_noop(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Rien à déplacer : pas de réindexation (relancer `fontd` pour rien à
    chaque sync était M-02). L'auto-guérison d'un index figé reste portée par
    `install_font`, qui réindexe quand la font est déjà en place."""
    install, _ = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"INTER")

    assert (
        font_installer.activate_font("Inter.ttf") == font_installer.MoveResult.ALREADY
    )
    assert registry.reindexed == []


def test_deactivate_triggers_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Sans réindexation, les applications continuent de servir la font déplacée."""
    install, disabled = dirs
    install.mkdir(parents=True)
    (install / "Inter.ttf").write_bytes(b"INTER")

    assert (
        font_installer.deactivate_font("Inter.ttf") == font_installer.MoveResult.MOVED
    )
    assert (disabled / "Inter.ttf").exists()
    assert registry.reindexed == [install]


def test_deactivate_already_disabled_does_not_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    """Rien n'a bougé dans ~/Library/Fonts : inutile de relancer fontd."""
    _, disabled = dirs
    disabled.mkdir(parents=True)
    (disabled / "Inter.ttf").write_bytes(b"INTER")

    assert (
        font_installer.deactivate_font("Inter.ttf") == font_installer.MoveResult.ALREADY
    )
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
        assert (
            font_installer.activate_font(f"Font{i}.ttf", refresh_index=False)
            == font_installer.MoveResult.MOVED
        )

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
            font_installer.deactivate_font(f"Font{i}.ttf", refresh_index=False)
            == font_installer.MoveResult.MOVED
        )

    assert registry.reindexed == []
    assert all((disabled / f"Font{i}.ttf").exists() for i in range(3))

    assert font_installer.reindex_installed() is True
    assert registry.reindexed == [install]


# --- Homonymes entre ~/Library/Fonts et disabled/ (M-01, M-02) -------------
# Vraies TTF : v1 et v2 portent le même nom de fichier mais pas le même contenu.


# `build_ttf` horodate la police à la seconde : chaque version est construite
# UNE fois, sinon deux « mêmes » octets peuvent différer d'un appel à l'autre.
@functools.cache
def _v1() -> bytes:
    from tests.backend.conftest import build_ttf

    return build_ttf(family="Foo")


@functools.cache
def _v2() -> bytes:
    from tests.backend.conftest import build_ttf

    return build_ttf(family="Foo", extra_codepoints=[0x263A, 0x2603])


def _hashes(directory: Path) -> set[str]:
    return {_sha(p.read_bytes()) for p in directory.iterdir() if p.is_file()}


def test_deactivate_keeps_namesake_in_disabled(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v2())

    result = font_installer.deactivate_font("Foo.ttf")

    assert result == font_installer.MoveResult.MOVED
    assert _hashes(disabled) == {_sha(_v1()), _sha(_v2())}
    assert not (install / "Foo.ttf").exists()
    assert registry.reindexed == [install]


def test_deactivate_exact_duplicate_removes_source_only(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v1())

    result = font_installer.deactivate_font("Foo.ttf")

    assert result == font_installer.MoveResult.DEDUPLICATED
    assert not (install / "Foo.ttf").exists()
    assert (disabled / "Foo.ttf").read_bytes() == _v1()
    assert [p.name for p in disabled.iterdir()] == ["Foo.ttf"]
    # La font a quitté ~/Library/Fonts : le système doit le savoir.
    assert registry.reindexed == [install]


def test_activate_blocked_by_namesake_moves_under_disambiguated_name(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v2())

    result = font_installer.activate_font("Foo.ttf")

    assert result == font_installer.MoveResult.MOVED
    assert _hashes(install) == {_sha(_v1()), _sha(_v2())}
    assert (install / "Foo.ttf").read_bytes() == _v2()
    assert not (disabled / "Foo.ttf").exists()
    assert registry.reindexed == [install]


def test_activate_exact_duplicate_drops_disabled_copy_without_reindex(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v1())

    result = font_installer.activate_font("Foo.ttf")

    assert result == font_installer.MoveResult.DEDUPLICATED
    assert not (disabled / "Foo.ttf").exists()
    assert (install / "Foo.ttf").read_bytes() == _v1()
    assert registry.reindexed == []


def test_activate_unresolvable_collision_is_reported_untouched(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v2())
    blocker = install / font_installer._disambiguated_name("Foo.ttf", _sha(_v1()))
    blocker.write_bytes(b"autre chose")

    result = font_installer.activate_font("Foo.ttf")

    assert result == font_installer.MoveResult.CONFLICT
    assert (disabled / "Foo.ttf").read_bytes() == _v1()
    assert blocker.read_bytes() == b"autre chose"
    assert registry.reindexed == []


def test_install_avoids_disabled_namesake(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())

    path = font_installer.install_font("Foo.ttf", _v2(), expected_hash=_sha(_v2()))

    assert path is not None
    assert path.name == font_installer._disambiguated_name("Foo.ttf", _sha(_v2()))
    assert not (install / "Foo.ttf").exists()
    # Réactiver v1 plus tard ne heurte plus rien.
    assert font_installer.activate_font("Foo.ttf") == font_installer.MoveResult.MOVED
    assert _hashes(install) == {_sha(_v1()), _sha(_v2())}


def test_deactivate_acts_on_scanned_path_not_top_level_namesake(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    (install / "Family").mkdir(parents=True)
    nested = install / "Family" / "Foo.ttf"
    nested.write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v2())

    result = font_installer.deactivate_font(str(nested), expected_hash=_sha(_v1()))

    assert result == font_installer.MoveResult.MOVED
    assert (install / "Foo.ttf").read_bytes() == _v2()
    assert _hashes(disabled) == {_sha(_v1())}


def test_file_changed_since_scan_does_not_move(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    (install / "Foo.ttf").write_bytes(_v2())

    result = font_installer.deactivate_font(
        str(install / "Foo.ttf"), expected_hash=_sha(_v1())
    )

    assert result == font_installer.MoveResult.CHANGED
    assert (install / "Foo.ttf").read_bytes() == _v2()
    assert not disabled.exists() or not any(disabled.iterdir())
    assert registry.reindexed == []


def test_symlink_at_disambiguated_name_never_leads_to_deletion(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    source = disabled / "Foo.ttf"
    source.write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v2())
    trap = install / font_installer._disambiguated_name("Foo.ttf", _sha(_v1()))
    trap.symlink_to(source)

    result = font_installer.activate_font(str(source), expected_hash=_sha(_v1()))

    assert result == font_installer.MoveResult.CONFLICT
    assert source.read_bytes() == _v1()


def test_unreadable_source_is_never_deduplicated(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    source = disabled / "Foo.ttf"
    source.write_bytes(_v1())
    (install / "Foo.ttf").write_bytes(_v1())
    (install / "Foo.ttf").chmod(0)
    source.chmod(0)
    try:
        result = font_installer.activate_font("Foo.ttf")
    finally:
        source.chmod(0o644)
        (install / "Foo.ttf").chmod(0o644)

    assert result == font_installer.MoveResult.CONFLICT
    assert source.read_bytes() == _v1()


def test_install_never_overwrites_foreign_file_at_disambiguated_name(
    dirs: tuple[Path, Path], registry: _RegistrySpy
) -> None:
    install, disabled = dirs
    install.mkdir(parents=True)
    disabled.mkdir(parents=True)
    (disabled / "Foo.ttf").write_bytes(_v1())
    foreign = install / font_installer._disambiguated_name("Foo.ttf", _sha(_v2()))
    foreign.write_bytes(b"autre police")

    assert font_installer.install_font("Foo.ttf", _v2()) is None
    assert foreign.read_bytes() == b"autre police"


def test_move_no_clobber_refuses_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "a.ttf"
    dest = tmp_path / "b.ttf"
    source.write_bytes(b"A")
    dest.write_bytes(b"B")

    assert font_installer._move_no_clobber(source, dest) is False
    assert (source.read_bytes(), dest.read_bytes()) == (b"A", b"B")


def test_move_result_has_no_truth_value() -> None:
    with pytest.raises(TypeError):
        bool(font_installer.MoveResult.MISSING)


# --- remove_verified : la seule suppression du chemin de sync (M-04) -------


def test_remove_verified_deletes_matching_file(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    target = install / "Foo.ttf"
    target.write_bytes(_v1())

    assert font_installer.remove_verified(target, _sha(_v1())) is True
    assert not any(install.iterdir())


def test_remove_verified_keeps_changed_file_in_place(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    target = install / "Foo.ttf"
    target.write_bytes(_v2())

    assert font_installer.remove_verified(target, _sha(_v1())) is False
    assert target.read_bytes() == _v2()
    assert [p.name for p in install.iterdir()] == ["Foo.ttf"]


def test_remove_verified_refuses_symlink_and_outside_paths(
    dirs: tuple[Path, Path], tmp_path: Path
) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    outside = tmp_path / "Library-Fonts-systeme" / "Foo.ttf"
    outside.parent.mkdir()
    outside.write_bytes(_v1())
    link = install / "Lien.ttf"
    link.symlink_to(outside)

    assert font_installer.remove_verified(outside, _sha(_v1())) is False
    assert font_installer.remove_verified(link, _sha(_v1())) is False
    assert outside.read_bytes() == _v1() and link.is_symlink()


def test_remove_verified_never_deletes_a_file_rewritten_meanwhile(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le fichier est mis à l'écart AVANT d'être haché : une police réécrite à
    son emplacement pendant le hachage n'est pas celle qu'on supprime."""
    install, _ = dirs
    install.mkdir(parents=True)
    target = install / "Foo.ttf"
    target.write_bytes(_v1())
    real_hash = font_installer._hash_or_none

    def _hash_while_user_writes(path: Path) -> str | None:
        target.write_bytes(_v2())  # écriture concurrente au nom d'origine
        return real_hash(path)

    monkeypatch.setattr(font_installer, "_hash_or_none", _hash_while_user_writes)

    assert font_installer.remove_verified(target, _sha(_v1())) is True
    assert target.read_bytes() == _v2()


def test_remove_verified_recovers_from_crash_leftover(dirs: tuple[Path, Path]) -> None:
    install, _ = dirs
    install.mkdir(parents=True)
    target = install / "Foo.ttf"
    target.write_bytes(_v1())
    leftover = install / ".Foo.ttf.fontsync-remove"
    os.link(target, leftover)  # arrêt brutal entre le lien et le retrait

    assert font_installer.remove_verified(target, _sha(_v1())) is True
    assert not any(install.iterdir())
