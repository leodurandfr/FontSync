"""Vérifie le socle d'empaquetage launchd de l'agent (PLAN.md B8 + B10).

Deux niveaux :
- rendu des gabarits *.plist (substitution des jetons → plist valide portant les
  clés launchd attendues) ;
- flux des sous-commandes `setup`/`teardown`/`status` qui ont absorbé la logique
  de l'ancien `install.sh` (résolution Python, écriture des plists, appels
  `launchctl`), pilotés sans toucher à la session via un faux `launchctl`.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from agent import launchd_setup

SUBS = {
    "python": "/opt/fontsync/.venv/bin/python",
    "workdir": "/opt/fontsync",
    "home": "/Users/test",
    "logdir": "/Users/test/Library/Logs/FontSync",
}


def _render(label: str) -> dict:
    raw = launchd_setup.render_plist(label, **SUBS)
    for token in launchd_setup.SUBSTITUTION_TOKENS:
        assert token not in raw, f"jeton non substitué : {token}"
    return plistlib.loads(raw.encode())


# --- Rendu des gabarits ----------------------------------------------------


def test_sync_plist_is_triggered_not_keepalive() -> None:
    p = _render("com.fontsync.sync")

    assert p["Label"] == "com.fontsync.sync"
    assert p["ProgramArguments"] == [SUBS["python"], "-m", "agent", "sync"]
    # `sync` est une commande courte : déclenchée, jamais maintenue en vie.
    assert "KeepAlive" not in p
    assert p["RunAtLoad"] is True
    assert p["StartInterval"] == 600
    assert f"{SUBS['home']}/Library/Fonts" in p["WatchPaths"]
    assert "/Library/Fonts" in p["WatchPaths"]
    assert p["EnvironmentVariables"]["PYTHONPATH"] == SUBS["workdir"]


def test_listen_plist_is_keepalive_daemon() -> None:
    p = _render("com.fontsync.listen")

    assert p["Label"] == "com.fontsync.listen"
    assert p["ProgramArguments"][-1] == "listen"
    # `listen` est long-vécu : relancé s'il meurt.
    assert p["KeepAlive"] is True
    assert p["RunAtLoad"] is True
    assert "StartInterval" not in p
    assert "WatchPaths" not in p


@pytest.mark.parametrize("label", launchd_setup.LABELS)
def test_log_paths_under_logdir(label: str) -> None:
    p = _render(label)
    assert p["StandardOutPath"].startswith(SUBS["logdir"])
    assert p["StandardErrorPath"].startswith(SUBS["logdir"])


def test_render_rejects_invalid_plist(monkeypatch: pytest.MonkeyPatch) -> None:
    # Un gabarit cassé doit lever (équivalent portable du `plutil -lint`).
    monkeypatch.setattr(
        launchd_setup.Path, "read_text", lambda self: "<plist><dict>@PYTHON@"
    )
    with pytest.raises(Exception):
        launchd_setup.render_plist("com.fontsync.sync", **SUBS)


# --- Résolution du Python --------------------------------------------------


def test_resolve_python_prefers_override() -> None:
    assert (
        launchd_setup.resolve_python({"FONTSYNC_PYTHON": "/custom/python"})
        == "/custom/python"
    )


def test_resolve_python_defaults_to_current_interpreter() -> None:
    import sys

    assert launchd_setup.resolve_python({}) == sys.executable


# --- write_plists ----------------------------------------------------------


def test_write_plists_creates_valid_files(tmp_path: Path) -> None:
    written = launchd_setup.write_plists(tmp_path / "LaunchAgents", **SUBS)

    assert [p.name for p in written] == [f"{lbl}.plist" for lbl in launchd_setup.LABELS]
    for path in written:
        assert path.exists()
        plistlib.loads(path.read_bytes())  # parsable
        assert "@" not in path.read_text() or "fontsync" in path.read_text()
    # Pas de fichier temporaire laissé derrière.
    assert not list((tmp_path / "LaunchAgents").glob("*.tmp"))


# --- Flux setup / teardown / status ----------------------------------------


@pytest.fixture
def fake_launchctl(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Capture les appels `launchctl` et neutralise le réseau/launchd réel."""
    calls: list[tuple[str, ...]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    class _Absent:
        returncode = 1
        stdout = ""
        stderr = ""

    def _fake(*args: str):
        calls.append(args)
        # `print` sonde la présence d'un job : on le simule ABSENT (déchargé)
        # pour que la boucle d'attente de `_bootout_and_wait` sorte aussitôt.
        if args and args[0] == "print":
            return _Absent()
        return _Result()

    monkeypatch.setattr(launchd_setup, "_launchctl", _fake)
    monkeypatch.setattr(launchd_setup, "is_macos", lambda: True)
    monkeypatch.setattr(launchd_setup.os, "getuid", lambda: 501, raising=False)
    # `import agent` probe : toujours OK.
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    return calls


def test_setup_writes_plists_and_loads_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_launchctl: list
) -> None:
    la_dir = tmp_path / "LaunchAgents"
    log_dir = tmp_path / "Logs" / "FontSync"
    monkeypatch.setattr(launchd_setup, "LAUNCH_AGENTS_DIR", la_dir)
    monkeypatch.setattr(launchd_setup, "LOG_DIR", log_dir)

    rc = launchd_setup.setup({"FONTSYNC_PYTHON": "/opt/py"})
    assert rc == 0

    # Les deux plists ont été matérialisés et sont valides.
    for label in launchd_setup.LABELS:
        plist = la_dir / f"{label}.plist"
        assert plist.exists()
        data = plistlib.loads(plist.read_bytes())
        assert data["ProgramArguments"][0] == "/opt/py"
    assert log_dir.exists()

    # Chaque job est rechargé (bootout puis bootstrap) + kickstart du sync.
    domain = "gui/501"
    verbs = [(c[0], c[1]) for c in fake_launchctl]
    for label in launchd_setup.LABELS:
        assert ("bootout", f"{domain}/{label}") in verbs
        assert ("bootstrap", domain) in verbs
    assert ("kickstart", f"{domain}/com.fontsync.sync") in [
        (c[0], c[1]) for c in fake_launchctl
    ]


def test_setup_aborts_when_bootstrap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launchd_setup, "is_macos", lambda: True)
    monkeypatch.setattr(launchd_setup.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(launchd_setup, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")
    monkeypatch.setattr(launchd_setup, "LOG_DIR", tmp_path / "Logs")
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    def _fake(*args: str):
        ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        fail = type("R", (), {"returncode": 5, "stdout": "", "stderr": "boom"})()
        absent = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        if args[0] == "bootstrap":
            return fail
        if args[0] == "print":  # job absent → la boucle d'attente sort vite
            return absent
        return ok

    monkeypatch.setattr(launchd_setup, "_launchctl", _fake)

    assert launchd_setup.setup({"FONTSYNC_PYTHON": "/opt/py"}) == 1


def test_teardown_removes_plists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_launchctl: list
) -> None:
    la_dir = tmp_path / "LaunchAgents"
    monkeypatch.setattr(launchd_setup, "LAUNCH_AGENTS_DIR", la_dir)
    launchd_setup.write_plists(la_dir, **SUBS)  # simule une install existante

    rc = launchd_setup.teardown()
    assert rc == 0
    for label in launchd_setup.LABELS:
        assert not (la_dir / f"{label}.plist").exists()
        assert ("bootout", f"gui/501/{label}") in [(c[0], c[1]) for c in fake_launchctl]


def test_teardown_is_idempotent_without_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_launchctl: list
) -> None:
    monkeypatch.setattr(launchd_setup, "LAUNCH_AGENTS_DIR", tmp_path / "nope")
    assert launchd_setup.teardown() == 0  # missing_ok : ne lève pas


def test_status_reports_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(launchd_setup, "is_macos", lambda: True)
    monkeypatch.setattr(launchd_setup.os, "getuid", lambda: 501, raising=False)

    def _fake(*args: str):
        rc = 0 if args[1].endswith("sync") else 3
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(launchd_setup, "_launchctl", _fake)

    assert launchd_setup.status() == 0
    out = capsys.readouterr().out
    assert "com.fontsync.sync : chargé" in out
    assert "com.fontsync.listen : absent" in out


def test_subcommands_refuse_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launchd_setup, "is_macos", lambda: False)
    assert launchd_setup.setup() == 1
    assert launchd_setup.teardown() == 1
    assert launchd_setup.status() == 1


def test_install_script_still_present_and_executable() -> None:
    # Wrapper rétro-compatible conservé (route vers les sous-commandes CLI).
    script = Path(launchd_setup.TEMPLATE_DIR) / "install.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111
