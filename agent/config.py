"""Lecture et gestion de la configuration de l'agent FontSync.

La config (`~/.fontsync/config.yaml`) est le **seul** état persistant de l'agent
avec le cache de hash : elle porte l'identité du device (`device_id`/token)
établie au premier `register`, ainsi que les préférences de scan/sync. Tout le
reste de l'agent est stateless (cf. PLAN.md).

Schéma YAML :

    server:
      url: http://…
      device_token: …        # réservé à une future auth (pas d'auth au MVP)
      device_id: …           # persisté après le 1er enregistrement
    scan:
      directories: [...]
      ignore_patterns: [...]
    sync:
      auto_pull: false        # le serveur fait foi ; ceci n'est que le défaut
      auto_push: true         #   envoyé au premier `register`
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.paths import state_dir

CONFIG_DIR = state_dir()
CONFIG_FILE = CONFIG_DIR / "config.yaml"

AGENT_VERSION = "0.1.0"

# Dossiers de fonts macOS (per-user + système partagé, pas /System/Library/Fonts)
DEFAULT_MACOS_DIRECTORIES = [
    str(Path.home() / "Library" / "Fonts"),
    "/Library/Fonts",
]
DEFAULT_IGNORE_PATTERNS = [".*", "System*"]


@dataclass
class AgentConfig:
    """Configuration de l'agent FontSync.

    Les défauts définis ici sont l'**unique** source de vérité : `load()` les
    réutilise pour toute clé absente du fichier, ce qui empêche le défaut d'un
    champ de diverger entre le dataclass et la lecture.

    `auto_pull` / `auto_push` ne sont que les valeurs envoyées au premier
    enregistrement : ensuite, c'est le serveur qui fait foi (piloté via le
    frontend). Leurs défauts s'alignent sur ceux du serveur
    (`backend/models/device.py`) : pull off, push on.
    """

    server_url: str = "http://localhost:8080"
    device_token: str | None = None
    device_id: str | None = None
    directories: list[str] = field(
        default_factory=lambda: list(DEFAULT_MACOS_DIRECTORIES)
    )
    ignore_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS)
    )
    auto_push: bool = True
    auto_pull: bool = False

    @classmethod
    def load(cls) -> AgentConfig:
        """Charge la configuration depuis ~/.fontsync/config.yaml.

        Crée le fichier avec les valeurs par défaut s'il n'existe pas. Toute clé
        absente retombe sur le défaut du dataclass (via une instance `cls()`),
        garantissant un comportement identique « fichier absent » vs « clé
        absente ».
        """
        if not CONFIG_FILE.exists():
            config = cls()
            config.save()
            return config

        with open(CONFIG_FILE) as f:
            raw = yaml.safe_load(f) or {}

        defaults = cls()
        server = raw.get("server") or {}
        scan = raw.get("scan") or {}
        sync = raw.get("sync") or {}

        return cls(
            server_url=server.get("url", defaults.server_url),
            device_token=server.get("device_token", defaults.device_token),
            device_id=server.get("device_id", defaults.device_id),
            directories=scan.get("directories", defaults.directories),
            ignore_patterns=scan.get("ignore_patterns", defaults.ignore_patterns),
            auto_push=sync.get("auto_push", defaults.auto_push),
            auto_pull=sync.get("auto_pull", defaults.auto_pull),
        )

    def save(self) -> None:
        """Persiste la configuration dans ~/.fontsync/config.yaml.

        Écriture atomique (`os.replace`) : un crash en cours d'écriture ne peut
        pas corrompre l'identité persistée (`device_id`/token). Le fichier est
        restreint à l'utilisateur (0600) car il porte un token.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        data = {
            "server": {
                "url": self.server_url,
                "device_token": self.device_token,
                "device_id": self.device_id,
            },
            "scan": {
                "directories": self.directories,
                "ignore_patterns": self.ignore_patterns,
            },
            "sync": {
                "auto_push": self.auto_push,
                "auto_pull": self.auto_pull,
            },
        }

        tmp = CONFIG_FILE.with_suffix(CONFIG_FILE.suffix + ".tmp")
        with open(tmp, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, CONFIG_FILE)
        CONFIG_FILE.chmod(0o600)

    def get_device_name(self) -> str:
        """Retourne un nom lisible pour ce device.

        `FONTSYNC_DEVICE_NAME` permet de le forcer (simulation multi-machines
        en dev) ; non défini → nom de la machine.
        """
        return (
            os.environ.get("FONTSYNC_DEVICE_NAME") or platform.node() or "Mac inconnu"
        )

    def get_hostname(self) -> str:
        """Hostname du device — **clé d'upsert** côté serveur.

        `FONTSYNC_HOSTNAME` permet de le forcer : indispensable pour simuler
        plusieurs devices sur une seule machine (sinon le serveur les fusionne,
        l'enregistrement étant un upsert par hostname). Non défini → machine.
        """
        return os.environ.get("FONTSYNC_HOSTNAME") or platform.node()

    def get_os_version(self) -> str:
        return platform.mac_ver()[0] or platform.version()
