#!/usr/bin/env bash
# =============================================================================
# Build script — FontSync Agent macOS .app bundle
#
# Produit un bundle .app autonome via PyInstaller, avec options pour
# la signature (codesign) et la notarisation Apple (notarytool).
#
# Prérequis :
#   - Python 3.12+
#   - PyInstaller (pip install pyinstaller)
#   - Xcode command line tools (pour codesign / notarytool)
#
# Usage :
#   ./scripts/build_agent.sh              # Build seul
#   ./scripts/build_agent.sh --sign       # Build + signature
#   ./scripts/build_agent.sh --notarize   # Build + signature + notarisation
#
# Variables d'environnement (signature/notarisation) :
#   FONTSYNC_SIGN_IDENTITY   — identité codesign (défaut: "Developer ID Application")
#   FONTSYNC_APPLE_ID        — Apple ID pour notarytool
#   FONTSYNC_TEAM_ID         — Team ID Apple Developer
#   FONTSYNC_NOTARY_PASSWORD — mot de passe spécifique à l'app (app-specific password)
# =============================================================================

set -euo pipefail

# ---- Chemins ----
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$PROJECT_DIR/agent"
DIST_DIR="$PROJECT_DIR/dist"
SCRIPTS_DIR="$PROJECT_DIR/scripts"

APP_NAME="FontSync Agent"
BUNDLE_ID="com.fontsync.agent"
AGENT_VERSION="0.1.0"

# ---- Parse des flags ----
DO_SIGN=false
DO_NOTARIZE=false

for arg in "$@"; do
    case $arg in
        --sign) DO_SIGN=true ;;
        --notarize) DO_NOTARIZE=true; DO_SIGN=true ;;
        --help|-h)
            echo "Usage: $0 [--sign] [--notarize]"
            exit 0
            ;;
    esac
done

echo "╔══════════════════════════════════════╗"
echo "║    FontSync Agent — Build macOS      ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ---- Nettoyage ----
echo "==> Nettoyage des builds précédents..."
rm -rf "$DIST_DIR/$APP_NAME.app" "$DIST_DIR/build" "$DIST_DIR/$APP_NAME"

# ---- Vérification des dépendances ----
echo "==> Vérification des dépendances..."
python3 -c "import PyInstaller" 2>/dev/null || {
    echo "    PyInstaller non trouvé. Installation..."
    pip install pyinstaller --quiet
}

# ---- Build PyInstaller ----
echo "==> Génération du bundle .app via PyInstaller..."
python3 -m PyInstaller \
    --name "$APP_NAME" \
    --windowed \
    --onedir \
    --noconfirm \
    --distpath "$DIST_DIR" \
    --workpath "$DIST_DIR/build" \
    --specpath "$DIST_DIR/build" \
    --hidden-import "pystray._darwin" \
    --hidden-import "PIL._imaging" \
    --hidden-import "PIL.ImageDraw" \
    --hidden-import "agent.tray" \
    --hidden-import "agent.notifier" \
    --hidden-import "agent.font_installer" \
    --hidden-import "agent.discovery" \
    --hidden-import "agent.scanner" \
    --hidden-import "agent.sync_client" \
    --hidden-import "agent.config" \
    --collect-all "pystray" \
    --collect-all "watchdog" \
    --osx-bundle-identifier "$BUNDLE_ID" \
    "$AGENT_DIR/main.py"

# ---- Ajustement Info.plist ----
# LSUIElement = true : masque l'icône du Dock, garde uniquement le tray icon
PLIST="$DIST_DIR/$APP_NAME.app/Contents/Info.plist"

if [ -f "$PLIST" ]; then
    /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$PLIST"

    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $AGENT_VERSION" "$PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $AGENT_VERSION" "$PLIST" 2>/dev/null || true

    echo "    Info.plist configuré (LSUIElement=true)"
fi

echo "==> Bundle créé : $DIST_DIR/$APP_NAME.app"
echo ""

# =============================================================================
# Signature (codesign)
# =============================================================================
# Requiert un certificat "Developer ID Application" dans le trousseau macOS.
# Obtenable via Apple Developer Program (99$/an).
#
# Pour lister les identités disponibles :
#   security find-identity -v -p codesigning
# =============================================================================

if [ "$DO_SIGN" = true ]; then
    CERT="${FONTSYNC_SIGN_IDENTITY:-Developer ID Application}"
    echo "==> Signature avec : $CERT"

    # Signer d'abord les frameworks et dylibs internes (--deep est déconseillé
    # par Apple pour les bundles contenant des frameworks car il signe dans le
    # mauvais ordre et peut être rejeté par Gatekeeper/Notarization)
    FRAMEWORKS_DIR="$DIST_DIR/$APP_NAME.app/Contents/Frameworks"
    if [ -d "$FRAMEWORKS_DIR" ]; then
        find "$FRAMEWORKS_DIR" \( -name "*.dylib" -o -name "*.so" \) -exec \
            codesign --force --options runtime --sign "$CERT" \
            --entitlements "$SCRIPTS_DIR/entitlements.plist" {} \;
    fi

    # Puis signer le bundle principal
    codesign \
        --force \
        --options runtime \
        --sign "$CERT" \
        --entitlements "$SCRIPTS_DIR/entitlements.plist" \
        "$DIST_DIR/$APP_NAME.app"

    # Vérification
    codesign --verify --deep --strict "$DIST_DIR/$APP_NAME.app"
    echo "    Signature vérifiée ✓"
    echo ""
fi

# =============================================================================
# Notarisation Apple (notarytool)
# =============================================================================
# Apple scanne le binaire côté serveur et délivre un ticket.
# Gatekeeper accepte ensuite l'app sans avertissement.
#
# Prérequis :
#   - Xcode 13+ (pour xcrun notarytool)
#   - App-specific password : https://appleid.apple.com → App-Specific Passwords
#
# Alternative : stocker les credentials dans le trousseau :
#   xcrun notarytool store-credentials "fontsync-notary" \
#       --apple-id "$FONTSYNC_APPLE_ID" \
#       --team-id "$FONTSYNC_TEAM_ID" \
#       --password "$FONTSYNC_NOTARY_PASSWORD"
#   Puis utiliser : --keychain-profile "fontsync-notary"
# =============================================================================

if [ "$DO_NOTARIZE" = true ]; then
    echo "==> Création du ZIP pour soumission..."
    ZIP_PATH="$DIST_DIR/FontSyncAgent-${AGENT_VERSION}.zip"
    ditto -c -k --sequesterRsrc --keepParent \
        "$DIST_DIR/$APP_NAME.app" \
        "$ZIP_PATH"

    echo "==> Soumission à Apple Notary Service..."
    xcrun notarytool submit "$ZIP_PATH" \
        --apple-id "${FONTSYNC_APPLE_ID}" \
        --team-id "${FONTSYNC_TEAM_ID}" \
        --password "${FONTSYNC_NOTARY_PASSWORD}" \
        --wait

    echo "==> Agrafage du ticket de notarisation (stapling)..."
    xcrun stapler staple "$DIST_DIR/$APP_NAME.app"

    rm -f "$ZIP_PATH"
    echo "    Notarisation terminée ✓"
    echo ""
fi

# =============================================================================
# Création du DMG (optionnel)
# =============================================================================
# Requiert create-dmg : brew install create-dmg
# =============================================================================

if command -v create-dmg &>/dev/null; then
    DMG_PATH="$DIST_DIR/FontSyncAgent-${AGENT_VERSION}.dmg"
    echo "==> Création du DMG..."

    # Supprimer un DMG existant (create-dmg refuse d'écraser)
    rm -f "$DMG_PATH"

    create-dmg \
        --volname "FontSync Agent $AGENT_VERSION" \
        --window-size 540 380 \
        --icon-size 128 \
        --icon "$APP_NAME.app" 130 190 \
        --hide-extension "$APP_NAME.app" \
        --app-drop-link 410 190 \
        "$DMG_PATH" \
        "$DIST_DIR/$APP_NAME.app"

    echo "    DMG : $DMG_PATH"
    echo ""
fi

echo "==> Build terminé."
