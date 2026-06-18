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
par signal ; le thread principal *consommateur* débounce puis lance `run_sync`.
Ces deux moitiés sont des fonctions pures de leurs entrées (`queue`, `stop`,
factory de signaux) → testables sans réseau ni threads réels.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Any, Callable

from agent.config import AGENT_VERSION, AgentConfig
from agent.sync_client import SyncClientError
from agent.sync_command import SyncError, _configure_logging, run_sync

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


def run_listen(
    config: AgentConfig,
    *,
    run: "Callable[[AgentConfig], Any]" = run_sync,
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
