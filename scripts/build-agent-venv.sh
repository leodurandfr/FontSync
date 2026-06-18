#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# build-agent-venv.sh — construit l'environnement Python *relocatable* de l'agent
# FontSync à embarquer dans l'app Mac (cf. PLAN-PUBLICATION.md P0.3 / P3.7).
#
# Stratégie (P0.3) : CPython « standalone » (python-build-standalone, via `uv`),
# relocatable par construction (la stdlib se résout relativement à l'exécutable),
# COPIÉ dans le bundle puis garni des dépendances de l'agent par pip. On NE crée
# PAS un venv classique : un venv ne contient pas la stdlib (il pointe vers un
# interpréteur de base par chemin absolu) → impossible à déplacer dans `/Applications`.
# L'arbre produit expose `bin/python3`, ce qu'attend `AgentController` côté Swift.
#
# pyobjc est volontairement installé par *pip* (son chemin supporté) plutôt que
# figé par un freezer — c'est l'argument décisif de P0.3.
#
# Usage :
#   scripts/build-agent-venv.sh [--out DIR] [--python 3.12] [--arch host|universal2]
#
# Par défaut : arch de la machine (arm64 sur Apple Silicon). `--arch universal2`
# fusionne arm64 + x86_64 au lipo pour couvrir les Macs Intel (cf. RELEASE.md) —
# à valider sur du vrai matériel Intel.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/macos-app/build/agent-venv"
PYVER="3.12"
ARCH="host"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --python) PYVER="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Argument inconnu : $1" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "uv requis (https://docs.astral.sh/uv/)." >&2; exit 1; }

# Installe un seul arbre CPython standalone pour une arche donnée, garni des deps
# de l'agent. $1 = dossier de sortie, $2 = arche cible (aarch64|x86_64).
build_one() {
  local dest="$1" archtag="$2"
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"

  # 1. Récupère l'install CPython standalone de CETTE arche (cache uv). On vise
  #    l'arche explicitement pour que la moitié x86_64 d'un build universal2
  #    parte du bon interpréteur (et pas de l'arm64 hôte).
  uv python install "cpython-$PYVER-macos-$archtag" >/dev/null
  local base
  base="$(uv python find "cpython-$PYVER-macos-$archtag")"  # .../install/bin/python3
  base="$(cd "$(dirname "$base")/.." && pwd)"               # racine de l'install

  # 2. Copie l'arbre complet (interpréteur + stdlib) dans la cible.
  cp -R "$base" "$dest"
  # Lève le verrou PEP 668 hérité de uv (« externally managed ») : la copie est
  # désormais notre arbre privé, on doit pouvoir y pip-installer l'agent. Le
  # marqueur est toujours à `lib/pythonX.Y/EXTERNALLY-MANAGED` (chemin déterministe).
  rm -f "$dest"/lib/python*/EXTERNALLY-MANAGED

  # 3. Installe l'agent + ses deps DANS l'arbre copié (pas de venv séparé).
  #    uv introspecte l'interpréteur copié (l'arche x86_64 nécessite Rosetta 2
  #    sur un Mac Apple Silicon) et résout les wheels de la bonne arche.
  uv pip install --python "$dest/bin/python3" --no-cache "$REPO_ROOT"

  # 4. Allègement : caches de compilation (chemins relatifs : find depuis cwd
  #    est fiable ici, contrairement à un find récursif depuis un path absolu).
  ( cd "$dest" && find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true )
  ( cd "$dest" && find . -name '*.pyc' -delete 2>/dev/null || true )
}

echo "→ Construction de l'environnement agent ($ARCH, Python $PYVER)…"

if [[ "$ARCH" == "universal2" ]]; then
  # Construit les deux arches séparément puis fusionne les Mach-O au lipo.
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  build_one "$TMP/arm64"  "aarch64"
  build_one "$TMP/x86_64" "x86_64"

  rm -rf "$OUT"; cp -R "$TMP/arm64" "$OUT"
  # Fusionne tout binaire Mach-O présent dans les deux arbres (interpréteur + .so).
  while IFS= read -r rel; do
    a="$TMP/arm64/$rel"; b="$TMP/x86_64/$rel"; o="$OUT/$rel"
    if [[ -f "$a" && -f "$b" ]] && file "$a" | grep -q 'Mach-O'; then
      lipo -create "$a" "$b" -output "$o" 2>/dev/null || true
    fi
  done < <(cd "$TMP/arm64" && find . -type f)
  echo "⚠️  universal2 fusionné au lipo — À VALIDER sur du matériel Intel réel."
else
  # Arche de la machine : arm64 (uname) → aarch64 (nomenclature uv/PBS).
  host_tag="$([[ "$(uname -m)" == "arm64" ]] && echo aarch64 || echo x86_64)"
  build_one "$OUT" "$host_tag"
fi

echo "✓ Agent embarqué prêt : $OUT"
"$OUT/bin/python3" -c "import agent, httpx, yaml; print('  import agent OK :', agent.__name__)"
echo "  Taille : $(du -sh "$OUT" | cut -f1)"
