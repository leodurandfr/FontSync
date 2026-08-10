"""Commande `sync` stateless de l'agent FontSync.

Flux complet, identique quelle que soit la source du déclenchement
(launchd `WatchPaths`, `StartInterval`, ou signal SSE relayé par `listen`) :

    discover → hash → register/update device → POST /sync/delta
    → push inconnues → désinstaller les tombées → pull manquantes (si auto_pull)
    → install → exit

**Aucun état global mutable.** Chaque exécution repart de l'état réel du disque
et de la réponse delta du serveur (source de vérité). La seule chose persistée
est l'identité du device (`device_id`), pas un état de synchronisation.

Ce que l'agent déclare au serveur est devenu **la mesure de ce qu'il possède**,
et plus seulement de quoi calculer des ajouts : le serveur en déduit ce qui a
disparu de la machine. Deux conséquences, toutes deux dans `_declared_fonts` :

- le dossier `~/.fontsync/disabled/` est déclaré lui aussi. `deactivate_font` y
  déplace les fichiers, et il n'appartient à aucun `scan.directories` : sans ça
  une police simplement *désactivée* serait vue comme supprimée et effacée de
  toutes les machines ;
- la découverte s'appuie sur le disque (cf. `agent.discovery`), pas sur le seul
  index de macOS, qui peut se figer et faire disparaître de sa vue des fichiers
  bien présents.

HTTP synchrone (`httpx` via `SyncClient`) : la commande est courte et n'a pas
d'event loop → pas de risque de blocage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agent.config import AgentConfig
from agent.discovery import DiscoveredFont, discover_fonts, discover_via_directories
from agent.font_installer import (
    DISABLED_DIR,
    install_font,
    reindex_installed,
    uninstall_font,
)
from agent.font_registry import REINDEX_DELAY_HINT_SECONDS
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
    ) -> tuple[int, int, int, int]: ...

    def pull_font(self, font_id: str, device_id: str) -> tuple[str, bytes]: ...

    def close(self) -> None: ...


@dataclass
class SyncResult:
    """Bilan chiffré d'une exécution `sync` (pour log et tests)."""

    device_id: str = ""
    discovered: int = 0
    deactivated: int = 0  # déclarées depuis ~/.fontsync/disabled/
    hashed: int = 0
    already_synced: int = 0
    pushed: int = 0
    duplicates: int = 0
    push_errors: int = 0
    push_skipped: int = 0  # inconnues non envoyées (auto_push désactivé)
    push_refused: int = 0  # refusées car supprimées côté serveur (pas une erreur)
    installed: int = 0
    pull_skipped: int = 0  # format non installable (woff/woff2)
    pull_errors: int = 0
    pull_disabled: int = 0  # manquantes non récupérées (auto_pull désactivé)
    deleted_on_server: int = 0  # détenues ici mais tombées côté serveur
    uninstalled: int = 0
    uninstall_missing: int = 0  # aucun fichier correspondant (déjà partie)
    uninstall_errors: int = 0
    reindex_triggered: bool = False  # réindexation macOS amorcée (effet différé)

    def summary(self) -> str:
        reindex = (
            f" | réindexation macOS amorcée (jusqu'à ~{REINDEX_DELAY_HINT_SECONDS} s)"
            if self.reindex_triggered
            else ""
        )
        # La ligne « supprimées » n'apparaît que s'il y a quelque chose à dire :
        # en régime normal, ne rien supprimer ne mérite pas une colonne de zéros.
        deletions = (
            f" | supprimées: {self.deleted_on_server} tombées côté serveur, "
            f"{self.uninstalled} désinstallées, {self.uninstall_missing} absentes, "
            f"{self.uninstall_errors} erreurs"
            if self.deleted_on_server or self.uninstalled or self.uninstall_errors
            else ""
        )
        return (
            f"device={self.device_id or '?'} | "
            f"découvertes={self.discovered} (dont {self.deactivated} désactivées), "
            f"déjà sync={self.already_synced} | "
            f"push: {self.pushed} ok, {self.duplicates} doublons, "
            f"{self.push_errors} erreurs, {self.push_skipped} ignorées, "
            f"{self.push_refused} refusées (supprimées) | "
            f"pull: {self.installed} installées, {self.pull_skipped} non installables, "
            f"{self.pull_errors} erreurs, {self.pull_disabled} ignorées"
            f"{deletions}"
            f"{reindex}"
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
        discovered, result.deactivated = _declared_fonts(config)
        result.discovered = len(discovered)
        cache = HashCache.load()
        scanned = scan_fonts(discovered, cache=cache)
        cache.save()
        result.hashed = len(scanned)
        logger.info(
            "Scan local : %d fonts découvertes (dont %d désactivées), %d hachées",
            result.discovered,
            result.deactivated,
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
        to_uninstall: list[dict[str, Any]] = delta.get("toUninstall", [])
        result.already_synced = int(delta.get("alreadySynced", 0))
        result.deleted_on_server = int(delta.get("deletedOnServer", 0))
        logger.info(
            "Delta : %d à pusher, %d à puller, %d à désinstaller, "
            "%d déjà synchronisées",
            len(unknown),
            len(missing),
            len(to_uninstall),
            result.already_synced,
        )

        # 5. Push des fonts inconnues du serveur.
        if unknown and auto_push:
            (
                result.pushed,
                result.duplicates,
                result.push_errors,
                result.push_refused,
            ) = client.push_fonts(device_id, scanned, unknown)
        elif unknown:
            result.push_skipped = len(unknown)
            logger.info(
                "%d fonts à envoyer ignorées (auto_push désactivé)", len(unknown)
            )

        # 6. Désinstallation des fonts tombées côté serveur. La liste est vide
        #    tant que la propagation n'est pas activée sur cet appareil : c'est
        #    le serveur qui arbitre, l'agent ne fait qu'exécuter.
        for ref in to_uninstall:
            _uninstall(ref, result)

        # 7. Pull + installation des fonts manquantes localement.
        if missing and auto_pull:
            for ref in missing:
                _pull_and_install(client, device_id, ref, result)
        elif missing:
            result.pull_disabled = len(missing)
            logger.info(
                "%d fonts disponibles ignorées (auto_pull désactivé)", len(missing)
            )

        # 8. Une seule réindexation macOS pour tout le lot, poses et retraits
        #    confondus : la reconstruction de l'index repartirait de zéro si on
        #    la relançait par fichier.
        if result.installed or result.uninstalled:
            result.reindex_triggered = reindex_installed()

    finally:
        if owns_client:
            client.close()

    logger.info("Sync terminé — %s", result.summary())
    return result


def _declared_fonts(config: AgentConfig) -> tuple[list[DiscoveredFont], int]:
    """Ce que cette machine possède réellement : dossiers de polices + désactivées.

    `~/.fontsync/disabled/` n'appartient à aucun `scan.directories` — c'est le
    dossier où `deactivate_font` met les polices retirées de la circulation. Ne
    pas le déclarer reviendrait à dire au serveur que ces polices n'existent
    plus : il les mettrait en quarantaine et **toutes** les machines les
    effaceraient. Une police désactivée est présente, simplement inactive.

    Returns:
        (fonts déclarées, nombre venant du dossier `disabled/`).
    """
    fonts = discover_fonts(config.directories, config.ignore_patterns)
    deactivated = discover_via_directories([str(DISABLED_DIR)], config.ignore_patterns)
    known = {str(f.path.resolve()) for f in fonts}
    added = [f for f in deactivated if str(f.path.resolve()) not in known]
    return fonts + added, len(added)


def _uninstall(ref: dict[str, Any], result: SyncResult) -> None:
    """Retire une font tombée côté serveur. Une erreur isolée n'arrête pas le sync.

    La suppression reste gardée par le hash côté `font_installer` : une police
    personnelle homonyme n'est jamais touchée. Un fichier introuvable n'est pas
    une erreur — la police a pu être retirée à la main entre deux syncs.
    """
    filename = ref.get("originalFilename")
    file_hash = ref.get("fileHash")
    if not filename or not file_hash:
        logger.warning("Référence de désinstallation incomplète, ignorée : %s", ref)
        result.uninstall_errors += 1
        return

    try:
        # `refresh_index=False` : réindexation groupée en fin de sync.
        if uninstall_font(str(filename), str(file_hash), refresh_index=False):
            result.uninstalled += 1
            logger.info("Désinstallée (supprimée côté serveur) : %s", filename)
        else:
            result.uninstall_missing += 1
    except Exception:
        logger.exception("Échec de la désinstallation de %s", filename)
        result.uninstall_errors += 1


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
        # `refresh_index=False` : la réindexation est faite une fois pour tout le
        # lot par `run_sync` (étape 6bis).
        dest = install_font(
            filename, data, expected_hash=expected_hash, refresh_index=False
        )
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
