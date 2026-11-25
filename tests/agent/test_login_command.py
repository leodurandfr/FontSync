"""`fontsync-agent login` : email + mot de passe → jeton d'appareil."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent import config as config_module
from agent import login_command
from agent.config import AgentConfig
from agent.login_command import LoginError, device_login


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_dir = tmp_path / ".fontsync"
    monkeypatch.setattr(config_module, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", cfg_dir / "config.yaml")
    return cfg_dir / "config.yaml"


def _server(status: int, body: dict | None = None, seen: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["url"] = str(request.url)
            seen["json"] = json.loads(request.content)
        return httpx.Response(status, json=body or {})

    return httpx.MockTransport(handler)


def test_login_stores_the_device_token() -> None:
    config = AgentConfig(server_url="http://nas:8080/", device_id="dev-1")
    config.save()
    seen: dict = {}

    account = device_login(
        config,
        email="Lea@Example.com",
        password="secret-pass",
        transport=_server(
            201,
            {"token": "device-tok", "user": {"email": "lea@example.com"}},
            seen,
        ),
    )

    assert account == "lea@example.com"
    assert seen["url"] == "http://nas:8080/api/auth/device-login"
    assert seen["json"]["email"] == "Lea@Example.com"
    assert seen["json"]["deviceName"]
    reloaded = AgentConfig.load()
    assert reloaded.device_token == "device-tok"
    assert reloaded.account_email == "lea@example.com"
    # L'identité du Mac est conservée : le serveur le reconnaît au register.
    assert reloaded.device_id == "dev-1"
    assert reloaded.auth_token == "device-tok"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "incorrect"), (429, "Trop d'essais"), (404, "mettez-le à jour")],
)
def test_login_failures_say_why_and_write_nothing(status: int, message: str) -> None:
    config = AgentConfig(server_url="http://nas:8080", device_id="dev-1")
    config.save()

    with pytest.raises(LoginError, match=message):
        device_login(
            config, email="a@example.com", password="x", transport=_server(status)
        )

    assert AgentConfig.load().device_id == "dev-1"
    assert AgentConfig.load().device_token is None


def test_main_reads_password_without_echo_and_reports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: dict = {}

    def fake_login(config: AgentConfig, *, email: str, password: str) -> str:
        calls.update(email=email, password=password, url=config.server_url)
        return email

    monkeypatch.setattr(login_command, "device_login", fake_login)

    code = login_command.main(
        server="http://nas:8080",
        prompt=lambda _q: "lea@example.com",
        secret_prompt=lambda _q: "secret-pass",
    )

    assert code == 0
    assert calls == {
        "email": "lea@example.com",
        "password": "secret-pass",
        "url": "http://nas:8080",
    }
    assert "lea@example.com" in capsys.readouterr().out


def test_main_returns_1_on_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: object, **_k: object) -> str:
        raise LoginError("Email ou mot de passe incorrect.")

    monkeypatch.setattr(login_command, "device_login", refuse)
    code = login_command.main(
        email="a@example.com", secret_prompt=lambda _q: "x", prompt=lambda _q: ""
    )
    assert code == 1
