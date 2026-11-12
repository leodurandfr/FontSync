"""Dev scripts are safe by default: no well-known token on a non-loopback interface."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SERVER = REPO_ROOT / "scripts" / "dev" / "run-server.sh"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_server(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {
        **os.environ,
        "FONTSYNC_DEV_ROOT": str(tmp_path),
        "PORT": str(_free_port()),
        **env,
    }
    proc = subprocess.Popen(
        ["bash", str(RUN_SERVER)],
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        out, _ = proc.communicate(timeout=5)
        pytest.fail(f"run-server.sh kept running (server started):\n{out}")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, "")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "::"])
def test_refuses_default_token_off_loopback(tmp_path: Path, host: str) -> None:
    result = _run_server(tmp_path, HOST=host, FONTSYNC_TOKEN="fontsync-dev")
    assert result.returncode != 0
    assert "fontsync-dev" in result.stdout
    # Refused before any migration: no database was created.
    assert not (tmp_path / "server" / "fontsync.db").exists()


@pytest.mark.parametrize(
    "token",
    [
        " fontsync-dev",
        "fontsync-dev ",
        "fontsync-dev\n",
        "\tfontsync-dev",
        # Characters Python's str.strip() removes but `tr -d '[:space:]'` keeps.
        "\x1cfontsync-dev",
        "fontsync-dev\x1f",
        "\x85fontsync-dev",
        " fontsync-dev",
        "fontsync-dev　",
    ],
)
def test_refuses_default_token_with_surrounding_whitespace(
    tmp_path: Path, token: str
) -> None:
    """The server strips the token: whitespace must not slip past the check."""
    result = _run_server(tmp_path, HOST="0.0.0.0", FONTSYNC_TOKEN=token)
    assert result.returncode == 2
    assert not (tmp_path / "server" / "fontsync.db").exists()
