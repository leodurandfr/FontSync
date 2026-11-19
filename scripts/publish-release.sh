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
#        → VÉRIFIE l'appcast (scripts/lib/check-appcast.py) : un item pour
#          $VERSION, enclosure sur `releases/download/v$VERSION/`, taille et
#          signature EdDSA du DMG — sinon rien n'est envoyé (B-88) ;
#        → les téléverse sur la Release du tag (gh release upload --clobber) ;
#   3. avec PUBLISH=1 : publie la Release versionnée (« latest », pour les
#      clients ≤ 0.1.1 dont le flux est `releases/latest/download/appcast.xml`),
#      PUIS met à jour le flux stable : asset `appcast.xml` de la release fixe
#      `appcast` (jamais « latest »), lu par `SUFeedURL` depuis la 0.1.2.
#
# Aucun secret n'est commité : identité/notarisation/clés Sparkle viennent de
# l'environnement et du Trousseau (cf. macos-app/RELEASE.md).
#
# Pré-requis (env) : les mêmes que release-macos-app.sh
#   VERSION, BUILD, DEVELOPER_ID_APP, TEAM_ID, NOTARY_PROFILE
# Optionnel :
#   REPO=owner/name   (défaut : leodurandfr/FontSync, cf. SUFeedURL d'Info.plist)
#   PUBLISH=1         publie la release après téléversement (retire le draft)
#                     et met à jour le flux stable ; exige l'appcast
#   SKIP_BUILD=1      réutilise un .dmg/appcast déjà présents dans macos-app/dist
#   SIGN_UPDATE=…     outil sign_update de Sparkle (défaut : celui du dernier
#                     build ; `none` pour ne pas comparer la signature)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/macos-app/dist"
APP_NAME="FontSync"

: "${VERSION:?VERSION requis (ex. 1.0.0)}"
TAG="v$VERSION"
DMG="$DIST_DIR/$APP_NAME-$VERSION.dmg"
APPCAST="$DIST_DIR/appcast.xml"
FEED_REPO="${REPO:-leodurandfr/FontSync}"
# Flux Sparkle stable (SUFeedURL ≥ 0.1.2) : asset d'une release fixe, jamais
# « latest » — une release serveur ou un oubli d'appcast ne le casse plus.
STABLE_TAG="appcast"

command -v gh >/dev/null || { echo "gh (GitHub CLI) requis." >&2; exit 1; }

# Toujours explicite : sans --repo, gh viserait le dépôt du dossier courant (un
# fork, un autre remote) alors que l'appcast désigne $FEED_REPO.
REPO_ARGS=(--repo "$FEED_REPO")
# `"${REPO_ARGS[@]+"${REPO_ARGS[@]}"}"` (pas juste `"${REPO_ARGS[@]}"`) : le
# bash 3.2 livré par macOS traite l'expansion d'un tableau vide comme une
# variable non définie sous `set -u` et fait échouer le script.

# 1. Construit le .dmg signé + appcast (sauf réutilisation explicite).
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "▶ Build de l'app signée + .dmg (release-macos-app.sh)…"
  "$REPO_ROOT/scripts/release-macos-app.sh"
fi

[ -f "$DMG" ] || { echo "Introuvable : $DMG (lancez sans SKIP_BUILD)." >&2; exit 1; }

# 2. Contrôle de l'appcast AVANT tout envoi (B-88, B-100).
if [ -f "$APPCAST" ]; then
  SIGN_UPDATE="${SIGN_UPDATE-$( (find "$REPO_ROOT/macos-app/build/SourcePackages/artifacts" \
    -path '*/Sparkle/bin/sign_update' -type f 2>/dev/null || true) | head -1)}"
  CHECK_ARGS=(--version "$VERSION" --dmg "$DMG" --repo "$FEED_REPO")
  [ -n "${BUILD:-}" ] && CHECK_ARGS+=(--build "$BUILD")
  if [ -n "$SIGN_UPDATE" ] && [ "$SIGN_UPDATE" != "none" ]; then
    SIG="$( ("$SIGN_UPDATE" "$DMG" || true) | sed -n 's/.*sparkle:edSignature="\([^"]*\)".*/\1/p')"
    [ -n "$SIG" ] || { echo "sign_update n'a pas rendu de signature : rien n'a été envoyé." >&2; exit 1; }
    CHECK_ARGS+=(--ed-signature "$SIG")
  else
    echo "  (sign_update introuvable : signature EdDSA de l'appcast non comparée au DMG.)"
  fi
  python3 "$REPO_ROOT/scripts/lib/check-appcast.py" "$APPCAST" "${CHECK_ARGS[@]}" || {
    echo "Appcast incohérent avec $DMG : rien n'a été envoyé." >&2
    exit 1
  }
elif [ "${PUBLISH:-0}" = "1" ]; then
  echo "Introuvable : $APPCAST — publication refusée (les clients ne verraient pas la mise à jour)." >&2
  exit 1
else
  echo "  (pas d'appcast.xml : seul le .dmg part, en draft ; PUBLISH=1 l'exigera.)"
fi

# Publier rend la version « latest » et la pose sur le flux stable : seulement
# pour une version finale (pas de « -rc1 »), dont le tag existe ici et qui est
# le plus haut tag v* final — sinon le flux et « latest » reculeraient.
if [ "${PUBLISH:-0}" = "1" ]; then
  case "$VERSION" in
    *-*)
      echo "Pré-release $VERSION : PUBLISH=1 refusé (le flux stable et « latest » sont réservés aux versions finales)." >&2
      echo "  Publier à la main : gh release edit $TAG --repo $FEED_REPO --draft=false --prerelease --latest=false" >&2
      exit 1
      ;;
  esac
  HIGHEST="$(git -C "$REPO_ROOT" tag -l 'v*' 2>/dev/null | grep -v -- - | sort -V | tail -1 || true)"
  if ! git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
    echo "Tag $TAG absent de ce dépôt : PUBLISH=1 refusé (git fetch --tags ?)." >&2
    exit 1
  fi
  if [ "$HIGHEST" != "$TAG" ]; then
    echo "$TAG n'est pas la plus haute version publiée ($HIGHEST) : PUBLISH=1 refusé (le flux stable reculerait)." >&2
    exit 1
  fi
fi

# 3. La Release doit exister (créée par release.yml sur le tag). Repli local si
#    on publie hors CI.
if ! gh release view "$TAG" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" >/dev/null 2>&1; then
  echo "▶ Release $TAG absente — création (draft)…"
  gh release create "$TAG" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" \
    --title "$APP_NAME $TAG" --generate-notes --draft
fi

# 4. Téléverse les artefacts (--clobber : ré-exécution sûre).
echo "▶ Téléversement des artefacts sur ${TAG}…"
ASSETS=("$DMG")
[ -f "$APPCAST" ] && ASSETS+=("$APPCAST")
gh release upload "$TAG" "${ASSETS[@]}" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" --clobber

# 5. Publication optionnelle (retire le draft), puis flux stable : seulement une
#    fois la release versionnée publique, sinon son enclosure renverrait 404.
if [ "${PUBLISH:-0}" = "1" ]; then
  echo "▶ Publication de la release ${TAG}…"
  # --latest : les clients ≤ 0.1.1 lisent releases/latest/download/appcast.xml.
  gh release edit "$TAG" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" --draft=false --latest

  echo "▶ Flux stable (release « $STABLE_TAG »)…"
  if ! gh release view "$STABLE_TAG" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" >/dev/null 2>&1; then
    gh release create "$STABLE_TAG" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" \
      --title "Sparkle appcast (FontSync.app)" \
      --notes "Flux de mise à jour de l'app macOS (SUFeedURL). Ne pas supprimer." \
      --prerelease --latest=false
  fi
  # --clobber supprime l'ancien asset avant d'envoyer le nouveau : en cas d'échec,
  # le flux stable manque jusqu'à la relance (les clients réessaient au prochain
  # contrôle, sans rien installer).
  gh release upload "$STABLE_TAG" "$APPCAST" "${REPO_ARGS[@]+"${REPO_ARGS[@]}"}" --clobber || {
    echo "Flux stable NON mis à jour. Relancer :" >&2
    echo "  gh release upload $STABLE_TAG \"$APPCAST\" --repo $FEED_REPO --clobber" >&2
    exit 1
  }
fi

echo "✓ Terminé."
echo "  DMG     : $DMG"
[ -f "$APPCAST" ] && echo "  appcast : $APPCAST"
[ "${PUBLISH:-0}" = "1" ] || echo "  (release en draft : publiez-la avec PUBLISH=1 SKIP_BUILD=1 — pas via l'UI GitHub, qui ne met pas à jour le flux stable.)"
