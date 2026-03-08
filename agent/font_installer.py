"""Installation de fonts per-user sur macOS.

Copie les fichiers dans ~/Library/Fonts/ (pas de droits admin nécessaires).
Seuls les formats installables (TTF, OTF, TTC) sont acceptés.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

INSTALL_DIR = Path.home() / "Library" / "Fonts"
INSTALLABLE_FORMATS = {".ttf", ".otf", ".ttc"}


def install_font(filename: str, data: bytes) -> Path | None:
    """Installe une font dans ~/Library/Fonts/.

    Args:
        filename: nom du fichier (ex: "Inter-Regular.ttf")
        data: contenu binaire du fichier

    Returns:
        Le path d'installation, ou None si le format n'est pas installable.
    """
    ext = Path(filename).suffix.lower()
    if ext not in INSTALLABLE_FORMATS:
        logger.warning("Format %s non installable, ignoré : %s", ext, filename)
        return None

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dest = INSTALL_DIR / filename

    if dest.exists():
        logger.info("Font déjà présente, écrasement : %s", dest)

    dest.write_bytes(data)
    logger.info("Font installée : %s", dest)
    return dest
