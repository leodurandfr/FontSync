"""The whole test suite runs in a sandbox: never the real ~/.fontsync, fonts or LaunchAgents.

`tests/conftest.py` points HOME, FONTSYNC_HOME and FONTSYNC_FONTS_DIR at a
throwaway directory before `agent` is imported, and installs an audit hook
that refuses writes under the real protected directories it captured.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests import conftest as root_conftest


def test_config_file_is_sandboxed() -> None:
    from agent import config

    # $TMPDIR may itself live under the real HOME: compare with the real state dir.
    real_state_dir = Path(root_conftest.REAL_HOME) / ".fontsync"
    assert not config.CONFIG_FILE.is_relative_to(real_state_dir)
    assert config.CONFIG_FILE.is_relative_to(root_conftest.SANDBOX_HOME)


def test_home_and_agent_dirs_point_to_the_sandbox() -> None:
    from agent import font_registry, launchd_setup
    from agent.paths import fonts_dir, state_dir

    sandbox = Path(root_conftest.SANDBOX_HOME)
    assert Path.home() == sandbox
    assert state_dir().is_relative_to(sandbox)
    assert fonts_dir().is_relative_to(sandbox)
    # Paths frozen at import time by agent modules.
    assert launchd_setup.LAUNCH_AGENTS_DIR.is_relative_to(sandbox)
    assert launchd_setup.LOG_DIR.is_relative_to(sandbox)
    assert font_registry._SYSTEM_USER_FONTS_DIR.is_relative_to(sandbox)


def test_write_to_real_fonts_dir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is exercised on a stand-in of ~/Library/Fonts, never the real one."""
    fake_fonts = tmp_path / "fake-real-home" / "Library" / "Fonts"
    fake_fonts.mkdir(parents=True)
    monkeypatch.setattr(root_conftest, "PROTECTED_DIRS", (str(fake_fonts),))
    with pytest.raises(PermissionError, match="test sandbox"):
        with open(fake_fonts / "x.ttf", "wb") as handle:
            handle.write(b"x")
    with pytest.raises(PermissionError, match="test sandbox"):
        os.open(fake_fonts / "y.ttf", os.O_WRONLY | os.O_CREAT)
    outside = tmp_path / "elsewhere.ttf"
    outside.write_bytes(b"ok")
    with pytest.raises(PermissionError, match="test sandbox"):
        os.replace(outside, fake_fonts / "moved.ttf")
    assert not any(fake_fonts.iterdir())


def test_read_of_protected_dir_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fonts = tmp_path / "Fonts"
    fake_fonts.mkdir()
    (fake_fonts / "a.ttf").write_bytes(b"font")
    monkeypatch.setattr(root_conftest, "PROTECTED_DIRS", (str(fake_fonts),))
    assert (fake_fonts / "a.ttf").read_bytes() == b"font"


@pytest.mark.parametrize(
    ("command", "shell"),
    [
        (["launchctl", "list"], False),
        (["./launchctl", "list"], False),
        (["killall", "fontd"], False),
        (["env", "launchctl", "list"], False),
        ("launchctl list", True),
        ("sh -c 'killall fontd'", True),
    ],
)
def test_launchctl_and_killall_are_refused(
    command: list[str] | str,
    shell: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty PATH and a fresh cwd: if the guard ever regresses, nothing real runs
    # (FileNotFoundError or a failing shell instead of PermissionError).
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PermissionError, match="test sandbox"):
        subprocess.run(command, shell=shell, check=False, capture_output=True)


def test_os_system_launchctl_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(PermissionError, match="test sandbox"):
        os.system("launchctl list")


def test_write_through_case_or_slash_alias_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protected = tmp_path / "Prot" / "Fonts"
    protected.mkdir(parents=True)
    monkeypatch.setattr(root_conftest, "PROTECTED_DIRS", (str(protected),))
    for alias in (str(protected).upper() + "/a.ttf", "/" + str(protected) + "/b.ttf"):
        with pytest.raises(PermissionError, match="test sandbox"):
            open(alias, "wb").close()  # noqa: SIM115
    assert not any(protected.iterdir())
