"""Lecture et gestion de la configuration de l'agent FontSync."""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".fontsync"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

AGENT_VERSION = "0.1.0"

# Dossiers de fonts macOS (per-user + système partagé, pas /System/Library/Fonts)
DEFAULT_MACOS_DIRECTORIES = [
    str(Path.home() / "Library" / "Fonts"),
    "/Library/Fonts",
]


@dataclass
class AgentConfig:
    """Configuration de l'agent FontSync."""

    server_url: str = "http://localhost:8080"
    device_token: str | None = None
    device_id: str | None = None
    scan_interval_minutes: int = 5
    directories: list[str] = field(default_factory=lambda: list(DEFAULT_MACOS_DIRECTORIES))
    ignore_patterns: list[str] = field(default_factory=lambda: [".*", "System*"])
    auto_push: bool = True
    auto_pull: bool = True
    show_notifications: bool = True

    @classmethod
    def load(cls) -> AgentConfig:
        """Charge la configuration depuis ~/.fontsync/config.yaml.

        Crée le fichier avec les valeurs par défaut s'il n'existe pas.
        """
        if not CONFIG_FILE.exists():
            config = cls()
            config.save()
            return config

        with open(CONFIG_FILE) as f:
            raw = yaml.safe_load(f) or {}

        server = raw.get("server", {})
        scan = raw.get("scan", {})
        sync = raw.get("sync", {})

        return cls(
            server_url=server.get("url", "http://localhost:8080"),
            device_token=server.get("device_token"),
            device_id=server.get("device_id"),
            scan_interval_minutes=scan.get("interval_minutes", 5),
            directories=scan.get("directories", list(DEFAULT_MACOS_DIRECTORIES)),
            ignore_patterns=scan.get("ignore_patterns", [".*", "System*"]),
            auto_push=sync.get("auto_push", True),
            auto_pull=sync.get("auto_pull", False),
        )

    def save(self) -> None:
        """Persiste la configuration dans ~/.fontsync/config.yaml."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        data = {
            "server": {
                "url": self.server_url,
                "device_token": self.device_token,
                "device_id": self.device_id,
            },
            "scan": {
                "interval_minutes": self.scan_interval_minutes,
                "directories": self.directories,
                "ignore_patterns": self.ignore_patterns,
            },
            "sync": {
                "auto_push": self.auto_push,
                "auto_pull": self.auto_pull,
            },
        }

        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    def get_device_name(self) -> str:
        """Retourne un nom lisible pour ce device."""
        return platform.node() or "Mac inconnu"

    def get_hostname(self) -> str:
        return platform.node()

    def get_os_version(self) -> str:
        return platform.mac_ver()[0] or platform.version()
