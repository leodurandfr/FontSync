#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# check-archs.sh — contrôle bloquant des architectures d'un FontSync.app (M-21).
#
# Usage : scripts/lib/check-archs.sh --expect "arm64" path/to/FontSync.app
#         scripts/lib/check-archs.sh --expect "arm64 x86_64" path/to/FontSync.app
#
# La 0.1.1 était universelle alors que son agent embarqué n'était qu'arm64 : sur
# un Mac Intel, l'app se lançait avec un agent incapable de tourner. Règles :
#   - Contents/MacOS/FontSync : EXACTEMENT les architectures attendues — c'est
#     lui qui décide sur quels Mac l'app se lance, et ce que generate_appcast
#     déclare à Sparkle (hardwareRequirements) ;
#   - l'interpréteur de l'agent (agent-venv/bin/python3.12), chaque .so/.dylib
#     du bundle (liens compris) et chaque exécutable hors de l'agent-venv
#     (Sparkle.framework : Sparkle, Autoupdate, Updater, services XPC) : AU
#     MOINS les architectures attendues (une roue universal2, pyobjc par
#     exemple, garde une tranche x86_64 inutile mais inoffensive).
# L'énumération est recomptée : un `find` ou un `sort` en échec (dossier
# illisible…) arrête le contrôle au lieu de le laisser conclure « OK ».
#
# Sortie : 0 si tout est conforme, 1 au moindre écart (fichiers listés), 2 sur
# erreur d'usage ou d'énumération. `LIPO` permet de substituer l'outil (tests).
set -euo pipefail

usage() {
  echo "usage : $0 --expect \"arm64\" FontSync.app" >&2
  exit 2
}

expect=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expect)
      [[ $# -ge 2 ]] || usage
      expect="$2"
      shift 2
      ;;
    -h | --help) sed -n '5,24p' "$0"; exit 0 ;;
    -*) echo "option inconnue : $1" >&2; usage ;;
    *) break ;;
  esac
done
[[ $# -eq 1 ]] || usage
app="${1%/}"
LIPO="${LIPO:-lipo}"
command -v "$LIPO" >/dev/null || { echo "lipo introuvable : $LIPO" >&2; exit 2; }

# Liste d'architectures normalisée : triée, dédoublonnée, séparée par des espaces.
norm() { tr -s ' \t\n' '\n' | sed '/^$/d' | sort -u | paste -sd ' ' -; }

want="$(printf '%s' "$expect" | norm)"
[[ -n "$want" ]] || usage

failures=0
checked=0

report() { # $1 = fichier, $2 = message
  echo "ÉCART  ${1#"$app"/} : $2"
  failures=$((failures + 1))
}

archs_of() { "$LIPO" -archs "$1" 2>/dev/null | norm; }

# $1 = fichier, $2 = exact|includes
check() {
  local file="$1" mode="$2" got arch
  checked=$((checked + 1))
  if [[ ! -e "$file" ]]; then
    report "$file" "absent"
    return
  fi
  got="$(archs_of "$file" || true)"
  if [[ -z "$got" ]]; then
    report "$file" "illisible par lipo (pas un Mach-O ?)"
    return
  fi
  if [[ "$mode" == exact ]]; then
    [[ "$got" == "$want" ]] || report "$file" "$got (attendu exactement : $want)"
    return
  fi
  for arch in $want; do
    if [[ " $got " != *" $arch "* ]]; then
      report "$file" "$got (manque : $arch)"
      return
    fi
  done
}

[[ -d "$app" ]] || { echo "bundle introuvable : $app" >&2; exit 2; }

# Bibliothèques natives (fichiers ou liens), puis exécutables hors agent-venv
# (le binaire principal est contrôlé à part, exactement). Liste NUL-séparée.
enumerate_binaries() {
  find "$app" \( -type f -o -type l \) \( -name '*.so' -o -name '*.dylib' \) -print0 || return 1
  find "$app/Contents" \
    \( -path "$app/Contents/Resources/agent-venv" -o -path "$app/Contents/MacOS/FontSync" \) -prune \
    -o -type f -perm -100 ! -name '*.so' ! -name '*.dylib' -print0 || return 1
}

# Une erreur dans `< <(…)` ne remonte pas (set -e/pipefail) : on compte d'abord,
# dans une substitution dont l'échec est, lui, visible.
expected="$(enumerate_binaries | tr -cd '\0' | wc -c | tr -d ' ')" || {
  echo "Énumération du bundle impossible (find en échec)." >&2
  exit 2
}

check "$app/Contents/MacOS/FontSync" exact
check "$app/Contents/Resources/agent-venv/bin/python3.12" includes
while IFS= read -r -d '' bin; do
  check "$bin" includes
done < <(enumerate_binaries | sort -z)

if [[ $checked -ne $((expected + 2)) ]]; then
  echo "Énumération incomplète : $((checked - 2))/$expected binaires contrôlés." >&2
  exit 2
fi

if [[ $failures -gt 0 ]]; then
  echo "Architectures : $failures écart(s) sur $checked binaires (attendu : $want)." >&2
  exit 1
fi
echo "Architectures OK : $checked binaires (attendu : $want)."
