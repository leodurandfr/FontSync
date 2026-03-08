"""Service d'analyse de fonts avec fonttools.

Extrait les métadonnées d'un fichier font (TTF, OTF, WOFF, WOFF2)
de manière robuste : ne lève jamais d'exception, retourne un dict
partiel si le parsing échoue sur certaines tables.
"""

import logging
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

# Mapping des codepoints Unicode vers les scripts supportés
_SCRIPT_RANGES: list[tuple[str, list[tuple[int, int]]]] = [
    ("latin", [(0x0000, 0x024F), (0x1E00, 0x1EFF), (0x2C60, 0x2C7F)]),
    ("cyrillic", [(0x0400, 0x04FF), (0x0500, 0x052F), (0x2DE0, 0x2DFF)]),
    ("greek", [(0x0370, 0x03FF), (0x1F00, 0x1FFF)]),
    ("arabic", [(0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]),
    ("hebrew", [(0x0590, 0x05FF), (0xFB1D, 0xFB4F)]),
    ("devanagari", [(0x0900, 0x097F), (0xA8E0, 0xA8FF)]),
    ("thai", [(0x0E00, 0x0E7F)]),
    ("cjk", [
        (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x2E80, 0x2EFF),
        (0x3000, 0x303F), (0x31F0, 0x31FF), (0xF900, 0xFAFF),
    ]),
    ("hangul", [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)]),
    ("kana", [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x31F0, 0x31FF)]),
    ("georgian", [(0x10A0, 0x10FF), (0x2D00, 0x2D2F)]),
    ("armenian", [(0x0530, 0x058F)]),
    ("ethiopic", [(0x1200, 0x137F)]),
    ("tamil", [(0x0B80, 0x0BFF)]),
    ("bengali", [(0x0980, 0x09FF)]),
    ("gujarati", [(0x0A80, 0x0AFF)]),
    ("telugu", [(0x0C00, 0x0C7F)]),
    ("kannada", [(0x0C80, 0x0CFF)]),
    ("malayalam", [(0x0D00, 0x0D7F)]),
    ("myanmar", [(0x1000, 0x109F)]),
    ("tibetan", [(0x0F00, 0x0FFF)]),
    ("sinhala", [(0x0D80, 0x0DFF)]),
    ("lao", [(0x0E80, 0x0EFF)]),
    ("khmer", [(0x1780, 0x17FF)]),
]

# Seuil minimum de codepoints pour considérer un script comme supporté
_SCRIPT_MIN_CODEPOINTS = 10


def _extract_name(name_table: Any, name_id: int) -> str | None:
    """Extrait une entrée de la table name par son ID."""
    record = name_table.getName(name_id, 3, 1, 0x0409)  # Windows, Unicode BMP, English
    if record is None:
        record = name_table.getName(name_id, 1, 0, 0)  # Mac, Roman, English
    if record is None:
        # Fallback : prendre n'importe quel enregistrement avec ce nameID
        for r in name_table.names:
            if r.nameID == name_id:
                record = r
                break
    if record is None:
        return None
    try:
        return str(record).strip()
    except Exception:
        return None


def _extract_name_table(font: TTFont) -> dict[str, Any]:
    """Extrait les métadonnées de la table 'name'."""
    result: dict[str, Any] = {}
    try:
        name_table = font["name"]
    except KeyError:
        return result

    # nameID 16 (Typographic Family) avec fallback sur nameID 1 (Family)
    family = _extract_name(name_table, 16) or _extract_name(name_table, 1)
    if family:
        result["family_name"] = family

    # nameID 17 (Typographic Subfamily) avec fallback sur nameID 2
    subfamily = _extract_name(name_table, 17) or _extract_name(name_table, 2)
    if subfamily:
        result["subfamily_name"] = subfamily

    mapping = {
        4: "full_name",
        6: "postscript_name",
        5: "version",
        9: "designer",
        8: "manufacturer",
        13: "license",
        14: "license_url",
        10: "description",
    }
    for name_id, key in mapping.items():
        value = _extract_name(name_table, name_id)
        if value:
            result[key] = value

    return result


def _extract_os2(font: TTFont) -> dict[str, Any]:
    """Extrait les métadonnées de la table 'OS/2'."""
    result: dict[str, Any] = {}
    try:
        os2 = font["OS/2"]
    except KeyError:
        return result

    if hasattr(os2, "usWeightClass"):
        result["weight_class"] = os2.usWeightClass
    if hasattr(os2, "usWidthClass"):
        result["width_class"] = os2.usWidthClass

    # Italic et oblique depuis fsSelection
    if hasattr(os2, "fsSelection"):
        fs = os2.fsSelection
        result["is_italic"] = bool(fs & (1 << 0))  # bit 0 = ITALIC
        result["is_oblique"] = bool(fs & (1 << 9))  # bit 9 = OBLIQUE

    # Panose
    if hasattr(os2, "panose"):
        panose = os2.panose
        try:
            panose_values = [
                panose.bFamilyType, panose.bSerifStyle, panose.bWeight,
                panose.bProportion, panose.bContrast, panose.bStrokeVariation,
                panose.bArmStyle, panose.bLetterForm, panose.bMidline,
                panose.bXHeight,
            ]
            result["panose"] = " ".join(str(v) for v in panose_values)
        except Exception:
            pass

    return result


def _extract_cmap_codepoints(font: TTFont) -> set[int]:
    """Extrait tous les codepoints de la table cmap."""
    codepoints: set[int] = set()
    try:
        cmap = font["cmap"]
        for table in cmap.tables:
            if table.isUnicode():
                codepoints.update(table.cmap.keys())
    except (KeyError, AttributeError):
        pass
    return codepoints


def _detect_scripts(codepoints: set[int]) -> list[str]:
    """Détecte les scripts supportés à partir des codepoints."""
    scripts: list[str] = []
    for script_name, ranges in _SCRIPT_RANGES:
        count = 0
        for start, end in ranges:
            count += sum(1 for cp in codepoints if start <= cp <= end)
        if count >= _SCRIPT_MIN_CODEPOINTS:
            scripts.append(script_name)
    return sorted(scripts)


def _classify_font(metadata: dict[str, Any], font: TTFont) -> str | None:
    """Classification heuristique : serif, sans-serif, monospace, display, handwriting, symbol.

    Utilise dans l'ordre : isFixedPitch (post), Panose, puis le nom de famille.
    """
    # 1. Monospace via table post
    try:
        post = font["post"]
        if post.isFixedPitch:
            return "monospace"
    except (KeyError, AttributeError):
        pass

    # 2. Panose-based classification
    panose_str = metadata.get("panose", "")
    if panose_str:
        parts = panose_str.split()
        if len(parts) >= 1:
            family_type = int(parts[0])
            if family_type == 2 and len(parts) >= 2:
                # Latin Text - check serif style
                serif_style = int(parts[1])
                if serif_style >= 11:  # 11-15 = sans-serif variants
                    return "sans-serif"
                elif 2 <= serif_style <= 10:
                    return "serif"
            elif family_type == 3:
                return "handwriting"
            elif family_type == 4:
                return "display"
            elif family_type == 5:
                return "symbol"

    # 3. Fallback : heuristique sur le nom
    name_lower = (
        metadata.get("family_name", "") or ""
    ).lower() + " " + (
        metadata.get("full_name", "") or ""
    ).lower()

    if any(kw in name_lower for kw in ("mono", "code", "console", "terminal", "fixed")):
        return "monospace"
    if any(kw in name_lower for kw in ("sans", "gothic", "grotesk", "grotesque", "helvetic")):
        return "sans-serif"
    if any(kw in name_lower for kw in ("serif", "roman", "garamond", "times", "georgia")):
        return "serif"
    if any(kw in name_lower for kw in ("hand", "script", "brush", "cursive", "callig")):
        return "handwriting"
    if any(kw in name_lower for kw in ("display", "poster", "decorat", "ornament")):
        return "display"
    if any(kw in name_lower for kw in ("symbol", "icon", "emoji", "ding", "wing")):
        return "symbol"

    return None


def _extract_glyph_count(font: TTFont) -> int | None:
    """Extrait le nombre de glyphes depuis la table maxp."""
    try:
        return font["maxp"].numGlyphs
    except (KeyError, AttributeError):
        return None


def _extract_variable_info(font: TTFont) -> dict[str, Any]:
    """Extrait les informations de font variable (table fvar)."""
    result: dict[str, Any] = {"is_variable": False}
    try:
        fvar = font["fvar"]
    except KeyError:
        return result

    result["is_variable"] = True
    axes = []
    for axis in fvar.axes:
        axes.append({
            "tag": axis.axisTag,
            "min": axis.minValue,
            "max": axis.maxValue,
            "default": axis.defaultValue,
        })
    result["variable_axes"] = axes
    return result


def analyze(file_path: str | Path) -> dict[str, Any]:
    """Analyse un fichier font et retourne ses métadonnées.

    Ne lève jamais d'exception. Si le fichier est illisible ou corrompu,
    retourne un dict vide ou partiel avec ce qui a pu être extrait.

    Args:
        file_path: Chemin vers le fichier font (TTF, OTF, WOFF, WOFF2).

    Returns:
        Dict contenant les métadonnées extractibles. Les clés correspondent
        aux colonnes de la table fonts du modèle SQLAlchemy.
    """
    file_path = Path(file_path)
    metadata: dict[str, Any] = {}

    try:
        font = TTFont(str(file_path), lazy=True)
    except Exception:
        logger.warning("Impossible d'ouvrir la font : %s", file_path, exc_info=True)
        return metadata

    # Table name
    try:
        metadata.update(_extract_name_table(font))
    except Exception:
        logger.warning("Erreur parsing table name : %s", file_path, exc_info=True)

    # Table OS/2
    try:
        metadata.update(_extract_os2(font))
    except Exception:
        logger.warning("Erreur parsing table OS/2 : %s", file_path, exc_info=True)

    # Cmap → scripts supportés
    try:
        codepoints = _extract_cmap_codepoints(font)
        if codepoints:
            scripts = _detect_scripts(codepoints)
            if scripts:
                metadata["supported_scripts"] = scripts
    except Exception:
        logger.warning("Erreur parsing cmap : %s", file_path, exc_info=True)

    # Glyph count
    try:
        glyph_count = _extract_glyph_count(font)
        if glyph_count is not None:
            metadata["glyph_count"] = glyph_count
    except Exception:
        logger.warning("Erreur extraction glyph count : %s", file_path, exc_info=True)

    # Variable font info
    try:
        metadata.update(_extract_variable_info(font))
    except Exception:
        logger.warning("Erreur parsing fvar : %s", file_path, exc_info=True)

    # Classification (dépend des métadonnées déjà extraites)
    try:
        classification = _classify_font(metadata, font)
        if classification:
            metadata["classification"] = classification
    except Exception:
        logger.warning("Erreur classification : %s", file_path, exc_info=True)

    try:
        font.close()
    except Exception:
        pass

    return metadata
