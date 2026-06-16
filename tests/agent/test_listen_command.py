"""Tests du process `listen` SSE de l'agent (B4).

On teste les moitiés pures du listener sans réseau ni threads réels :
- parsing SSE (signaux `sync` vs keep-alive) ;
- debounce/coalescing du consommateur (une rafale → un seul `run`) ;
- reconnexion du producteur après coupure du flux ;
- résolution de l'id de device (caché vs enregistrement).
"""

from __future__ import annotations

import queue
import threading
from typing import Any

from agent import listen_command
from agent.config import AgentConfig
from agent.listen_command import (
    _consume_signals,
    _produce_signals,
    _resolve_device_id,
    parse_sse_signals,
    run_listen,
)


def _config() -> AgentConfig:
    cfg = AgentConfig()
    cfg.save = lambda: None  # type: ignore[method-assign]
    return cfg


# ---- parse_sse_signals ----


def test_parse_counts_only_sync_events() -> None:
    lines = [
        "event: sync",
        "data: {}",
        "",
        ": keep-alive",
        "",
        "event: sync",
        "data: {}",
        "",
    ]
    assert list(parse_sse_signals(lines)) == [None, None]


def test_parse_ignores_keepalive_and_blank() -> None:
    lines = [": keep-alive", "", ": keep-alive", ""]
    assert list(parse_sse_signals(lines)) == []


# ---- _consume_signals (debounce / coalescing) ----


def test_consume_coalesces_burst_into_single_run() -> None:
    q: queue.Queue[None] = queue.Queue()
    for _ in range(5):
        q.put(None)
    stop = threading.Event()
    runs: list[Any] = []

    def run(cfg: AgentConfig) -> None:
        runs.append(cfg)
        stop.set()  # un seul run suffit pour ce test

    _consume_signals(q, run, _config(), stop, debounce=0.0)

    # Les 5 signaux groupés n'ont déclenché qu'un seul sync, et la file est vide.
    assert len(runs) == 1
    assert q.empty()


def test_consume_run_failure_does_not_propagate() -> None:
    q: queue.Queue[None] = queue.Queue()
    q.put(None)
    stop = threading.Event()
    calls = {"n": 0}

    def run(cfg: AgentConfig) -> None:
        calls["n"] += 1
        stop.set()
        raise RuntimeError("sync cassé")

    # Ne doit pas lever : l'échec est journalisé, le listener survit.
    _consume_signals(q, run, _config(), stop, debounce=0.0)
    assert calls["n"] == 1


def test_consume_exits_immediately_when_already_stopped() -> None:
    q: queue.Queue[None] = queue.Queue()
    q.put(None)
    stop = threading.Event()
    stop.set()
    runs: list[Any] = []

    _consume_signals(q, runs.append, _config(), stop, debounce=0.0)
    assert runs == []


# ---- _produce_signals (reconnexion) ----


def test_produce_reconnects_after_stream_drops() -> None:
    q: queue.Queue[None] = queue.Queue()
    stop = threading.Event()
    calls = {"n": 0}

    def factory() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            # Première connexion : deux signaux puis fin propre du flux.
            yield None
            yield None
            return
        # Deuxième connexion : échec → on arme stop pour terminer le test.
        stop.set()
        raise ConnectionError("flux coupé")

    _produce_signals(factory, q, stop, reconnect_delay=0.0)

    assert calls["n"] == 2  # a bien retenté après la fin du 1er flux
    assert q.qsize() == 2  # les deux signaux ont été empilés


def test_produce_stops_without_calling_factory_when_already_stopped() -> None:
    q: queue.Queue[None] = queue.Queue()
    stop = threading.Event()
    stop.set()
    calls = {"n": 0}

    def factory() -> Any:
        calls["n"] += 1
        return iter(())

    _produce_signals(factory, q, stop, reconnect_delay=0.0)
    assert calls["n"] == 0


# ---- _resolve_device_id ----


def test_resolve_uses_cached_device_id() -> None:
    cfg = _config()
    cfg.device_id = "dev-cached"

    class BoomClient:
        def register_device(self) -> dict[str, Any]:
            raise AssertionError("ne doit pas enregistrer si l'id est connu")

        def close(self) -> None:
            pass

    assert _resolve_device_id(cfg, client=BoomClient()) == "dev-cached"


def test_resolve_registers_and_persists_when_unknown() -> None:
    cfg = _config()
    saved = {"n": 0}
    cfg.save = lambda: saved.__setitem__("n", saved["n"] + 1)  # type: ignore[method-assign]

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def register_device(self) -> dict[str, Any]:
            return {"id": "dev-new"}

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    assert _resolve_device_id(cfg, client=client) == "dev-new"
    assert cfg.device_id == "dev-new"
    assert saved["n"] == 1
    # Client injecté : c'est l'appelant qui le ferme, pas `_resolve_device_id`.
    assert client.closed is False


# ---- run_listen (intégration légère, threads réels) ----


def test_run_listen_triggers_run_then_stops() -> None:
    stop = threading.Event()
    runs: list[Any] = []

    def run(cfg: AgentConfig) -> None:
        runs.append(cfg)
        stop.set()

    def factory() -> Any:
        # Un signal, puis on bloque jusqu'à l'arrêt pour ne pas boucler.
        yield None
        stop.wait(1.0)

    run_listen(
        _config(),
        run=run,
        signals_factory=factory,
        debounce=0.0,
        reconnect_delay=0.0,
        stop=stop,
    )
    assert len(runs) == 1


def test_module_exposes_main() -> None:
    assert callable(listen_command.main)
