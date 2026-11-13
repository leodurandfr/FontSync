"""Tests du dispatch CLI de l'agent (`agent/__main__.py`, B11).

Vérifient que chaque sous-commande route vers le bon point d'entrée, que
l'absence de commande équivaut à `sync`, que le code de sortie est propagé, et
qu'une commande inconnue échoue proprement (argparse). Les vrais points d'entrée
sont remplacés par des stubs : aucun réseau ni effet launchd réel.
"""

from __future__ import annotations

import pytest

from agent import __main__ as cli
from agent import launchd_setup, listen_command, sync_command


def test_no_command_defaults_to_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sync_command, "main", lambda **kw: calls.append("sync") or 0)

    assert cli.main([]) == 0
    assert calls == ["sync"]


def test_sync_command_routes_and_propagates_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_command, "main", lambda **kw: 1)

    assert cli.main(["sync"]) == 1


def test_listen_command_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(listen_command, "main", lambda: calls.append("listen") or 0)

    assert cli.main(["listen"]) == 0
    assert calls == ["listen"]


@pytest.mark.parametrize("command", ["setup", "teardown", "status", "doctor"])
def test_launchd_commands_route(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(launchd_setup, command, lambda **kw: calls.append(command) or 0)

    assert cli.main([command]) == 0
    assert calls == [command]


def test_unknown_command_exits_nonzero() -> None:
    # argparse rejette une sous-commande non déclarée avant tout dispatch.
    with pytest.raises(SystemExit) as exc:
        cli.main(["bogus"])
    assert exc.value.code != 0


def test_sync_wait_flag_is_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    monkeypatch.setattr(
        sync_command, "main", lambda *, wait=False: seen.append(wait) or 0
    )

    cli.main(["sync", "--wait"])
    cli.main(["sync"])

    assert seen == [True, False]


def test_setup_passes_allow_dev_python(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []
    monkeypatch.setattr(
        launchd_setup,
        "setup",
        lambda *, allow_dev_python=False: seen.append(allow_dev_python) or 0,
    )

    cli.main(["setup", "--allow-dev-python"])
    cli.main(["setup"])

    assert seen == [True, False]
