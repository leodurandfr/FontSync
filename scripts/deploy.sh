#!/usr/bin/env bash
set -euo pipefail

# === Configuration ===
NAS_USER="Leo"
NAS_HOST="192.168.1.140"
NAS_PORT="93"
REMOTE_DIR="/volume1/docker/fontsync"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.prod"
SSH_OPTS="-p $NAS_PORT"
DOCKER_PATH="/usr/local/bin"

# === Couleurs ===
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
err() { echo -e "${RED}[deploy]${NC} $1"; exit 1; }

nas_ssh() { ssh $SSH_OPTS "$NAS_USER@$NAS_HOST" "export PATH=$DOCKER_PATH:\$PATH && $1"; }
nas_sudo() { ssh $SSH_OPTS "$NAS_USER@$NAS_HOST" "export PATH=$DOCKER_PATH:\$PATH && sudo $1"; }

# === Vérifications locales ===
if [ ! -f "$ENV_FILE" ]; then
    err "$ENV_FILE introuvable. Copier .env.prod.example et remplir les valeurs."
fi

# === Build frontend localement ===
log "Build du frontend..."
(cd frontend && npm run build) || err "Échec du build frontend"

# === Sync des fichiers vers le NAS ===
log "Synchronisation des fichiers vers $NAS_HOST..."
tar czf - \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='.env' \
    --exclude='.env.prod' \
    --exclude='pg_data' \
    --exclude='.DS_Store' \
    --exclude='.smbdelete*' \
    --exclude='tests/fixtures/*.ttf' \
    --exclude='tests/fixtures/*.otf' \
    --exclude='tests/fixtures/*.woff' \
    --exclude='tests/fixtures/*.woff2' \
    . 2>/dev/null | nas_ssh "cd $REMOTE_DIR && tar xzf - 2>/dev/null"

# === Copier le .env.prod ===
log "Copie de $ENV_FILE..."
scp -O $SSH_OPTS "$ENV_FILE" "$NAS_USER@$NAS_HOST:$REMOTE_DIR/.env.prod"

# === Build & restart sur le NAS ===
log "Build et redémarrage des containers..."
nas_sudo "sh -c 'cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE --env-file .env.prod up -d --build'"

# === Migrations ===
log "Exécution des migrations Alembic..."
nas_sudo "sh -c 'cd $REMOTE_DIR && docker compose -f $COMPOSE_FILE exec fontsync alembic upgrade head'"

log "Déploiement terminé ! https://fontsync.leodurand.com"
