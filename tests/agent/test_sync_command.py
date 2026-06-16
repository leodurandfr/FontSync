"""Tests de la commande `sync` stateless de l'agent (B1).

On injecte un client HTTP factice et on remplace découverte/hachage/installation
par des stubs : aucun réseau ni filesystem réel n'est touché. On vérifie le flux
complet (discover → hash → register → delta → push → pull → install), le respect
des drapeaux serveur `autoPull`/`autoPush`, et l'absence d'état mutable entre runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent import sync_command
from agent.config import AgentConfig
from agent.hashing import ScannedFont
from agent.sync_command import SyncError, run_sync


class FakeClient:
    """Client HTTP factice : réponses canned + journal des appels."""

    def __init__(
        self,
        *,
        device: dict[str, Any] | None = None,
        delta: dict[str, Any] | None = None,
        register_raises: Exception | None = None,
    ) -> None:
        self._device = device or {"id": "dev-123", "autoPull": True, "autoPush": True}
        self._delta = delta or {
            "unknownToServer": [],
            "missingOnDevice": [],
            "alreadySynced": 0,
        }
        self._register_raises = register_raises
        self.pushed_hashes: set[str] | None = None
        self.pulled_ids: list[str] = []
        self.closed = False

    def register_device(self) -> dict[str, Any]:
        if self._register_raises is not None:
            raise self._register_raises
        return self._device

    def delta_sync(self, device_id: str, fonts: list[ScannedFont]) -> dict[str, Any]:
        return self._delta

    def push_fonts(
        self, device_id: str, fonts: list[ScannedFont], hashes_to_push: set[str]
    ) -> tuple[int, int, int]:
        self.pushed_hashes = set(hashes_to_push)
        return len(hashes_to_push), 0, 0

    def pull_font(self, font_id: str, device_id: str) -> tuple[str, bytes]:
        self.pulled_ids.append(font_id)
        return f"{font_id}.ttf", b"FAKEFONTDATA"

    def close(self) -> None:
        self.closed = True


class _NoopCache:
    """Cache de hash factice : ne touche jamais le disque pendant les tests."""

    @classmethod
    def load(cls, *a: Any, **k: Any) -> "_NoopCache":
        return cls()

    def save(self) -> None:
        pass


def _stub_scan(monkeypatch: pytest.MonkeyPatch, hashes: list[str]) -> None:
    """Remplace discover/scan/cache par des stubs renvoyant `len(hashes)` fonts."""
    fonts = [
        ScannedFont(
            path=Path(f"/fake/{h}.ttf"),
            filename=f"{h}.ttf",
            file_hash=h,
            file_size=1000 + i,
        )
        for i, h in enumerate(hashes)
    ]
    monkeypatch.setattr(sync_command, "discover_fonts", lambda *a, **k: list(fonts))
    monkeypatch.setattr(sync_command, "scan_fonts", lambda *a, **k: list(fonts))
    monkeypatch.setattr(sync_command, "HashCache", _NoopCache)


def _config() -> AgentConfig:
    cfg = AgentConfig()
    # Ne jamais écrire sur le disque pendant les tests.
    cfg.save = lambda: None  # type: ignore[method-assign]
    return cfg


def test_full_flow_push_pull_install(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_scan(monkeypatch, ["a" * 64, "b" * 64])
    installed: list[str] = []
    monkeypatch.setattr(
        sync_command,
        "install_font",
        lambda fn, data, **kw: installed.append(fn) or Path(fn),
    )

    client = FakeClient(
        delta={
            "unknownToServer": ["a" * 64],
            "missingOnDevice": [
                {"id": "font-1", "originalFilename": "Inter.ttf"},
                {"id": "font-2", "originalFilename": "Roboto.ttf"},
            ],
            "alreadySynced": 1,
        }
    )

    result = run_sync(_config(), client=client)

    assert result.discovered == 2
    assert result.hashed == 2
    assert result.already_synced == 1
    # Push : seule la font inconnue du serveur est envoyée.
    assert client.pushed_hashes == {"a" * 64}
    assert result.pushed == 1
    # Pull : les deux fonts manquantes sont récupérées puis installées.
    assert client.pulled_ids == ["font-1", "font-2"]
    assert result.installed == 2
    assert installed == ["font-1.ttf", "font-2.ttf"]


def test_persists_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_scan(monkeypatch, [])
    cfg = AgentConfig()
    saved = {"count": 0}
    cfg.save = lambda: saved.__setitem__("count", saved["count"] + 1)  # type: ignore[method-assign]

    run_sync(cfg, client=FakeClient(device={"id": "dev-xyz"}))

    assert cfg.device_id == "dev-xyz"
    assert saved["count"] == 1


def test_respects_server_auto_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_scan(monkeypatch, ["c" * 64])
    monkeypatch.setattr(sync_command, "install_font", lambda fn, data, **kw: Path(fn))

    client = FakeClient(
        device={"id": "d", "autoPull": False, "autoPush": False},
        delta={
            "unknownToServer": ["c" * 64],
            "missingOnDevice": [{"id": "font-9", "originalFilename": "X.ttf"}],
            "alreadySynced": 0,
        },
    )

    result = run_sync(_config(), client=client)

    # Rien n'est poussé ni installé : drapeaux serveur à False font foi.
    assert client.pushed_hashes is None
    assert client.pulled_ids == []
    assert result.push_skipped == 1
    assert result.pull_disabled == 1
    assert result.pushed == 0
    assert result.installed == 0


def test_unsupported_format_counts_as_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_scan(monkeypatch, [])
    # install_font renvoie None pour un format non installable (woff/woff2).
    monkeypatch.setattr(sync_command, "install_font", lambda fn, data, **kw: None)

    client = FakeClient(
        delta={
            "unknownToServer": [],
            "missingOnDevice": [{"id": "font-w", "originalFilename": "X.woff2"}],
            "alreadySynced": 0,
        }
    )

    result = run_sync(_config(), client=client)

    assert client.pulled_ids == ["font-w"]
    assert result.installed == 0
    assert result.pull_skipped == 1


def test_register_failure_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_scan(monkeypatch, ["d" * 64])
    client = FakeClient(register_raises=ConnectionError("serveur down"))

    with pytest.raises(SyncError):
        run_sync(_config(), client=client)

    # Échec avant tout push : rien n'a été modifié.
    assert client.pushed_hashes is None


def test_stateless_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deux runs identiques → bilans identiques (aucune accumulation d'état)."""
    _stub_scan(monkeypatch, ["e" * 64])
    monkeypatch.setattr(sync_command, "install_font", lambda fn, data, **kw: Path(fn))
    delta = {
        "unknownToServer": ["e" * 64],
        "missingOnDevice": [{"id": "f1", "originalFilename": "A.ttf"}],
        "alreadySynced": 0,
    }

    r1 = run_sync(_config(), client=FakeClient(delta=dict(delta)))
    r2 = run_sync(_config(), client=FakeClient(delta=dict(delta)))

    assert (r1.pushed, r1.installed) == (1, 1)
    assert (r2.pushed, r2.installed) == (1, 1)
