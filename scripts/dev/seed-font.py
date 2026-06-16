#!/usr/bin/env python3
"""Génère une vraie font TTF valide dans un dossier — graine de test pour le dev.

Permet d'avoir quelque chose à pousser sans dépendre des fixtures commerciales
(gitignorées). Chaque (famille, style) produit un binaire distinct → hash
distinct → fonts distinctes côté serveur.

Usage :
    python scripts/dev/seed-font.py <dossier> [--family NOM] [--style STYLE]

Exemple (poser une font dans le dossier du device A) :
    python scripts/dev/seed-font.py .dev/A/fonts --family "Dev Sans" --style Regular
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

_FS_REGULAR = 0x40

# ASCII imprimable — assez pour une cmap valide.
_CODEPOINTS = list(range(0x20, 0x7F))


def build_ttf(family: str, style: str) -> bytes:
    """Construit une TTF minimale mais valide en mémoire."""
    glyph_names = [".notdef"] + [f"g{cp:04X}" for cp in _CODEPOINTS]
    cmap = {cp: f"g{cp:04X}" for cp in _CODEPOINTS}

    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(cmap)

    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({name: empty for name in glyph_names})
    fb.setupHorizontalMetrics({name: (500, 0) for name in glyph_names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)

    ps_name = f"{family}-{style}".replace(" ", "")
    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "uniqueFontIdentifier": ps_name,
            "fullName": f"{family} {style}",
            "psName": ps_name,
            "version": "1.0",
        }
    )
    fb.setupOS2(usWeightClass=400, usWidthClass=5, fsSelection=_FS_REGULAR)
    fb.setupPost()

    buffer = io.BytesIO()
    fb.save(buffer)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Génère une TTF de test.")
    parser.add_argument("directory", help="Dossier cible (créé si absent).")
    parser.add_argument("--family", default="Dev Sans")
    parser.add_argument("--style", default="Regular")
    args = parser.parse_args()

    out_dir = Path(args.directory).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{args.family}-{args.style}".replace(" ", "") + ".ttf"
    dest = out_dir / filename
    dest.write_bytes(build_ttf(args.family, args.style))
    print(f"Font générée : {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
