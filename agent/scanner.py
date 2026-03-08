"""Scan de fonts : hashing SHA-256, file watcher (watchdog), scan périodique."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent.discovery import FONT_EXTENSIONS, DiscoveredFont

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


# ---------------------------------------------------------------------------
# File watcher (watchdog)
# ---------------------------------------------------------------------------


class _FontEventHandler(FileSystemEventHandler):
    """Gère les événements watchdog pour les fichiers font."""

    def __init__(
        self,
        queue: asyncio.Queue[Path],
        loop: asyncio.AbstractEventLoop,
        ignore_patterns: list[str],
    ) -> None:
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._ignore_patterns = ignore_patterns

    def _is_font_file(self, path: Path) -> bool:
        """Vérifie si le fichier est une font valide (extension + patterns)."""
        if path.suffix.lower() not in FONT_EXTENSIONS:
            return False
        if any(fnmatch.fnmatch(path.name, pat) for pat in self._ignore_patterns):
            return False
        # Ignorer les fichiers temporaires macOS
        if path.name.startswith(".") or path.name.startswith("._"):
            return False
        return True

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._is_font_file(path):
            logger.info("Watcher : nouveau fichier détecté → %s", path.name)
            self._loop.call_soon_threadsafe(self._queue.put_nowait, path)


class WatcherService:
    """Surveille les dossiers de fonts en continu via watchdog.

    Les nouveaux fichiers sont placés dans une asyncio.Queue pour traitement
    par la boucle principale.
    """

    def __init__(
        self,
        directories: list[str],
        ignore_patterns: list[str],
        queue: asyncio.Queue[Path],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._directories = directories
        self._observer = Observer()
        self._handler = _FontEventHandler(queue, loop, ignore_patterns)

    def start(self) -> None:
        """Démarre la surveillance des dossiers."""
        for dir_str in self._directories:
            dir_path = Path(dir_str).expanduser()
            if not dir_path.exists():
                logger.warning("Watcher : dossier inexistant, ignoré : %s", dir_path)
                continue
            self._observer.schedule(self._handler, str(dir_path), recursive=True)
            logger.info("Watcher : surveillance de %s", dir_path)

        self._observer.start()
        logger.info("Watcher démarré")

    def stop(self) -> None:
        """Arrête la surveillance."""
        self._observer.stop()
        self._observer.join(timeout=5)
        logger.info("Watcher arrêté")


async def run_periodic_scan(
    directories: list[str],
    ignore_patterns: list[str],
    known_hashes: set[str],
    interval_minutes: int,
    on_new_font: Callable[[ScannedFont], None],
) -> None:
    """Scan périodique en backup du file watcher.

    Compare l'état actuel avec les hashes connus et signale les nouvelles fonts.
    """
    from agent.discovery import discover_via_directories

    while True:
        await asyncio.sleep(interval_minutes * 60)
        logger.info("Scan périodique en cours...")
        t0 = time.monotonic()

        discovered = discover_via_directories(directories, ignore_patterns)
        new_count = 0

        for font in discovered:
            try:
                file_hash = hash_file(font.path)
                if file_hash not in known_hashes:
                    file_size = font.path.stat().st_size
                    scanned = ScannedFont(
                        path=font.path,
                        filename=font.filename,
                        file_hash=file_hash,
                        file_size=file_size,
                    )
                    known_hashes.add(file_hash)
                    on_new_font(scanned)
                    new_count += 1
            except OSError:
                logger.warning("Scan périodique : impossible de lire %s", font.path)
            except Exception:
                logger.exception("Scan périodique : erreur sur %s", font.path)

        elapsed = time.monotonic() - t0
        logger.info(
            "Scan périodique terminé en %.1fs — %d nouvelles fonts détectées",
            elapsed,
            new_count,
        )
