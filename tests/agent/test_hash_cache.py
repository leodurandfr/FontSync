"""Tests du cache de hash local de l'agent (B2).

Vérifient la validité de clé `(path, size, mtime_ns)`, l'invalidation sur
changement de mtime/taille, l'élagage des chemins disparus à la persistance, la
robustesse face à un fichier corrompu, et l'intégration avec `scan_fonts`
(une font inchangée n'est pas re-hachée).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent import hashing
from agent.discovery import DiscoveredFont
from agent.hash_cache import HashCache
from agent.hashing import hash_file, scan_fonts


def _cache_path(tmp_path: Path) -> Path:
    return tmp_path / "hash_cache.json"


def test_hit_when_size_and_mtime_match(tmp_path: Path) -> None:
    cache = HashCache(_cache_path(tmp_path))
    p = Path("/fonts/A.ttf")
    cache.put(p, size=100, mtime_ns=42, file_hash="h1")

    assert cache.get(p, size=100, mtime_ns=42) == "h1"


def test_miss_on_mtime_change(tmp_path: Path) -> None:
    cache = HashCache(_cache_path(tmp_path))
    p = Path("/fonts/A.ttf")
    cache.put(p, size=100, mtime_ns=42, file_hash="h1")

    assert cache.get(p, size=100, mtime_ns=99) is None


def test_miss_on_size_change(tmp_path: Path) -> None:
    cache = HashCache(_cache_path(tmp_path))
    p = Path("/fonts/A.ttf")
    cache.put(p, size=100, mtime_ns=42, file_hash="h1")

    assert cache.get(p, size=200, mtime_ns=42) is None


def test_miss_on_unknown_path(tmp_path: Path) -> None:
    cache = HashCache(_cache_path(tmp_path))
    assert cache.get(Path("/fonts/unknown.ttf"), size=1, mtime_ns=1) is None


def test_persist_and_reload(tmp_path: Path) -> None:
    path = _cache_path(tmp_path)
    cache = HashCache(path)
    p = Path("/fonts/A.ttf")
    cache.get(p, size=100, mtime_ns=42)  # marque vu
    cache.put(p, size=100, mtime_ns=42, file_hash="h1")
    cache.save()

    reloaded = HashCache.load(path)
    assert reloaded.get(p, size=100, mtime_ns=42) == "h1"


def test_save_prunes_unseen_paths(tmp_path: Path) -> None:
    """Une entrée dont le chemin n'est pas revu pendant le run est élaguée."""
    path = _cache_path(tmp_path)
    cache = HashCache(path)
    stale = Path("/fonts/deleted.ttf")
    fresh = Path("/fonts/kept.ttf")
    cache.put(stale, size=1, mtime_ns=1, file_hash="old")
    cache.put(fresh, size=2, mtime_ns=2, file_hash="new")
    cache.save()

    # Nouveau run : seul `fresh` est revu (get marque vu), `stale` a disparu.
    cache2 = HashCache.load(path)
    assert cache2.get(fresh, size=2, mtime_ns=2) == "new"
    cache2.save()

    cache3 = HashCache.load(path)
    assert cache3.get(fresh, size=2, mtime_ns=2) == "new"
    assert cache3.get(stale, size=1, mtime_ns=1) is None


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    cache = HashCache.load(tmp_path / "does_not_exist.json")
    assert cache.get(Path("/fonts/A.ttf"), size=1, mtime_ns=1) is None


def test_load_corrupted_file_is_empty(tmp_path: Path) -> None:
    path = _cache_path(tmp_path)
    path.write_text("{ not valid json", encoding="utf-8")

    cache = HashCache.load(path)  # ne lève pas
    assert cache.get(Path("/fonts/A.ttf"), size=1, mtime_ns=1) is None


def test_load_skips_corrupted_entries(tmp_path: Path) -> None:
    path = _cache_path(tmp_path)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "/fonts/ok.ttf": {"size": 10, "mtime_ns": 5, "hash": "good"},
                    "/fonts/bad.ttf": {"size": "oops"},  # entrée corrompue
                },
            }
        ),
        encoding="utf-8",
    )

    cache = HashCache.load(path)
    assert cache.get(Path("/fonts/ok.ttf"), size=10, mtime_ns=5) == "good"
    assert cache.get(Path("/fonts/bad.ttf"), size=10, mtime_ns=5) is None


def test_load_wrong_version_is_empty(tmp_path: Path) -> None:
    path = _cache_path(tmp_path)
    path.write_text(
        json.dumps(
            {
                "version": 999,
                "entries": {"/fonts/A.ttf": {"size": 1, "mtime_ns": 1, "hash": "h"}},
            }
        ),
        encoding="utf-8",
    )

    cache = HashCache.load(path)
    assert cache.get(Path("/fonts/A.ttf"), size=1, mtime_ns=1) is None


def test_scan_fonts_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Au 2e scan d'un fichier inchangé, `hash_file` n'est pas rappelé."""
    font_path = tmp_path / "Inter.ttf"
    font_path.write_bytes(b"fake ttf bytes")
    discovered = [DiscoveredFont(path=font_path, filename="Inter.ttf")]
    cache = HashCache(_cache_path(tmp_path))

    real_hash = hash_file(font_path)
    calls = {"n": 0}
    original = hashing.hash_file

    def counting_hash(path: Path) -> str:
        calls["n"] += 1
        return original(path)

    monkeypatch.setattr(hashing, "hash_file", counting_hash)

    first = scan_fonts(discovered, cache=cache)
    second = scan_fonts(discovered, cache=cache)

    assert calls["n"] == 1  # haché une seule fois malgré deux scans
    assert first[0].file_hash == real_hash
    assert second[0].file_hash == real_hash


def test_scan_fonts_rehashes_on_change(tmp_path: Path) -> None:
    """Modifier le contenu (taille différente) invalide l'entrée de cache."""
    font_path = tmp_path / "Inter.ttf"
    font_path.write_bytes(b"version one")
    discovered = [DiscoveredFont(path=font_path, filename="Inter.ttf")]
    cache = HashCache(_cache_path(tmp_path))

    h1 = scan_fonts(discovered, cache=cache)[0].file_hash

    font_path.write_bytes(b"version two is longer")
    h2 = scan_fonts(discovered, cache=cache)[0].file_hash

    assert h1 != h2
