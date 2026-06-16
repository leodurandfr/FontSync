"""Ré-exports des primitives de hachage de l'agent.

Les primitives (`ScannedFont`, `hash_file`, `scan_fonts`) vivent dans
`agent.hashing` ; elles sont ré-exportées ici pour les consommateurs
existants. Le file watcher (watchdog) et le scan périodique persistant ont
été retirés : l'agent est désormais stateless (commande `sync` déclenchée par
launchd, cf. PLAN.md).
"""

from __future__ import annotations

from agent.hashing import CHUNK_SIZE, ScannedFont, hash_file, scan_fonts

__all__ = [
    "CHUNK_SIZE",
    "ScannedFont",
    "hash_file",
    "scan_fonts",
]
