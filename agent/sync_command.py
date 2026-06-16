"""Commande `sync` stateless de l'agent FontSync.

Flux complet, identique quelle que soit la source du déclenchement
(launchd `WatchPaths`, `StartInterval`, ou signal SSE relayé par `listen`) :

    discover → hash → register/update device → POST /sync/delta
    → push inconnues → pull manquantes (si auto_pull) → install → exit

**Aucun état global mutable.** Chaque exécution repart de l'état réel du disque
et de la réponse delta du serveur (source de vérité). La seule chose persistée
est l'identité du device (`device_id`), pas un état de synchronisation.

HTTP synchrone (`httpx` via `SyncClient`) : la commande est courte et n'a pas
d'event loop → pas de risque de blocage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agent.config import AgentConfig
from agent.discovery import discover_fonts
from agent.font_installer import install_font
from agent.hash_cache import HashCache
from agent.hashing import ScannedFont, scan_fonts

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Échec fatal d'une exécution `sync` (impossible de joindre le serveur)."""


class _Client(Protocol):
    """Interface minimale attendue du client HTTP (cf. `agent.sync_client.SyncClient`)."""

    def register_device(self) -> dict[str, Any]: ...

    def delta_sync(
        self, device_id: str, fonts: "Sequence[ScannedFont]"
    ) -> dict[str, Any]: ...

    def push_fonts(
        self,
        device_id: str,
        fonts: "Sequence[ScannedFont]",
        hashes_to_push: set[str],
    ) -> tuple[int, int, int]: ...

    def pull_font(self, font_id: str, device_id: str) -> tuple[str, bytes]: ...

    def close(self) -> None: ...


@dataclass
class SyncResult:
    """Bilan chiffré d'une exécution `sync` (pour log et tests)."""

    device_id: str = ""
    discovered: int = 0
    hashed: int = 0
    already_synced: int = 0
    pushed: int = 0
    duplicates: int = 0
    push_errors: int = 0
    push_skipped: int = 0  # inconnues non envoyées (auto_push désactivé)
    installed: int = 0
    pull_skipped: int = 0  # format non installable (woff/woff2)
    pull_errors: int = 0
    pull_disabled: int = 0  # manquantes non récupérées (auto_pull désactivé)

    def summary(self) -> str:
        return (
            f"device={self.device_id or '?'} | "
            f"découvertes={self.discovered}, déjà sync={self.already_synced} | "
            f"push: {self.pushed} ok, {self.duplicates} doublons, "
            f"{self.push_errors} erreurs, {self.push_skipped} ignorées | "
            f"pull: {self.installed} installées, {self.pull_skipped} non installables, "
            f"{self.pull_errors} erreurs, {self.pull_disabled} ignorées"
        )


def run_sync(config: AgentConfig, *, client: _Client | None = None) -> SyncResult:
    """Exécute une synchronisation complète et retourne son bilan.

    Args:
        config: configuration de l'agent.
        client: client HTTP injectable (pour les tests) ; par défaut un
            `SyncClient` est construit à partir de `config`.

    Raises:
        SyncError: si l'enregistrement du device ou le delta échoue (le serveur
            est injoignable) — rien n'a alors été modifié localement.
    """
    result = SyncResult()
    owns_client = client is None
    if client is None:
        # Import différé : `SyncClient` tire `httpx`, inutile aux tests qui
        # injectent un client factice.
        from agent.sync_client import SyncClient

        client = SyncClient(config)

    try:
        # 1-2. Découverte + hachage de l'état réel du disque. Le cache de hash
        #    (clé path/size/mtime) évite de re-hacher les fonts inchangées ; il
        #    est réécrit dès le scan terminé, car le travail de hachage est
        #    valide quelle que soit l'issue des étapes réseau suivantes.
        discovered = discover_fonts(config.directories, config.ignore_patterns)
        result.discovered = len(discovered)
        cache = HashCache.load()
        scanned = scan_fonts(discovered, cache=cache)
        cache.save()
        result.hashed = len(scanned)
        logger.info(
            "Scan local : %d fonts découvertes, %d hachées",
            result.discovered,
            result.hashed,
        )

        # 3. Enregistrement / mise à jour du device. Le serveur est la source de
        #    vérité pour auto_pull/auto_push (pilotés depuis le frontend).
        try:
            device = client.register_device()
        except Exception as e:  # noqa: BLE001 — remonté en SyncError fatale
            raise SyncError(f"enregistrement du device impossible : {e}") from e

        device_id = str(device["id"])
        result.device_id = device_id
        if config.device_id != device_id:
            config.device_id = device_id
            config.save()

        auto_pull = bool(device.get("autoPull", config.auto_pull))
        auto_push = bool(device.get("autoPush", config.auto_push))

        # 4. Delta sync : lecture pure côté serveur.
        try:
            delta = client.delta_sync(device_id, scanned)
        except Exception as e:  # noqa: BLE001 — remonté en SyncError fatale
            raise SyncError(f"delta sync impossible : {e}") from e

        unknown: set[str] = set(delta.get("unknownToServer", []))
        missing: list[dict[str, Any]] = delta.get("missingOnDevice", [])
        result.already_synced = int(delta.get("alreadySynced", 0))
        logger.info(
            "Delta : %d à pusher, %d à puller, %d déjà synchronisées",
            len(unknown),
            len(missing),
            result.already_synced,
        )

        # 5. Push des fonts inconnues du serveur.
        if unknown and auto_push:
            result.pushed, result.duplicates, result.push_errors = client.push_fonts(
                device_id, scanned, unknown
            )
        elif unknown:
            result.push_skipped = len(unknown)
            logger.info(
                "%d fonts à envoyer ignorées (auto_push désactivé)", len(unknown)
            )

        # 6. Pull + installation des fonts manquantes localement.
        if missing and auto_pull:
            for ref in missing:
                _pull_and_install(client, device_id, ref, result)
        elif missing:
            result.pull_disabled = len(missing)
            logger.info(
                "%d fonts disponibles ignorées (auto_pull désactivé)", len(missing)
            )

    finally:
        if owns_client:
            client.close()

    logger.info("Sync terminé — %s", result.summary())
    return result


def _pull_and_install(
    client: _Client, device_id: str, ref: dict[str, Any], result: SyncResult
) -> None:
    """Récupère puis installe une font manquante. Une erreur isolée n'arrête pas le sync."""
    font_id = ref.get("id")
    label = ref.get("originalFilename") or font_id or "?"
    if not font_id:
        logger.warning("Référence de font sans id, ignorée : %s", ref)
        result.pull_errors += 1
        return

    # Le hash attendu (issu du delta serveur) sert de vérification d'intégrité et
    # d'identité pour l'anti-écrasement ; absent → installation sans vérification.
    expected_hash = ref.get("fileHash")
    try:
        filename, data = client.pull_font(str(font_id), device_id)
        dest = install_font(filename, data, expected_hash=expected_hash)
        if dest is not None:
            result.installed += 1
            logger.info("Installée : %s", filename)
        else:
            # Format non installable (woff/woff2) : téléchargé mais pas posé.
            result.pull_skipped += 1
    except Exception:
        logger.exception("Échec pull/install de %s", label)
        result.pull_errors += 1


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main() -> int:
    """Point d'entrée CLI de la commande `sync`. Retourne un code de sortie."""
    _configure_logging()
    config = AgentConfig.load()
    try:
        run_sync(config)
    except SyncError as e:
        logger.error("Sync échoué : %s", e)
        return 1
    return 0
