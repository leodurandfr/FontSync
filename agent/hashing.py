"""Hachage SHA-256 des fichiers de polices.

Isolé du file watcher (`scanner.py`) pour rester importable sans `watchdog` :
la commande `sync` stateless n'a besoin que du hachage, pas de la surveillance
continue (remplacée par launchd `WatchPaths`).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent.discovery import DiscoveredFont

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 64 Ko


@dataclass
class ScannedFont:
    """Font scannée avec son hash SHA-256."""

    path: Path
    filename: str
    file_hash: str
    file_size: int


def hash_file(path: Path) -> str:
    """Calcule le SHA-256 d'un fichier."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            sha256.update(chunk)
    return sha256.hexdigest()


def scan_fonts(
    discovered: list[DiscoveredFont],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ScannedFont]:
    """Hash chaque font découverte et retourne la liste des fonts scannées.

    Une font illisible est ignorée (jamais bloquante).

    Args:
        discovered: liste de fonts découvertes
        on_progress: callback(current, total) pour la progression
    """
    scanned: list[ScannedFont] = []
    total = len(discovered)

    for i, font in enumerate(discovered):
        try:
            file_hash = hash_file(font.path)
            file_size = font.path.stat().st_size
            scanned.append(
                ScannedFont(
                    path=font.path,
                    filename=font.filename,
                    file_hash=file_hash,
                    file_size=file_size,
                )
            )
        except OSError:
            logger.warning("Impossible de lire %s, ignoré", font.path)
        except Exception:
            logger.exception("Erreur lors du hash de %s", font.path)

        if on_progress:
            on_progress(i + 1, total)

    return scanned
