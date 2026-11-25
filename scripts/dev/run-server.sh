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
#                         de ce Mac à 0.0.0.0
#   FONTSYNC_DEV_EMAIL     compte admin de dev, créé au premier lancement si la
#   FONTSYNC_DEV_PASSWORD  base n'a aucun compte (défaut en loopback :
#                          dev@example.com / fontsync-dev-password ; hors
#                          loopback : mot de passe aléatoire, affiché une fois)

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

# Compte admin de dev, créé au démarrage si la base n'en a aucun
# (`FONTSYNC_ADMIN_EMAIL`/`_PASSWORD`, cf. backend/services/accounts.py) : les
# agents de dev s'y connectent (`run-agent.sh`) sans passer par l'interface.
# Hors loopback, le mot de passe public du dépôt ouvrirait l'API à tout le
# réseau : refusé, et un mot de passe aléatoire le remplace quand aucun n'est
# fourni.
dev_password_default="fontsync-dev-password"
export FONTSYNC_ADMIN_EMAIL="${FONTSYNC_DEV_EMAIL:-dev@example.com}"
if is_loopback "$host"; then
  export FONTSYNC_ADMIN_PASSWORD="${FONTSYNC_DEV_PASSWORD:-$dev_password_default}"
elif [ "${FONTSYNC_DEV_PASSWORD:-}" = "$dev_password_default" ]; then
  echo "ERREUR : HOST=$host expose le serveur hors de cette machine avec le mot" >&2
  echo "de passe public « $dev_password_default ». Retirer FONTSYNC_DEV_PASSWORD" >&2
  echo "(un mot de passe aléatoire sera généré) ou en fournir un autre." >&2
  exit 2
elif [ -z "${FONTSYNC_DEV_PASSWORD:-}" ]; then
  FONTSYNC_ADMIN_PASSWORD="$("$python_bin" -c 'import secrets; print(secrets.token_urlsafe(18))')"
  export FONTSYNC_ADMIN_PASSWORD
  echo "==> Serveur exposé sur $host : compte $FONTSYNC_ADMIN_EMAIL, mot de passe de cette session :"
  echo "    $FONTSYNC_ADMIN_PASSWORD"
else
  export FONTSYNC_ADMIN_PASSWORD="$FONTSYNC_DEV_PASSWORD"
fi

mkdir -p "$dev_root/server/fonts"

export DATABASE_URL="sqlite+aiosqlite:///$dev_root/server/fontsync.db"
export STORAGE_BACKEND="filesystem"
export FONT_STORAGE_PATH="$dev_root/server/fonts"

cd "$repo_root"

echo "==> Migrations (alembic upgrade head)"
"$python_bin" -m alembic upgrade head

# Hors loopback, une base .dev déjà remplie en loopback garde le mot de passe
# public : il est remplacé par celui de cette session (les sessions existantes
# sont révoquées ; reconnecter un profil : `run-agent.sh A login`).
if ! is_loopback "$host"; then
  "$python_bin" - "$FONTSYNC_ADMIN_EMAIL" "$dev_password_default" <<'PY'
import asyncio
import os
import sys

from backend.database import async_session
from backend.services.accounts import (
    get_user_by_email,
    hash_password,
    revoke_user_sessions,
    verify_password,
)


async def main(email: str, public: str) -> None:
    async with async_session() as db:
        user = await get_user_by_email(db, email)
        if user is None or not await verify_password(user.password_hash, public):
            return
        user.password_hash = await hash_password(os.environ["FONTSYNC_ADMIN_PASSWORD"])
        await revoke_user_sessions(db, user.id)
        await db.commit()
        print(f"==> Mot de passe public de {email} remplacé par celui de cette session.")


asyncio.run(main(sys.argv[1], sys.argv[2]))
PY
fi

echo "==> uvicorn sur http://$host:$port  (db=$DATABASE_URL)"
exec "$python_bin" -m uvicorn backend.main:app --reload --host "$host" --port "$port"
