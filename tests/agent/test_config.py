"""Tests de la configuration de l'agent (B5).

Vérifient la persistance correcte de l'identité du device (`device_id`/token)
au `save()`, le round-trip complet load→save→load, la cohérence des défauts
entre le dataclass et `load()` (notamment `auto_pull`), la tolérance aux clés
absentes ou à un fichier partiel, et l'écriture atomique restreinte (0600).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from agent import config as config_module
from agent.config import AgentConfig


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige la config vers tmp_path pour ne jamais toucher le vrai ~."""
    cfg_dir = tmp_path / ".fontsync"
    cfg_file = cfg_dir / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", cfg_file)
    return cfg_file


def test_load_creates_default_file_when_absent(_isolated_config: Path) -> None:
    assert not _isolated_config.exists()
    cfg = AgentConfig.load()
    assert _isolated_config.exists()
    # Les défauts du dataclass sont écrits tels quels.
    assert cfg.auto_pull is False
    assert cfg.auto_push is True


def test_persists_device_id_and_token(_isolated_config: Path) -> None:
    """Bug #13 : device_id/token doivent survivre à save()→load()."""
    cfg = AgentConfig.load()
    cfg.device_id = "dev-123"
    cfg.device_token = "tok-abc"
    cfg.save()

    reloaded = AgentConfig.load()
    assert reloaded.device_id == "dev-123"
    assert reloaded.device_token == "tok-abc"


def test_full_round_trip_preserves_all_fields(_isolated_config: Path) -> None:
    cfg = AgentConfig(
        server_url="http://nas.local:9000",
        server_token="instance-secret",
        device_token="tok",
        device_id="dev",
        directories=["/a", "/b"],
        ignore_patterns=["x*"],
        auto_push=False,
        auto_pull=True,
    )
    cfg.save()

    reloaded = AgentConfig.load()
    assert reloaded == cfg


def test_persists_server_token(_isolated_config: Path) -> None:
    """P1.3 : le token partagé d'instance survit à save()→load()."""
    cfg = AgentConfig.load()
    cfg.server_token = "instance-secret"
    cfg.save()

    assert AgentConfig.load().server_token == "instance-secret"
    # Distinct du device_token (auth par-device, réservée au cloud / Phase 7).
    assert AgentConfig.load().device_token is None


def test_server_token_loaded_from_yaml_key(_isolated_config: Path) -> None:
    """La clé YAML est bien `server.token` (pas `server.server_token`)."""
    _isolated_config.parent.mkdir(parents=True, exist_ok=True)
    _isolated_config.write_text(
        yaml.safe_dump({"server": {"token": "tok-x"}}), encoding="utf-8"
    )

    assert AgentConfig.load().server_token == "tok-x"


def test_auto_pull_default_consistent_between_dataclass_and_load(
    _isolated_config: Path,
) -> None:
    """Le défaut « clé absente » doit égaler le défaut du dataclass (False)."""
    # Fichier sans la clé sync.auto_pull.
    _isolated_config.parent.mkdir(parents=True, exist_ok=True)
    _isolated_config.write_text(
        yaml.safe_dump({"server": {"url": "http://x"}}), encoding="utf-8"
    )

    loaded = AgentConfig.load()
    assert loaded.auto_pull is AgentConfig().auto_pull is False


def test_load_tolerates_partial_and_null_sections(_isolated_config: Path) -> None:
    _isolated_config.parent.mkdir(parents=True, exist_ok=True)
    # Sections présentes mais nulles (YAML `scan:` sans valeur) ne doivent pas
    # faire planter `load()`.
    _isolated_config.write_text(
        "server:\n  device_id: only-id\nscan:\nsync:\n", encoding="utf-8"
    )

    cfg = AgentConfig.load()
    assert cfg.device_id == "only-id"
    assert cfg.directories == AgentConfig().directories
    assert cfg.auto_push is True


def test_save_is_atomic_and_restricted(_isolated_config: Path) -> None:
    cfg = AgentConfig.load()
    cfg.device_token = "secret"
    cfg.save()

    # Pas de fichier temporaire laissé derrière.
    leftovers = list(_isolated_config.parent.glob("*.tmp"))
    assert leftovers == []

    mode = stat.S_IMODE(os.stat(_isolated_config).st_mode)
    assert mode == 0o600


def test_hostname_and_name_env_override(
    _isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les overrides d'env distinguent deux devices simulés sur une même machine."""
    cfg = AgentConfig.load()
    monkeypatch.setenv("FONTSYNC_HOSTNAME", "mac-dev-B")
    monkeypatch.setenv("FONTSYNC_DEVICE_NAME", "Dev B")
    assert cfg.get_hostname() == "mac-dev-B"
    assert cfg.get_device_name() == "Dev B"


def test_hostname_falls_back_to_platform_node(
    _isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans override → comportement de production (platform.node())."""
    monkeypatch.delenv("FONTSYNC_HOSTNAME", raising=False)
    monkeypatch.setattr(config_module.platform, "node", lambda: "real-mac")
    assert AgentConfig.load().get_hostname() == "real-mac"
