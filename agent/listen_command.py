"""Process `listen` de l'agent FontSync (B4).

Ouvre une connexion SSE longue durée vers le serveur (`GET
/api/agent/{device_id}/events`) ; à chaque signal « sync » reçu, relance la
commande `sync` stateless. Les signaux sont *debouncés* pour coalescer les
rafales (plusieurs fonts arrivant coup sur coup → un seul `sync`). En cas de
coupure, une boucle de reconnexion triviale (sleep + retry) rétablit le flux.

**Zéro état, zéro hash.** Ce process ne fait que relayer un déclencheur : toute
la sémantique de synchronisation vit dans `run_sync` (et côté serveur, source de
vérité). Le signal SSE n'a pas de payload exploité.

Architecture interne : un thread *producteur* lit le flux SSE et empile un jeton
par signal ; le thread principal *consommateur* débounce puis déclenche un
sync (`trigger_sync` : le job launchd sur le vrai profil, sinon `run_sync`
sous verrou — jamais deux syncs à la fois).
Ces deux moitiés sont des fonctions pures de leurs entrées (`queue`, `stop`,
factory de signaux) → testables sans réseau ni threads réels.
"""

from __future__ import annotations

import logging
import os
import pwd
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from agent.config import AGENT_VERSION, AgentConfig
from agent.paths import sync_rerun_file
from agent.sync_client import SyncClientError
from agent.sync_command import (
    SyncError,
    _configure_logging,
    _release_lock,
    _try_lock,
    request_rerun,
    run_sync,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger(__name__)

# Fenêtre de coalescing : on attend un court instant après un signal pour
# regrouper les signaux suivants en un seul `sync`.
DEBOUNCE_SECONDS = 2.0
# Délai avant tentative de reconnexion après une coupure du flux SSE.
RECONNECT_DELAY_SECONDS = 5.0
# Timeout de lecture du flux SSE : doit dépasser le keep-alive serveur (~25 s)
# pour ne pas couper une connexion saine, tout en finissant par détecter une
# connexion morte silencieuse.
_READ_TIMEOUT_SECONDS = 60.0
# Période de réveil du consommateur pour re-tester `stop` quand aucun signal
# n'arrive (la `queue` n'a pas d'attente interruptible native).
_POLL_INTERVAL_SECONDS = 0.5


def parse_sse_signals(lines: "Iterable[str]") -> "Iterator[None]":
    """Émet un jeton (`None`) par signal `sync` lu dans un flux SSE.

    On ne s'intéresse qu'aux lignes `event: sync` ; le `data:` est ignoré (le
    signal n'a pas de payload exploité) et les commentaires keep-alive
    (`: keep-alive`) sont silencieusement sautés.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("event:"):
            continue
        if stripped.split(":", 1)[1].strip() == "sync":
            yield None


def _stream_signals(config: AgentConfig, device_id: str) -> "Iterator[None]":
    """Ouvre le flux SSE du device et émet un jeton par signal reçu.

    L'itérateur se termine (ou lève) quand la connexion se ferme ou échoue ; la
    reconnexion est gérée par l'appelant (`_produce_signals`).
    """
    # Import différé : `httpx` est inutile aux tests qui injectent une factory.
    import httpx

    url = f"{config.server_url.rstrip('/')}/api/agent/{device_id}/events"
    timeout = httpx.Timeout(
        connect=10.0, read=_READ_TIMEOUT_SECONDS, write=10.0, pool=10.0
    )
    headers = {
        "Accept": "text/event-stream",
        "User-Agent": f"fontsync-agent/{AGENT_VERSION}",
    }
    # Token partagé d'instance (P1.2) : l'agent SSE passe par httpx → en-tête
    # `Authorization` (le query param est réservé à un EventSource navigateur).
    if config.server_token:
        headers["Authorization"] = f"Bearer {config.server_token}"
    with httpx.stream("GET", url, timeout=timeout, headers=headers) as resp:
        resp.raise_for_status()
        logger.info("Flux SSE connecté (%s)", url)
        yield from parse_sse_signals(resp.iter_lines())


def _resolve_device_id(config: AgentConfig, *, client: Any | None = None) -> str:
    """Retourne l'id de ce device, en l'enregistrant auprès du serveur au besoin.

    Le `listen` a besoin de l'id pour construire l'URL SSE. S'il est déjà connu
    (persisté en config par un `sync` antérieur), on l'utilise tel quel ; sinon
    on enregistre le device une fois et on persiste l'id.
    """
    if config.device_id:
        return config.device_id

    owns_client = client is None
    if client is None:
        from agent.sync_client import SyncClient

        client = SyncClient(config)
    try:
        device = client.register_device()
    finally:
        if owns_client:
            client.close()

    device_id = str(device["id"])
    config.device_id = device_id
    config.save()
    logger.info("Device enregistré pour le listener (id=%s)", device_id)
    return device_id


def _drain(q: "queue.Queue[None]") -> None:
    """Vide tous les jetons immédiatement disponibles (coalescing)."""
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass


def _produce_signals(
    signals_factory: "Callable[[], Iterator[None]]",
    q: "queue.Queue[None]",
    stop: threading.Event,
    reconnect_delay: float,
) -> None:
    """Boucle productrice : empile un jeton par signal, reconnecte à la coupure.

    `signals_factory()` ouvre **une** connexion et retourne son itérateur de
    signaux ; quand il se termine ou lève, on attend `reconnect_delay` puis on
    rappelle la factory. S'arrête dès que `stop` est armé.
    """
    while not stop.is_set():
        try:
            for _ in signals_factory():
                if stop.is_set():
                    return
                q.put(None)
        except Exception:
            logger.exception("Connexion au flux d'événements perdue")
        if stop.is_set():
            return
        logger.info("Reconnexion dans %.0fs…", reconnect_delay)
        stop.wait(reconnect_delay)


def _consume_signals(
    q: "queue.Queue[None]",
    run: "Callable[[AgentConfig], Any]",
    config: AgentConfig,
    stop: threading.Event,
    debounce: float,
) -> None:
    """Boucle consommatrice : attend un signal, débounce, puis lance `run`.

    Un échec de `run` est journalisé mais n'arrête pas le listener.
    """
    while not stop.is_set():
        try:
            q.get(timeout=_POLL_INTERVAL_SECONDS)
        except queue.Empty:
            continue
        # Debounce : laisser une rafale s'accumuler, puis tout drainer pour ne
        # déclencher qu'un seul `sync`.
        stop.wait(debounce)
        _drain(q)
        if stop.is_set():
            return
        try:
            run(config)
        except Exception:
            logger.exception("Échec du sync déclenché par signal")


_DEFAULT_SYNC_LABEL = "com.fontsync.sync"


def _run_launchctl(args: list[str]) -> int:
    """`launchctl <args>` ; code de retour, -1 si non lançable (jamais d'exception)."""
    try:
        return subprocess.run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


def _account_home() -> Path:
    """Dossier personnel du COMPTE (base des utilisateurs), pas `$HOME`."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _same_path(value: str, expected: Path) -> bool:
    try:
        return Path(value).expanduser().resolve() == expected.resolve()
    except OSError:
        return False


def _uses_default_home(env: Mapping[str, str]) -> bool:
    """L'agent tourne-t-il sur le vrai profil du compte, et non un profil simulé ?

    Faux dès qu'un des chemins de l'agent est redirigé ailleurs que les défauts
    du compte, ou que `$HOME` lui-même l'est (bac à sable, harnais) : le job
    launchd réel lit le vrai profil, le déclencher depuis un profil simulé
    relancerait la synchronisation de la vraie machine.
    """
    account = _account_home()
    home = env.get("HOME")
    if home and not _same_path(home, account):
        return False
    defaults = {
        "FONTSYNC_HOME": account / ".fontsync",
        "FONTSYNC_FONTS_DIR": account / "Library" / "Fonts",
    }
    for variable, default in defaults.items():
        value = env.get(variable)
        if value and not _same_path(value, default):
            return False
    return True


# Délai avant de vérifier que la demande posée a bien été servie : un job
# qui finissait son tour au moment du `kickstart` (déjà « en cours » pour
# launchd, mais au-delà de sa dernière lecture de la demande) l'aurait ignorée.
_FOLLOW_UP_SECONDS = 3.0


def _lock_is_free() -> bool:
    """Aucun sync ne tient le verrou en ce moment."""
    fd = _try_lock()
    if fd is None:
        return False
    _release_lock(fd)
    return True


def trigger_sync(
    config: AgentConfig,
    *,
    launchctl: "Callable[[list[str]], int]" = _run_launchctl,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    run: "Callable[[AgentConfig], Any]" = run_sync,
    sleep: "Callable[[float], None]" = time.sleep,
) -> Any:
    """Déclenche un sync sans jamais en lancer deux à la fois.

    Pose d'abord la demande de tour (un sync en cours en refera un), puis, sur
    le vrai profil macOS dont le job est chargé, demande à launchd de lancer
    le job `sync` (`kickstart` SANS `-k` : un sync en cours n'est jamais
    tué) — c'est alors le code du job, à jour après une mise à jour de l'app,
    qui tourne, et non celui, peut-être périmé, de ce process `listen`.
    Ailleurs (profil simulé, harnais, `FONTSYNC_NO_KICKSTART`, job absent ou
    kickstart en échec) : `run_sync` dans ce process, protégé par le verrou.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    request_rerun()
    if (
        platform == "darwin"
        and not env.get("FONTSYNC_NO_KICKSTART")
        and _uses_default_home(env)
    ):
        label = env.get("FONTSYNC_LAUNCHD_LABEL") or _DEFAULT_SYNC_LABEL
        target = f"gui/{os.getuid()}/{label}"
        if launchctl(["print", target]) == 0:
            code = launchctl(["kickstart", target])
            if code == 0:
                logger.info("Sync confié au job launchd %s.", label)
                # Si le job finissait au moment du kickstart, la demande est
                # restée en plan : verrou libre + demande présente = personne ne
                # la sert. On relance une fois.
                sleep(_FOLLOW_UP_SECONDS)
                if sync_rerun_file().exists() and _lock_is_free():
                    code = launchctl(["kickstart", target])
                    logger.info(
                        "Demande restée en plan : nouveau kickstart (%d).", code
                    )
                    if code != 0:
                        return run(config)
                return None
            logger.warning(
                "kickstart de %s en échec (code %d) : sync dans ce process.",
                label,
                code,
            )
    return run(config)


def run_listen(
    config: AgentConfig,
    *,
    run: "Callable[[AgentConfig], Any]" = trigger_sync,
    signals_factory: "Callable[[], Iterator[None]] | None" = None,
    debounce: float = DEBOUNCE_SECONDS,
    reconnect_delay: float = RECONNECT_DELAY_SECONDS,
    stop: threading.Event | None = None,
) -> None:
    """Lance le listener : flux SSE (producteur) + débounce/sync (consommateur).

    Args:
        config: configuration de l'agent.
        run: fonction de synchronisation à déclencher (injectable pour tests).
        signals_factory: source des signaux (une connexion par appel) ; par
            défaut, le flux SSE reconnectant vers le serveur.
        debounce: fenêtre de coalescing des signaux, en secondes.
        reconnect_delay: délai entre deux tentatives de connexion SSE.
        stop: `Event` d'arrêt coopératif (sinon créé en interne ; armé sur
            `KeyboardInterrupt`).
    """
    stop = stop or threading.Event()
    if signals_factory is None:
        device_id = _resolve_device_id(config)
        signals_factory = lambda: _stream_signals(config, device_id)  # noqa: E731

    q: "queue.Queue[None]" = queue.Queue()
    producer = threading.Thread(
        target=_produce_signals,
        args=(signals_factory, q, stop, reconnect_delay),
        name="fontsync-listen-sse",
        daemon=True,
    )
    producer.start()
    logger.info("Listener démarré (debounce=%.1fs).", debounce)
    try:
        _consume_signals(q, run, config, stop, debounce)
    except KeyboardInterrupt:
        logger.info("Arrêt du listener demandé.")
    finally:
        stop.set()
        producer.join(timeout=reconnect_delay + 1.0)


def main() -> int:
    """Point d'entrée CLI du process `listen`. Boucle jusqu'à interruption."""
    _configure_logging()
    config = AgentConfig.load()
    try:
        run_listen(config)
    except KeyboardInterrupt:
        pass
    except (SyncClientError, SyncError) as e:
        logger.error("Listener arrêté : %s", e)
        return 1
    return 0
