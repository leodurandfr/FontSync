"""Découverte des fonts installées sur macOS.

**Union de deux sources**, pas un mode avec repli : Core Text (pyobjc) *et* le
scan direct des dossiers configurés.

L'union n'est pas un excès de prudence, c'est une nécessité depuis que l'absence
d'une police vaut suppression. Core Text ne voit que ce que macOS a **indexé** ;
or l'index se fige (macOS 14+, cf. `agent.font_registry`) et un fichier bien
présent sur le disque devient alors invisible de Core Text. Tant que la
découverte ne servait qu'à *ajouter*, une police manquée était simplement
re-téléchargée. Maintenant que le serveur en déduit « cette machine ne l'a
plus », la manquer la ferait supprimer partout. Ce que la machine possède se
mesure donc sur le disque, et Core Text n'apporte que ce qu'il voit en plus
(polices indexées hors des dossiers scannés).

Les motifs d'exclusion s'appliquent aux deux sources : ce qu'on ignore doit être
ignoré quelle que soit la source qui l'a trouvé, sinon la liste déclarée dépend
de l'état de l'index.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".ttc"}


@dataclass
class DiscoveredFont:
    """Font découverte sur le système."""

    path: Path
    filename: str
    # Ce détenteur peut-il alimenter la bibliothèque synchronisée ? Défaut
    # `True` — la direction sûre (cf. PLAN-ETATS-FONTS.md §4.3) : un appelant
    # qui ne calcule pas le drapeau (tests, `disabled/`) ne bloque rien à tort.
    ingestible: bool = True


def _is_ingestible(path: Path, ingest_directories: list[str] | None) -> bool:
    """Le chemin **résolu** est-il sous un des `ingest_directories` ?

    Comparaison par `Path.is_relative_to` sur des chemins résolus, jamais un
    préfixe de chaîne : `~/Library/Fonts` doit valoir `/Users/leo/Library/Fonts`,
    pas matcher `~/Library/FontsBackup` par accident de préfixe.
    """
    if ingest_directories is None:
        return True
    resolved = path.resolve()
    for d in ingest_directories:
        try:
            if resolved.is_relative_to(Path(d).expanduser().resolve()):
                return True
        except OSError:
            continue
    return False


def discover_via_core_text(
    ingest_directories: list[str] | None = None,
) -> list[DiscoveredFont]:
    """Découvre les fonts via Core Text (pyobjc).

    Retourne uniquement les fonts dans ~/Library/Fonts et /Library/Fonts
    (on exclut /System/Library/Fonts qui contient les fonts OS).

    `ingest_directories` : cf. `_is_ingestible`. `/Library/Fonts` est codé en
    dur dans `allowed_prefixes` ci-dessous, hors de toute configuration — une
    police que Core Text réinjecte depuis ce dossier (index macOS retrouvant
    un fichier que le scan disque a manqué) doit rester non ingestible comme
    si le scan l'avait trouvée directement.
    """
    try:
        import CoreText  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "pyobjc-framework-CoreText non disponible, fallback sur scan dossiers"
        )
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
                fonts.append(
                    DiscoveredFont(
                        path=path,
                        filename=path.name,
                        ingestible=_is_ingestible(path, ingest_directories),
                    )
                )

        logger.info("Core Text : %d fonts découvertes", len(fonts))
        return fonts

    except Exception:
        logger.exception("Erreur lors de la découverte Core Text")
        return []


def discover_via_directories(
    directories: list[str],
    ignore_patterns: list[str] | None = None,
    ingest_directories: list[str] | None = None,
) -> list[DiscoveredFont]:
    """Scan direct des dossiers de fonts (fallback).

    Parcourt récursivement les dossiers et collecte les fichiers font.

    `ingest_directories` : cf. `_is_ingestible`. `None` (le défaut) vaut
    « tout est ingestible » — c'est le cas de l'appel sur `disabled/`, qui
    force le drapeau à `True` lui-même (cf. `sync_command.py`).
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

            fonts.append(
                DiscoveredFont(
                    path=file_path,
                    filename=file_path.name,
                    ingestible=_is_ingestible(file_path, ingest_directories),
                )
            )

    logger.info("Scan dossiers : %d fonts découvertes", len(fonts))
    return fonts


def _matches_ignore(filename: str, ignore_patterns: list[str] | None) -> bool:
    return any(fnmatch.fnmatch(filename, pat) for pat in ignore_patterns or [])


def discover_fonts(
    directories: list[str],
    ignore_patterns: list[str] | None = None,
    ingest_directories: list[str] | None = None,
) -> list[DiscoveredFont]:
    """Découvre toutes les fonts de cette machine : disque **union** Core Text.

    Le scan de dossiers fait autorité sur « le fichier existe » ; Core Text
    n'ajoute que les polices indexées hors des dossiers scannés. Voir l'en-tête
    de module : depuis que l'absence vaut suppression, se fier au seul index de
    macOS ferait effacer partout ce que cet index a momentanément perdu.

    `ingest_directories` : cf. `_is_ingestible` — posé sur les deux sources, la
    découverte elle-même reste **inchangée** (§4.2 PLAN-ETATS-FONTS.md) : ce
    qui change, c'est la candidature au push, jamais ce qui est déclaré.

    En développement, ``FONTSYNC_DISCOVERY=directories`` court-circuite Core
    Text (qui renverrait toujours le vrai ``~/Library/Fonts``) : indispensable
    pour simuler une machine au jeu de fonts isolé. Neutre en production.
    """
    on_disk = discover_via_directories(directories, ignore_patterns, ingest_directories)
    if os.environ.get("FONTSYNC_DISCOVERY") == "directories":
        return on_disk

    seen = {str(f.path.resolve()) for f in on_disk}
    extra = 0
    for font in discover_via_core_text(ingest_directories):
        if _matches_ignore(font.filename, ignore_patterns):
            continue
        try:
            resolved = str(font.path.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        on_disk.append(font)
        extra += 1

    if extra:
        logger.info("Core Text : %d font(s) hors des dossiers scannés", extra)
    return on_disk
