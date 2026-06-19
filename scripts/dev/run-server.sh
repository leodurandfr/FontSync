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
#                       → mettre 0.0.0.0 pour exposer sur le LAN (test multi-Macs)
#   FONTSYNC_TOKEN      token d'instance     (défaut dev : fontsync-dev)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
port="${PORT:-8080}"
host="${HOST:-127.0.0.1}"

python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

mkdir -p "$dev_root/server/fonts"

# Token d'instance FIXE en dev : sinon `auth.py` en génère un aléatoire à chaque
# boot, qu'il faudrait re-saisir dans le TokenGate du frontend et re-passer au
# script de snapshot. Surchargeable via l'env.
export FONTSYNC_TOKEN="${FONTSYNC_TOKEN:-fontsync-dev}"

export DATABASE_URL="sqlite+aiosqlite:///$dev_root/server/fontsync.db"
export STORAGE_BACKEND="filesystem"
export FONT_STORAGE_PATH="$dev_root/server/fonts"

cd "$repo_root"

echo "==> Migrations (alembic upgrade head)"
"$python_bin" -m alembic upgrade head

echo "==> uvicorn sur http://$host:$port  (db=$DATABASE_URL)"
exec "$python_bin" -m uvicorn backend.main:app --reload --host "$host" --port "$port"
