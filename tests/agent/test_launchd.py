"""Vérifie les gabarits LaunchAgent de l'agent (PLAN.md B8).

On ne charge pas réellement les jobs (launchctl modifierait la session) : on
contrôle que les gabarits *.plist se substituent en plist valides et portent
les clés launchd attendues. Le script install.sh fait la même substitution
(jetons @...@) via sed, donc ces tests gardent les deux en phase.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

LAUNCHD_DIR = Path(__file__).resolve().parents[2] / "agent" / "launchd"

SUBSTITUTIONS = {
    "@PYTHON@": "/opt/fontsync/.venv/bin/python",
    "@WORKDIR@": "/opt/fontsync",
    "@HOME@": "/Users/test",
    "@LOGDIR@": "/Users/test/Library/Logs/FontSync",
}


def _render(name: str) -> dict:
    raw = (LAUNCHD_DIR / name).read_text()
    for token, value in SUBSTITUTIONS.items():
        raw = raw.replace(token, value)
    for token in SUBSTITUTIONS:
        assert token not in raw, f"jeton non substitué : {token}"
    return plistlib.loads(raw.encode())


def test_install_script_exists_and_executable() -> None:
    script = LAUNCHD_DIR / "install.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111, "install.sh doit être exécutable"


def test_sync_plist_is_triggered_not_keepalive() -> None:
    p = _render("com.fontsync.sync.plist")

    assert p["Label"] == "com.fontsync.sync"
    assert p["ProgramArguments"] == [
        SUBSTITUTIONS["@PYTHON@"],
        "-m",
        "agent",
        "sync",
    ]
    # `sync` est une commande courte : déclenchée, jamais maintenue en vie.
    assert "KeepAlive" not in p
    assert p["RunAtLoad"] is True
    assert p["StartInterval"] == 600
    assert f"{SUBSTITUTIONS['@HOME@']}/Library/Fonts" in p["WatchPaths"]
    assert "/Library/Fonts" in p["WatchPaths"]
    assert p["EnvironmentVariables"]["PYTHONPATH"] == SUBSTITUTIONS["@WORKDIR@"]


def test_listen_plist_is_keepalive_daemon() -> None:
    p = _render("com.fontsync.listen.plist")

    assert p["Label"] == "com.fontsync.listen"
    assert p["ProgramArguments"][-1] == "listen"
    # `listen` est long-vécu : relancé s'il meurt.
    assert p["KeepAlive"] is True
    assert p["RunAtLoad"] is True
    assert "StartInterval" not in p
    assert "WatchPaths" not in p


@pytest.mark.parametrize(
    "name", ["com.fontsync.sync.plist", "com.fontsync.listen.plist"]
)
def test_log_paths_under_logdir(name: str) -> None:
    p = _render(name)
    assert p["StandardOutPath"].startswith(SUBSTITUTIONS["@LOGDIR@"])
    assert p["StandardErrorPath"].startswith(SUBSTITUTIONS["@LOGDIR@"])
