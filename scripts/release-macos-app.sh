#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Leo Durand
#
# release-macos-app.sh — chaîne de release complète de l'app Mac FontSync (P3.7) :
#   1. construit l'agent Python embarqué (relocatable) ;
#   2. compile l'app (Release) signée Developer ID (xcodebuild) ;
#   3. embarque l'agent dans Contents/Resources/agent-venv ;
#   4. signe « inside-out » (chaque .so/.dylib → interpréteur → app), Hardened
#      Runtime + horodatage, SANS --deep ;
#   5. vérifie la signature (codesign --verify + Gatekeeper spctl) ;
#   6. fabrique un .dmg ;
#   7. notarise le .dmg (notarytool) et le staple ;
#   8. signe l'artefact pour Sparkle et (re)génère l'appcast.
#
# Le script ne contient AUCUN secret : identité, équipe, profil de notarisation
# et clés Sparkle viennent de l'environnement / du Trousseau (cf. RELEASE.md).
#
# Pré-requis (env) :
#   DEVELOPER_ID_APP   "Developer ID Application: Nom (TEAMID)"
#   TEAM_ID            identifiant d'équipe (10 car.)
#   NOTARY_PROFILE     profil notarytool stocké via `notarytool store-credentials`
#   VERSION            ex. 1.0.0   (CFBundleShortVersionString)
#   BUILD              ex. 1       (CFBundleVersion ; entier monotone)
# Optionnel : ARCH=universal2 (défaut: arche hôte), SKIP_NOTARIZE=1, SKIP_APPCAST=1
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/macos-app"
BUILD_DIR="$APP_DIR/build"
DIST_DIR="$APP_DIR/dist"
APP_NAME="FontSync"

: "${VERSION:?VERSION requis (ex. 1.0.0)}"
: "${BUILD:?BUILD requis (ex. 1)}"
: "${DEVELOPER_ID_APP:?DEVELOPER_ID_APP requis (Developer ID Application: …)}"
: "${TEAM_ID:?TEAM_ID requis}"
ARCH="${ARCH:-host}"

# Le cache SPM de Sparkle est un dépôt git « bare » ; certaines configs git
# globales (safe.bareRepository=explicit) le rejettent. On neutralise pour ce run.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.bareRepository GIT_CONFIG_VALUE_0=all

step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
step "1/8 Agent Python embarqué ($ARCH)"
"$REPO_ROOT/scripts/build-agent-venv.sh" --out "$BUILD_DIR/agent-venv" --arch "$ARCH"

# ---------------------------------------------------------------------------
step "2/8 Compilation Release signée Developer ID"
DERIVED="$BUILD_DIR/DerivedData"
xcodebuild \
  -project "$APP_DIR/$APP_NAME.xcodeproj" \
  -scheme "$APP_NAME" \
  -configuration Release \
  -derivedDataPath "$DERIVED" \
  -clonedSourcePackagesDirPath "$BUILD_DIR/SourcePackages" \
  MARKETING_VERSION="$VERSION" \
  CURRENT_PROJECT_VERSION="$BUILD" \
  CODE_SIGN_STYLE=Manual \
  CODE_SIGN_IDENTITY="$DEVELOPER_ID_APP" \
  DEVELOPMENT_TEAM="$TEAM_ID" \
  OTHER_CODE_SIGN_FLAGS="--timestamp --options=runtime" \
  build

APP="$DERIVED/Build/Products/Release/$APP_NAME.app"
[[ -d "$APP" ]] || { echo "App introuvable : $APP" >&2; exit 1; }

# ---------------------------------------------------------------------------
step "3/8 Embarquement de l'agent dans le bundle"
RES_VENV="$APP/Contents/Resources/agent-venv"
rm -rf "$RES_VENV"
mkdir -p "$APP/Contents/Resources"
cp -R "$BUILD_DIR/agent-venv" "$RES_VENV"

# ---------------------------------------------------------------------------
step "4/8 Signature inside-out (Hardened Runtime + horodatage)"
PY_ENTS="$APP_DIR/PythonAgent.entitlements"
APP_ENTS="$APP_DIR/FontSync.entitlements"
sign() { codesign --force --timestamp --options runtime --sign "$DEVELOPER_ID_APP" "$@"; }

# 4a. Toutes les bibliothèques natives de l'agent (.so / .dylib), du plus profond
#     au moins profond. find depuis le dossier (chemins relatifs) = fiable.
( cd "$RES_VENV" && find . \( -name '*.so' -o -name '*.dylib' \) -print0 ) \
  | while IFS= read -r -d '' rel; do
      sign --entitlements "$PY_ENTS" "$RES_VENV/${rel#./}"
    done

# 4b. Les exécutables de l'interpréteur (binaire réel, pas les symlinks).
( cd "$RES_VENV/bin" && find . -type f -perm -u+x -print0 ) \
  | while IFS= read -r -d '' rel; do
      f="$RES_VENV/bin/${rel#./}"
      # Ne signer que les Mach-O (ignorer les scripts shell/python type `pip`).
      if file "$f" | grep -q 'Mach-O'; then
        sign --entitlements "$PY_ENTS" "$f"
      fi
    done

# 4c. Re-scelle l'app (l'ajout de agent-venv a invalidé le sceau extérieur).
#     PAS de --deep : Sparkle.framework et ses XPC gardent leur signature Xcode.
sign --entitlements "$APP_ENTS" "$APP"

# ---------------------------------------------------------------------------
step "5/8 Vérification de signature"
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose=4 "$APP" || \
  echo "  (spctl refusera tant que la notarisation n'est pas faite — normal ici.)"

# ---------------------------------------------------------------------------
step "6/8 Fabrication du .dmg"
mkdir -p "$DIST_DIR"
DMG="$DIST_DIR/$APP_NAME-$VERSION.dmg"
rm -f "$DMG"
if command -v create-dmg >/dev/null; then
  create-dmg \
    --volname "$APP_NAME $VERSION" \
    --app-drop-link 450 180 \
    --icon "$APP_NAME.app" 150 180 \
    --window-size 600 360 \
    "$DMG" "$APP" >/dev/null
else
  # Repli sans create-dmg : image lisible avec un lien /Applications.
  STAGE="$(mktemp -d)"; cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "$APP_NAME $VERSION" -srcfolder "$STAGE" \
    -ov -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
fi
sign "$DMG"   # le .dmg lui-même est signé Developer ID
echo "  → $DMG"

# ---------------------------------------------------------------------------
step "7/8 Notarisation + stapling"
if [[ "${SKIP_NOTARIZE:-0}" == "1" ]]; then
  echo "  SKIP_NOTARIZE=1 → étape ignorée."
else
  : "${NOTARY_PROFILE:?NOTARY_PROFILE requis (notarytool store-credentials)}"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler staple "$APP"   # staple aussi l'app (utile hors DMG)
  spctl --assess --type install --verbose=4 "$DMG"
fi

# ---------------------------------------------------------------------------
step "8/8 Sparkle : signature de l'artefact + appcast"
if [[ "${SKIP_APPCAST:-0}" == "1" ]]; then
  echo "  SKIP_APPCAST=1 → étape ignorée."
else
  # Les outils Sparkle sont livrés dans l'artefact SPM résolu par xcodebuild.
  SPARKLE_BIN="$(find "$BUILD_DIR/SourcePackages/artifacts" -path '*/Sparkle/bin' -type d 2>/dev/null | head -1)"
  if [[ -z "$SPARKLE_BIN" ]]; then
    echo "  Outils Sparkle introuvables ($BUILD_DIR/SourcePackages/artifacts) — appcast à générer à la main." >&2
  else
    # generate_appcast lit la clé privée EdDSA dans le Trousseau (cf. generate_keys)
    # et produit/maj appcast.xml à partir des artefacts présents dans le dossier.
    "$SPARKLE_BIN/generate_appcast" "$DIST_DIR"
    echo "  → appcast : $DIST_DIR/appcast.xml"
    echo "  → signature EdDSA isolée (pour notes de release) :"
    "$SPARKLE_BIN/sign_update" "$DMG" || true
  fi
fi

step "Terminé : $DMG"
echo "Publier : le .dmg + appcast.xml sur la GitHub Release (cf. SUFeedURL dans Info.plist)."
