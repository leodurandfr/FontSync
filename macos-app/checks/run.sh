#!/usr/bin/env bash
#
# Vérifications des fonctions pures de l'app (pas de cible XCTest dans le
# projet) : compile chaque fichier vérifié avec ses vérifications, puis les lance.
#
# Usage : macos-app/checks/run.sh

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$(mktemp -d "${TMPDIR:-/tmp}/fontsync-checks.XXXXXX")"
trap 'rm -rf "$out"' EXIT

swiftc -o "$out/launchd-status-checks" \
  "$here/../FontSync/LaunchdStatus.swift" \
  "$here/LaunchdStatusChecks.swift"
"$out/launchd-status-checks"

swiftc -o "$out/webview-ui-delegate-checks" \
  "$here/../FontSync/WebView.swift" \
  "$here/WebViewUIDelegateChecks.swift"
# La vérification héberge une vraie WKWebView : son magasin de données (caches,
# WebsiteData) atterrit dans un dossier jetable, pas dans ~/Library.
mkdir -p "$out/home"
CFFIXED_USER_HOME="$out/home" "$out/webview-ui-delegate-checks"
