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
