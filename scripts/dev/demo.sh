#!/usr/bin/env bash
#
# Démo de bout en bout de la sync multi-machines, sur un seul Mac.
#
# Scénario : le device A « possède » une font ; un sync A la pousse vers le
# serveur ; un sync B la pull et l'installe dans le dossier isolé de B. On vérifie
# enfin que la font est bien arrivée chez B — preuve que la boucle
# A → serveur → B fonctionne, sans 2ᵉ machine ni vrai ~/Library/Fonts.
#
# Prérequis : un serveur FontSync joignable (cf. scripts/dev/run-server.sh ou
# `docker compose up`). Cible par défaut : http://localhost:8080.
#
# Usage : scripts/dev/demo.sh

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
server_url="${FONTSYNC_SERVER_URL:-http://localhost:8080}"

python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

run_agent="$repo_root/scripts/dev/run-agent.sh"

echo "==> Vérification du serveur ($server_url)"
if ! curl -fsS "$server_url/health" >/dev/null 2>&1; then
  echo "ERREUR : serveur injoignable sur $server_url" >&2
  echo "  Lance-le d'abord :  scripts/dev/run-server.sh   (ou  docker compose up)" >&2
  exit 1
fi

echo "==> Départ propre (.dev/)"
rm -rf "$dev_root/A" "$dev_root/B"

echo "==> Graine d'une font chez le device A"
"$python_bin" "$repo_root/scripts/dev/seed-font.py" \
  "$dev_root/A/fonts" --family "Demo Sans" --style Regular

echo "==> Sync A (push vers le serveur)"
"$run_agent" A sync

echo "==> Sync B (pull depuis le serveur)"
"$run_agent" B sync

echo "==> Vérification : la font est-elle arrivée chez B ?"
if ls "$dev_root"/B/fonts/*.ttf >/dev/null 2>&1; then
  echo "OK — fonts présentes chez B :"
  ls -1 "$dev_root"/B/fonts/
  echo
  echo "Succès : A → serveur → B vérifié."
else
  echo "ÉCHEC : aucune font installée chez B." >&2
  echo "  Vérifie qu'auto_pull est activé pour le device B (frontend ou config)." >&2
  exit 1
fi
