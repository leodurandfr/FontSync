"""Lecture et gestion de la configuration de l'agent FontSync.

La config (`~/.fontsync/config.yaml`) est le **seul** état persistant de l'agent
avec le cache de hash : elle porte l'identité du device (`device_id`/token)
établie au premier `register`, ainsi que les préférences de scan/sync. Tout le
reste de l'agent est stateless (cf. PLAN.md).

Schéma YAML :

    server:
      url: http://…
      device_token: …        # jeton d'appareil, obtenu par `fontsync-agent
                              #   login` (email + mot de passe) ou par l'app Mac
      account_email: …       # le compte de ce jeton (affichage seulement)
      token: …               # HÉRITÉ : token d'instance (= FONTSYNC_TOKEN côté
                              #   serveur), utilisé seulement sans device_token
      device_id: …           # persisté après le 1er enregistrement
    scan:
      directories: [...]
      ingest_directories: [...]  # sous-ensemble alimentant la bibliothèque
                                  #   synchronisée (le reste est scanné/déclaré
                                  #   mais jamais poussé, cf. PLAN-ETATS-FONTS.md §4)
      ignore_patterns: [...]
    sync:
      auto_pull: false        # le serveur fait foi ; ceci n'est que le défaut
      auto_push: true         #   envoyé au premier `register`

Les deux « tokens » : depuis les comptes, l'agent s'authentifie avec son
**jeton d'appareil** (`server.device_token`), propre à ce Mac et à son compte,
révocable seul depuis l'interface web. Le **token d'instance** hérité
(`server.token`, = `FONTSYNC_TOKEN`) n'est envoyé qu'à défaut, le temps de la
migration (`auth_token`).
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.paths import state_dir

CONFIG_DIR = state_dir()
CONFIG_FILE = CONFIG_DIR / "config.yaml"

_DISTRIBUTION = "fontsync-agent"
# Le serveur refuse au-delà (schéma `DeviceRegister.agent_version`) : un
# enregistrement refusé arrêterait tous les syncs.
_MAX_VERSION_LENGTH = 20


def _resolve_version(package_root: Path | None = None) -> str:
    """Version du paquet de l'agent, telle que déclarée au serveur.

    Depuis le dépôt, `pyproject.toml` fait foi (une installation éditable
    garde la version du moment où elle a été faite) ; dans l'app, le dépôt est
    installé comme distribution et sa métadonnée la porte. À défaut :
    `0+unknown`, jamais une constante qui dérive en silence. Ne lève jamais :
    appelée à l'import de toutes les commandes de l'agent.
    """
    root = package_root or Path(__file__).resolve().parents[1]
    version: str | None = None
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle).get("project")
        if (
            isinstance(project, dict)
            and project.get("name") == _DISTRIBUTION
            and project.get("version")
        ):
            version = str(project["version"])
    except (OSError, ValueError):  # ValueError : TOML ou UTF-8 invalide
        pass
    if version is None:
        try:
            version = importlib.metadata.version(_DISTRIBUTION)
        except importlib.metadata.PackageNotFoundError:
            version = "0+unknown"
    if len(version) > _MAX_VERSION_LENGTH:
        version = version.split("+", 1)[0][:_MAX_VERSION_LENGTH]
    return version


AGENT_VERSION = _resolve_version()

# Dossiers de fonts macOS (per-user + système partagé, pas /System/Library/Fonts)
DEFAULT_MACOS_DIRECTORIES = [
    str(Path.home() / "Library" / "Fonts"),
    "/Library/Fonts",
]
DEFAULT_IGNORE_PATTERNS = [".*", "System*"]
# Sous-ensemble de `directories` qui alimente la bibliothèque synchronisée
# (§4 PLAN-ETATS-FONTS.md) : `/Library/Fonts` reste scanné et déclaré (retirer
# la découverte serait non déterministe et ferait quarantiner en masse), mais
# ce que ce dossier contient n'est plus candidat au push — `ingestible=False`.
DEFAULT_INGEST_DIRECTORIES = [str(Path.home() / "Library" / "Fonts")]


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
    # HÉRITÉ : token partagé d'instance, envoyé seulement sans `device_token`.
    server_token: str | None = None
    # Jeton d'appareil (compte), envoyé en `Authorization: Bearer`.
    device_token: str | None = None
    # Compte du jeton d'appareil : affichage seulement (`status`, app Mac).
    account_email: str | None = None
    device_id: str | None = None
    directories: list[str] = field(
        default_factory=lambda: list(DEFAULT_MACOS_DIRECTORIES)
    )
    ingest_directories: list[str] = field(
        default_factory=lambda: list(DEFAULT_INGEST_DIRECTORIES)
    )
    ignore_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS)
    )
    auto_push: bool = True
    auto_pull: bool = False

    @property
    def auth_token(self) -> str | None:
        """Le secret envoyé en `Authorization: Bearer`.

        Le jeton d'appareil d'abord ; le token d'instance hérité seulement à
        défaut (migration). `None` : en-tête omis.
        """
        return self.device_token or self.server_token or None

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
            server_token=server.get("token", defaults.server_token),
            device_token=server.get("device_token", defaults.device_token),
            account_email=server.get("account_email", defaults.account_email),
            device_id=server.get("device_id", defaults.device_id),
            directories=scan.get("directories", defaults.directories),
            ingest_directories=scan.get(
                "ingest_directories", defaults.ingest_directories
            ),
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
                "token": self.server_token,
                "device_token": self.device_token,
                "account_email": self.account_email,
                "device_id": self.device_id,
            },
            "scan": {
                "directories": self.directories,
                "ingest_directories": self.ingest_directories,
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
