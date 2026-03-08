"""Découverte des fonts installées sur macOS.

Mode principal : Core Text via pyobjc.
Fallback : scan direct des dossiers ~/Library/Fonts et /Library/Fonts.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".ttc"}


@dataclass
class DiscoveredFont:
    """Font découverte sur le système."""

    path: Path
    filename: str


def discover_via_core_text() -> list[DiscoveredFont]:
    """Découvre les fonts via Core Text (pyobjc).

    Retourne uniquement les fonts dans ~/Library/Fonts et /Library/Fonts
    (on exclut /System/Library/Fonts qui contient les fonts OS).
    """
    try:
        import CoreText  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pyobjc-framework-CoreText non disponible, fallback sur scan dossiers")
        return []

    try:
        descriptors = CoreText.CTFontCollectionCreateFromAvailableFonts(None)
        font_descs = CoreText.CTFontCollectionCreateMatchingFontDescriptors(descriptors)

        if font_descs is None:
            logger.warning("Core Text n'a retourné aucun descripteur")
            return []

        fonts: list[DiscoveredFont] = []
        allowed_prefixes = (
            str(Path.home() / "Library" / "Fonts"),
            "/Library/Fonts",
        )

        for desc in font_descs:
            url = CoreText.CTFontDescriptorCopyAttribute(
                desc, CoreText.kCTFontURLAttribute
            )
            if url is None:
                continue

            path_str = str(url.path())
            if not path_str:
                continue

            # Filtrer : uniquement les dossiers user et partagé
            if not any(path_str.startswith(prefix) for prefix in allowed_prefixes):
                continue

            path = Path(path_str)
            if path.suffix.lower() in FONT_EXTENSIONS and path.is_file():
                fonts.append(DiscoveredFont(path=path, filename=path.name))

        logger.info("Core Text : %d fonts découvertes", len(fonts))
        return fonts

    except Exception:
        logger.exception("Erreur lors de la découverte Core Text")
        return []


def discover_via_directories(
    directories: list[str],
    ignore_patterns: list[str] | None = None,
) -> list[DiscoveredFont]:
    """Scan direct des dossiers de fonts (fallback).

    Parcourt récursivement les dossiers et collecte les fichiers font.
    """
    ignore = ignore_patterns or []
    fonts: list[DiscoveredFont] = []
    seen_paths: set[str] = set()

    for dir_str in directories:
        dir_path = Path(dir_str).expanduser()
        if not dir_path.exists():
            logger.debug("Dossier inexistant, ignoré : %s", dir_path)
            continue

        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in FONT_EXTENSIONS:
                continue

            # Vérifier les patterns d'exclusion
            if any(fnmatch.fnmatch(file_path.name, pat) for pat in ignore):
                continue

            resolved = str(file_path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            fonts.append(DiscoveredFont(path=file_path, filename=file_path.name))

    logger.info("Scan dossiers : %d fonts découvertes", len(fonts))
    return fonts


def discover_fonts(
    directories: list[str],
    ignore_patterns: list[str] | None = None,
) -> list[DiscoveredFont]:
    """Découvre toutes les fonts installées.

    Tente Core Text d'abord, fallback sur scan dossiers.
    """
    fonts = discover_via_core_text()
    if fonts:
        return fonts

    return discover_via_directories(directories, ignore_patterns)
