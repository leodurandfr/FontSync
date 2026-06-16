"""Tests du hachage SHA-256 de l'agent (B11).

Complètent `test_hash_cache.py` (qui couvre le chemin *avec* cache) en vérifiant
`hash_file` directement et `scan_fonts` *sans* cache : exactitude du hash,
hachage par chunks d'un gros fichier, robustesse (une font illisible est ignorée,
jamais bloquante), et le callback de progression.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agent.discovery import DiscoveredFont
from agent.hashing import hash_file, scan_fonts


def test_hash_file_matches_hashlib(tmp_path: Path) -> None:
    data = b"the quick brown fox"
    p = tmp_path / "A.ttf"
    p.write_bytes(data)

    assert hash_file(p) == hashlib.sha256(data).hexdigest()


def test_hash_file_handles_large_multichunk_file(tmp_path: Path) -> None:
    # > CHUNK_SIZE (64 Ko) pour exercer la boucle de lecture par morceaux.
    data = b"x" * (65536 * 3 + 7)
    p = tmp_path / "Big.ttf"
    p.write_bytes(data)

    assert hash_file(p) == hashlib.sha256(data).hexdigest()


def test_scan_fonts_without_cache_hashes_all(tmp_path: Path) -> None:
    a = tmp_path / "A.ttf"
    b = tmp_path / "B.ttf"
    a.write_bytes(b"alpha")
    b.write_bytes(b"beta-longer")
    discovered = [
        DiscoveredFont(path=a, filename="A.ttf"),
        DiscoveredFont(path=b, filename="B.ttf"),
    ]

    scanned = scan_fonts(discovered)

    assert {s.filename for s in scanned} == {"A.ttf", "B.ttf"}
    by_name = {s.filename: s for s in scanned}
    assert by_name["A.ttf"].file_hash == hashlib.sha256(b"alpha").hexdigest()
    assert by_name["A.ttf"].file_size == len(b"alpha")
    assert by_name["B.ttf"].file_size == len(b"beta-longer")


def test_scan_fonts_skips_unreadable_font(tmp_path: Path) -> None:
    """Une font dont le fichier n'existe pas est ignorée, sans interrompre le scan."""
    ok = tmp_path / "OK.ttf"
    ok.write_bytes(b"good")
    missing = tmp_path / "ghost.ttf"  # jamais créé → stat() lève OSError
    discovered = [
        DiscoveredFont(path=missing, filename="ghost.ttf"),
        DiscoveredFont(path=ok, filename="OK.ttf"),
    ]

    scanned = scan_fonts(discovered)

    assert [s.filename for s in scanned] == ["OK.ttf"]


def test_scan_fonts_reports_progress(tmp_path: Path) -> None:
    paths = []
    for i in range(3):
        p = tmp_path / f"F{i}.ttf"
        p.write_bytes(f"font-{i}".encode())
        paths.append(DiscoveredFont(path=p, filename=p.name))

    seen: list[tuple[int, int]] = []
    scan_fonts(paths, on_progress=lambda cur, total: seen.append((cur, total)))

    # Un appel par font découverte, même rang/total, y compris l'avancement final.
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_scan_fonts_empty_input() -> None:
    assert scan_fonts([]) == []
