#!/usr/bin/env bash
#
# Lance le serveur FontSync sur l'hôte (sans Docker) pour la boucle de dev la
# plus rapide : SQLite + storage dans un dossier jetable, reload à chaud.
#
# Alternative proche-prod : `docker compose up` (même serveur, sur localhost:8080).
#
# Usage : scripts/dev/run-server.sh
#
# Variables d'env :
#   FONTSYNC_DEV_ROOT   racine des données dev (défaut : <repo>/.dev)
#   PORT                port d'écoute        (défaut : 8080)
#   HOST                interface d'écoute   (défaut : 127.0.0.1)
#                       → hors loopback (test multi-Macs), préférer l'IP tailnet
#                         de ce Mac à 0.0.0.0, et jamais avec le token fontsync-dev
#   FONTSYNC_TOKEN      token d'instance     (défaut en loopback : fontsync-dev ;
#                       hors loopback : aléatoire, affiché une fois)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
port="${PORT:-8080}"
host="${HOST:-127.0.0.1}"

python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

is_loopback() {
  case "$1" in
    127.*|localhost|::1|\[::1\]) return 0 ;;
    *) return 1 ;;
  esac
}

# Token d'instance FIXE en loopback : sinon `auth.py` en génère un aléatoire à
# chaque boot, qu'il faudrait re-saisir dans le TokenGate du frontend et
# re-passer au script de snapshot. Hors loopback, le token public du dépôt
# ouvrirait l'API à tout le réseau : refusé, et un token aléatoire le remplace
# quand aucun n'est fourni.
# Le serveur retire les espaces autour du token (`str.strip()`, `backend/auth.py`) :
# comparer la valeur telle qu'il la verra, avec la même règle (pas `tr`, dont la
# notion d'espace diffère de celle de Python).
token_seen="$("$python_bin" -c 'import os; print(os.environ.get("FONTSYNC_TOKEN", "").strip())')"
if is_loopback "$host"; then
  export FONTSYNC_TOKEN="${FONTSYNC_TOKEN:-fontsync-dev}"
elif [ "$token_seen" = "fontsync-dev" ]; then
  echo "ERREUR : HOST=$host expose le serveur hors de cette machine avec le token" >&2
  echo "public « fontsync-dev ». Retirer FONTSYNC_TOKEN (un token aléatoire sera" >&2
  echo "généré) ou en fournir un autre, ou rester en HOST=127.0.0.1." >&2
  exit 2
elif [ -z "$token_seen" ]; then
  FONTSYNC_TOKEN="$("$python_bin" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  export FONTSYNC_TOKEN
  echo "==> Serveur exposé sur $host : token aléatoire de cette session (à donner aux agents) :"
  echo "    $FONTSYNC_TOKEN"
fi

mkdir -p "$dev_root/server/fonts"

export DATABASE_URL="sqlite+aiosqlite:///$dev_root/server/fontsync.db"
export STORAGE_BACKEND="filesystem"
export FONT_STORAGE_PATH="$dev_root/server/fonts"

cd "$repo_root"

echo "==> Migrations (alembic upgrade head)"
"$python_bin" -m alembic upgrade head

echo "==> uvicorn sur http://$host:$port  (db=$DATABASE_URL)"
exec "$python_bin" -m uvicorn backend.main:app --reload --host "$host" --port "$port"
