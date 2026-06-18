#!/bin/sh
# Entrypoint du conteneur FontSync.
#
# 1. S'assure que le dossier de la base SQLite (et le storage de polices)
#    existe — sinon SQLite échoue avec un cryptique « unable to open database
#    file » quand on lance sans monter de volume sur /data.
# 2. Applique les migrations Alembic AVANT de démarrer le serveur (P2.1,
#    PLAN-PUBLICATION.md) : sans ça, la base est vide au tout premier lancement
#    et désynchronisée après une mise à jour de l'image. `alembic upgrade head`
#    est idempotent — il ne fait rien si le schéma est déjà à jour.
set -e

echo "[entrypoint] Préparation des dossiers de données…"
python - <<'PY'
import os
from sqlalchemy.engine import make_url
from backend.config import settings

# Dossier de la base SQLite (no-op pour une URL non-SQLite, ex. Postgres futur).
url = make_url(settings.database_url)
if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
    os.makedirs(os.path.dirname(url.database) or ".", exist_ok=True)

# Dossier de stockage des polices (le storage le crée aussi à la 1re écriture).
if settings.storage_backend == "filesystem" and settings.font_storage_path:
    os.makedirs(settings.font_storage_path, exist_ok=True)
PY

echo "[entrypoint] Migrations de schéma (alembic upgrade head)…"
alembic upgrade head

echo "[entrypoint] Schéma à jour — démarrage : $*"
exec "$@"
