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

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
port="${PORT:-8080}"

python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

mkdir -p "$dev_root/server/fonts"

export DATABASE_URL="sqlite+aiosqlite:///$dev_root/server/fontsync.db"
export STORAGE_BACKEND="filesystem"
export FONT_STORAGE_PATH="$dev_root/server/fonts"

cd "$repo_root"

echo "==> Migrations (alembic upgrade head)"
"$python_bin" -m alembic upgrade head

echo "==> uvicorn sur http://localhost:$port  (db=$DATABASE_URL)"
exec "$python_bin" -m uvicorn backend.main:app --reload --port "$port"
