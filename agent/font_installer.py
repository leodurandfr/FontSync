"""Installation et activation de fonts per-user sur macOS.

Copie les fichiers dans ~/Library/Fonts/ (pas de droits admin nécessaires).
Seuls les formats installables (TTF, OTF, TTC) sont acceptés.

Activation/désactivation : déplace les fonts entre ~/Library/Fonts (actif)
et ~/.fontsync/disabled/ (inactif). Le fichier reste toujours sur le disque.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

INSTALL_DIR = Path.home() / "Library" / "Fonts"
DISABLED_DIR = Path.home() / ".fontsync" / "disabled"
INSTALLABLE_FORMATS = {".ttf", ".otf", ".ttc"}


def install_font(filename: str, data: bytes) -> Path | None:
    """Installe une font dans ~/Library/Fonts/.

    Args:
        filename: nom du fichier (ex: "Inter-Regular.ttf")
        data: contenu binaire du fichier

    Returns:
        Le path d'installation, ou None si le format n'est pas installable.
    """
    safe_name = Path(filename).name  # Strip directory components
    ext = Path(safe_name).suffix.lower()
    if ext not in INSTALLABLE_FORMATS:
        logger.warning("Format %s non installable, ignoré : %s", ext, safe_name)
        return None

    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dest = INSTALL_DIR / safe_name

    # Sécurité : ne jamais écrire hors de ~/Library/Fonts
    try:
        dest.resolve().relative_to(INSTALL_DIR.resolve())
    except ValueError:
        logger.error("Tentative d'installation hors de ~/Library/Fonts : %s", dest)
        return None

    if dest.exists():
        logger.info("Font déjà présente, écrasement : %s", dest)

    dest.write_bytes(data)
    logger.info("Font installée : %s", dest)
    return dest


def uninstall_font(filename: str) -> bool:
    """Désinstalle une font de ~/Library/Fonts/ et du dossier disabled.

    Supprime le fichier partout. Ne touche jamais /Library/Fonts
    ni /System/Library/Fonts.

    Args:
        filename: nom du fichier (ex: "Inter-Regular.ttf")

    Returns:
        True si le fichier a été supprimé, False sinon.
    """
    safe_name = Path(filename).name  # Strip directory components
    removed = False

    # Supprimer de ~/Library/Fonts
    dest = INSTALL_DIR / safe_name
    try:
        dest.resolve().relative_to(INSTALL_DIR.resolve())
    except ValueError:
        logger.error("Tentative de suppression hors de ~/Library/Fonts : %s", dest)
        return False

    if dest.exists():
        dest.unlink()
        removed = True

    # Supprimer aussi du dossier disabled si présent
    disabled = DISABLED_DIR / safe_name
    try:
        disabled.resolve().relative_to(DISABLED_DIR.resolve())
    except ValueError:
        logger.error("Tentative de suppression hors de ~/.fontsync/disabled : %s", disabled)
    else:
        if disabled.exists():
            disabled.unlink()
            removed = True

    if removed:
        logger.info("Font désinstallée : %s", safe_name)
    else:
        logger.warning("Font introuvable pour désinstallation : %s", safe_name)
    return removed


def activate_font(local_path: str) -> bool:
    """Active une font en la déplaçant de ~/.fontsync/disabled/ vers ~/Library/Fonts/.

    Args:
        local_path: chemin du fichier (absolu ou nom de fichier)

    Returns:
        True si la font a été activée, False sinon.
    """
    safe_name = Path(local_path).name
    source = DISABLED_DIR / safe_name
    dest = INSTALL_DIR / safe_name

    # Si déjà dans ~/Library/Fonts, elle est déjà active
    if dest.exists():
        logger.info("Font déjà active : %s", dest)
        return True

    if not source.exists():
        logger.warning(
            "Font introuvable dans le dossier disabled pour activation : %s",
            source,
        )
        return False

    # Sécurité : vérifier que la destination reste dans ~/Library/Fonts
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        dest.resolve().relative_to(INSTALL_DIR.resolve())
    except ValueError:
        logger.error("Tentative d'activation hors de ~/Library/Fonts : %s", dest)
        return False

    shutil.move(str(source), str(dest))
    logger.info("Font activée : %s → %s", source, dest)
    return True


def deactivate_font(local_path: str) -> bool:
    """Désactive une font en la déplaçant de ~/Library/Fonts/ vers ~/.fontsync/disabled/.

    Le fichier reste sur le disque mais n'est plus visible par les applications.

    Args:
        local_path: chemin du fichier (absolu ou nom de fichier)

    Returns:
        True si la font a été désactivée, False sinon.
    """
    safe_name = Path(local_path).name
    source = INSTALL_DIR / safe_name
    dest = DISABLED_DIR / safe_name

    # Si la source existe dans ~/Library/Fonts → la déplacer
    if source.exists():
        # Sécurité : ne déplacer que depuis ~/Library/Fonts
        try:
            source.resolve().relative_to(INSTALL_DIR.resolve())
        except ValueError:
            logger.error("Tentative de désactivation hors de ~/Library/Fonts : %s", source)
            return False

        DISABLED_DIR.mkdir(parents=True, exist_ok=True)
        # Écraser le fichier dans disabled s'il existe déjà (résidu)
        if dest.exists():
            dest.unlink()
        shutil.move(str(source), str(dest))
        logger.info("Font désactivée : %s → %s", source, dest)
        return True

    # Source absente de ~/Library/Fonts — vérifier si déjà dans disabled
    if dest.exists():
        logger.info("Font déjà désactivée : %s", dest)
        return True

    logger.warning(
        "Font introuvable pour désactivation : ni dans %s ni dans %s",
        source, dest,
    )
    return False
