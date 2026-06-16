"""Cache de hash local de l'agent (B2).

Évite de re-hacher les fonts inchangées d'un `sync` à l'autre : un scan de
plusieurs centaines de fonts devient quasi gratuit après la première fois.

Clé de validité `(path, size, mtime_ns)` : si les trois concordent avec
l'entrée persistée, le SHA-256 mémorisé est réutilisé ; sinon le fichier est
re-haché. `mtime_ns` (entier nanoseconde) évite les pièges de comparaison de
flottants après un aller-retour JSON.

Le cache est purement reconstructible (une absence ou une corruption → on
re-hache) : il n'introduit donc aucun état de synchronisation mutable. Il est
chargé au début d'un `sync`, mis à jour pendant le scan, puis réécrit en fin de
scan, **élagué des chemins disparus du disque**.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = Path.home() / ".fontsync" / "hash_cache.json"

_VERSION = 1


@dataclass
class _Entry:
    size: int
    mtime_ns: int
    file_hash: str


class HashCache:
    """Cache `(path, size, mtime_ns) → hash SHA-256`, persisté en JSON.

    Contrat d'usage : appeler `get()`/`put()` pour chaque font scannée, puis
    `save()` **une fois le scan terminé**. `save()` élague toute entrée dont le
    chemin n'a pas été vu pendant le run (font supprimée ou déplacée), donc
    appeler `save()` sans avoir scanné viderait le cache.
    """

    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self._path = path
        self._entries: dict[str, _Entry] = {}
        self._seen: set[str] = set()  # chemins vus dans ce run (pour l'élagage)

    @classmethod
    def load(cls, path: Path = DEFAULT_CACHE_PATH) -> HashCache:
        """Charge le cache depuis `path`. Fichier absent ou corrompu → cache vide."""
        cache = cls(path)
        try:
            with open(path) as f:
                raw = json.load(f)
        except FileNotFoundError:
            return cache
        except (OSError, ValueError):
            logger.warning("Cache de hash illisible (%s), réinitialisé", path)
            return cache

        if not isinstance(raw, dict) or raw.get("version") != _VERSION:
            return cache

        entries = raw.get("entries")
        if not isinstance(entries, dict):
            return cache

        for key, val in entries.items():
            try:
                cache._entries[str(key)] = _Entry(
                    size=int(val["size"]),
                    mtime_ns=int(val["mtime_ns"]),
                    file_hash=str(val["hash"]),
                )
            except (KeyError, TypeError, ValueError):
                continue  # entrée corrompue ignorée, jamais bloquante
        return cache

    def get(self, path: Path, size: int, mtime_ns: int) -> str | None:
        """Retourne le hash mémorisé si `(size, mtime_ns)` concordent, sinon None.

        Marque le chemin comme vu : il survivra à l'élagage de `save()`.
        """
        key = str(path)
        self._seen.add(key)
        entry = self._entries.get(key)
        if entry is not None and entry.size == size and entry.mtime_ns == mtime_ns:
            return entry.file_hash
        return None

    def put(self, path: Path, size: int, mtime_ns: int, file_hash: str) -> None:
        """Mémorise (ou met à jour) le hash d'un fichier."""
        key = str(path)
        self._seen.add(key)
        self._entries[key] = _Entry(size=size, mtime_ns=mtime_ns, file_hash=file_hash)

    def save(self) -> None:
        """Persiste le cache (écriture atomique), élagué des chemins non vus."""
        self._entries = {k: v for k, v in self._entries.items() if k in self._seen}
        data = {
            "version": _VERSION,
            "entries": {
                k: {"size": v.size, "mtime_ns": v.mtime_ns, "hash": v.file_hash}
                for k, v in self._entries.items()
            },
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._path)
        except OSError:
            logger.warning("Impossible d'écrire le cache de hash (%s)", self._path)
