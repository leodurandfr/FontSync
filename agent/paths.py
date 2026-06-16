"""Résolution centralisée des chemins de l'agent, surchargeables par variables
d'environnement.

But : pouvoir simuler **plusieurs machines sur un seul Mac** en développement
(cf. `scripts/dev/`) sans toucher au vrai `~/.fontsync` ni au vrai
`~/Library/Fonts`. Chaque « device » simulé tourne dans son propre état isolé.

Variables (toutes optionnelles ; non définies → comportement de production) :

- ``FONTSYNC_HOME``      : dossier d'état de l'agent — `config.yaml`,
  `hash_cache.json`, `disabled/`. Défaut : ``~/.fontsync``.
- ``FONTSYNC_FONTS_DIR`` : dossier d'installation des fonts. Défaut :
  ``~/Library/Fonts``.

Ces helpers sont lus à l'import des modules qui les consomment ; en pratique le
script de dev exporte les variables **avant** de lancer ``python -m agent``.
"""

from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    """Dossier d'état de l'agent (équivalent de ``~/.fontsync``)."""
    override = os.environ.get("FONTSYNC_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".fontsync"


def fonts_dir() -> Path:
    """Dossier d'installation des fonts (équivalent de ``~/Library/Fonts``)."""
    override = os.environ.get("FONTSYNC_FONTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Fonts"
