#!/usr/bin/env python3
"""Vérifie que macOS voit réellement les polices posées dans un dossier.

Depuis macOS 14/15, un fichier présent dans ~/Library/Fonts n'est pas pour
autant installé : tant que `fontd` n'a pas réindexé, la police n'existe pour
aucune application. Ce script mesure l'écart entre *les fichiers sur le disque*
et *les polices réellement disponibles*.

Deux précautions, apprises à la dure :

- **Ne pas se fier à `system_profiler SPFontsDataType`** : il rend un instantané
  périmé et affiche comme installées des polices que rien ne voit. La seule
  source fiable est Core Text (`CTFontCollectionCreateFromAvailableFonts`).
- **Comparer les familles sur le nameID 16** (famille typographique), pas le
  nameID 1, souvent qualifié par le style (« GT Standard M Ext Black ») : la
  comparaison par nameID 1 produit des faux négatifs en masse.

Usage :
    scripts/check-font-index.py [--dir ~/Library/Fonts] [--limit 20]

Code de sortie : 0 si tout ce qui est sur le disque est visible, 1 sinon —
utilisable tel quel après un sync pour savoir si la réindexation a abouti.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


def available_font_paths() -> set[Path]:
    """Chemins des polices que Core Text expose réellement aux applications."""
    import CoreText  # type: ignore[import-untyped]

    collection = CoreText.CTFontCollectionCreateFromAvailableFonts(None)
    descriptors = CoreText.CTFontCollectionCreateMatchingFontDescriptors(collection)
    if descriptors is None:
        return set()

    paths: set[Path] = set()
    for desc in descriptors:
        url = CoreText.CTFontDescriptorCopyAttribute(desc, CoreText.kCTFontURLAttribute)
        if url is None:
            continue
        path = str(url.path() or "")
        if path:
            paths.add(Path(path).resolve())
    return paths


def typographic_family(path: Path) -> str | None:
    """Famille typographique (nameID 16, repli nameID 1) du fichier.

    Retourne None si le fichier est illisible ou dépourvu de table `name` : une
    font malformée ne doit jamais interrompre le diagnostic.
    """
    try:
        from fontTools.ttLib import TTCollection, TTFont

        if path.suffix.lower() == ".ttc":
            with TTCollection(str(path), lazy=True) as ttc:
                fonts = list(ttc.fonts)
        else:
            fonts = [TTFont(str(path), lazy=True, fontNumber=0)]

        for font in fonts:
            name = font["name"]
            for name_id in (16, 1):
                value = name.getDebugName(name_id)
                if value:
                    return str(value).strip()
    except Exception:
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.home() / "Library" / "Fonts",
        help="dossier à vérifier (défaut : ~/Library/Fonts)",
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="nombre d'exemples listés (défaut : 20)"
    )
    args = parser.parse_args()

    directory: Path = args.dir.expanduser()
    if not directory.is_dir():
        print(f"Dossier introuvable : {directory}", file=sys.stderr)
        return 2

    try:
        visible = available_font_paths()
    except ImportError:
        print(
            "pyobjc-framework-CoreText requis (pip install pyobjc-framework-CoreText)",
            file=sys.stderr,
        )
        return 2

    on_disk = sorted(
        p.resolve()
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in FONT_EXTENSIONS
    )
    missing = [p for p in on_disk if p not in visible]

    # Vue par famille : c'est ce que l'utilisateur constate dans Livre des
    # polices. Une famille n'est réputée absente que si *aucun* de ses fichiers
    # n'est visible (sinon on signalerait une famille partiellement indexée
    # comme manquante).
    families: dict[str, list[bool]] = defaultdict(list)
    for path in on_disk:
        family = typographic_family(path)
        if family:
            families[family].append(path in visible)
    missing_families = sorted(f for f, seen in families.items() if not any(seen))
    partial_families = sorted(
        f for f, seen in families.items() if any(seen) and not all(seen)
    )

    print(f"Dossier            : {directory}")
    print(f"Fichiers sur disque: {len(on_disk)}")
    print(f"Vus par Core Text  : {len(on_disk) - len(missing)}")
    print(f"Familles (nameID 16): {len(families)} — {len(missing_families)} invisibles")

    if partial_families:
        print(f"\nFamilles partiellement indexées ({len(partial_families)}) :")
        for family in partial_families[: args.limit]:
            print(f"  ~ {family}")

    if missing:
        print(f"\nFichiers invisibles pour les applications ({len(missing)}) :")
        for path in missing[: args.limit]:
            print(f"  ✗ {path.name}")
        if len(missing) > args.limit:
            print(f"  … et {len(missing) - args.limit} autres")
        if missing_families:
            print(f"\nFamilles entièrement absentes ({len(missing_families)}) :")
            for family in missing_families[: args.limit]:
                print(f"  ✗ {family}")
            if len(missing_families) > args.limit:
                print(f"  … et {len(missing_families) - args.limit} autres")
        print(
            "\nL'index n'est pas à jour. `killall fontd fontworker` puis attendre "
            "quelques dizaines de secondes avant de re-vérifier."
        )
        return 1

    print("\nTout le dossier est visible par Core Text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
