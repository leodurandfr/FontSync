#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# publish-release.sh — téléverse les artefacts macOS sur la GitHub Release (P4.3).
#
# Chaîne complète d'une release publique (cf. docs/RELEASE.md) :
#   1. `git tag vX.Y.Z && git push --tags`
#        → docker-publish.yml publie l'image multi-arch sur ghcr.io ;
#        → release.yml crée la GitHub Release (draft) ;
#   2. ce script (sur un Mac avec Developer ID) :
#        → construit le `.dmg` signé + notarisé + `appcast.xml` (release-macos-app.sh) ;
#        → les téléverse sur la Release du tag (gh release upload --clobber) ;
#   3. on relit/publie la Release (gh release edit --draft=false), ce qui rend
#      l'`appcast.xml` accessible à l'URL Sparkle `releases/latest/download/`.
#
# Aucun secret n'est commité : identité/notarisation/clés Sparkle viennent de
# l'environnement et du Trousseau (cf. macos-app/RELEASE.md).
#
# Pré-requis (env) : les mêmes que release-macos-app.sh
#   VERSION, BUILD, DEVELOPER_ID_APP, TEAM_ID, NOTARY_PROFILE
# Optionnel :
#   REPO=owner/name   (défaut : déduit du remote git via gh)
#   PUBLISH=1         publie la release après téléversement (retire le draft)
#   SKIP_BUILD=1      réutilise un .dmg/appcast déjà présents dans macos-app/dist
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/macos-app/dist"
APP_NAME="FontSync"

: "${VERSION:?VERSION requis (ex. 1.0.0)}"
TAG="v$VERSION"
DMG="$DIST_DIR/$APP_NAME-$VERSION.dmg"
APPCAST="$DIST_DIR/appcast.xml"

command -v gh >/dev/null || { echo "gh (GitHub CLI) requis." >&2; exit 1; }

REPO_ARGS=()
[ -n "${REPO:-}" ] && REPO_ARGS=(--repo "$REPO")

# 1. Construit le .dmg signé + appcast (sauf réutilisation explicite).
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "▶ Build de l'app signée + .dmg (release-macos-app.sh)…"
  "$REPO_ROOT/scripts/release-macos-app.sh"
fi

[ -f "$DMG" ] || { echo "Introuvable : $DMG (lancez sans SKIP_BUILD)." >&2; exit 1; }

# 2. La Release doit exister (créée par release.yml sur le tag). Repli local si
#    on publie hors CI.
if ! gh release view "$TAG" "${REPO_ARGS[@]}" >/dev/null 2>&1; then
  echo "▶ Release $TAG absente — création (draft)…"
  gh release create "$TAG" "${REPO_ARGS[@]}" \
    --title "$APP_NAME $TAG" --generate-notes --draft
fi

# 3. Téléverse les artefacts (--clobber : ré-exécution sûre).
echo "▶ Téléversement des artefacts sur $TAG…"
ASSETS=("$DMG")
[ -f "$APPCAST" ] && ASSETS+=("$APPCAST")
gh release upload "$TAG" "${ASSETS[@]}" "${REPO_ARGS[@]}" --clobber

# 4. Publication optionnelle (retire le draft).
if [ "${PUBLISH:-0}" = "1" ]; then
  echo "▶ Publication de la release $TAG…"
  gh release edit "$TAG" "${REPO_ARGS[@]}" --draft=false --latest
fi

echo "✓ Terminé."
echo "  DMG     : $DMG"
[ -f "$APPCAST" ] && echo "  appcast : $APPCAST"
[ "${PUBLISH:-0}" = "1" ] || echo "  (release en draft : publiez-la avec PUBLISH=1 ou via l'UI GitHub.)"
