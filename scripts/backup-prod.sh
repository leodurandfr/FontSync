#!/usr/bin/env bash
#
# Sauvegarde de la PROD (à exécuter SUR le NAS, en root).
#
# Pourquoi ce script existe : la base tourne en `journal_mode=WAL`. Copier le
# seul fichier `.db` produit une sauvegarde **invalide** — les dernières
# transactions vivent dans le `-wal` qui l'accompagne, et un `.db` restauré
# sans lui rejoue des frames étrangères. La seule copie correcte d'une base
# SQLite vivante passe par l'API `sqlite3.Connection.backup`, depuis un process
# qui parle à la base : donc depuis l'intérieur du conteneur.
#
# Deux moitiés, deux régimes :
#
#   - la BASE — instantané horodaté, avec `PRAGMA integrity_check` avant de
#     sortir le fichier du conteneur, et rotation (`KEEP` copies) ;
#   - les BLOBS — miroir incrémental par rsync. Les fichiers sont nommés par
#     empreinte et jamais réécrits : après la première passe, une sauvegarde ne
#     coûte que les nouveautés. On ne supprime jamais côté miroir (pas de
#     `--delete`) : un vidage de corbeille en prod ne doit pas se propager à la
#     sauvegarde, c'est tout l'intérêt d'en avoir une.
#
# Usage, SUR le NAS :
#   sudo /volume1/docker/fontsync/backup-prod.sh
#   sudo /volume1/docker/fontsync/backup-prod.sh --db-only
#
# Usage, DEPUIS le Mac (sans rien installer sur le NAS) :
#   ssh -p 93 Leo@192.168.1.140 'sudo bash -s' < scripts/backup-prod.sh
#
# Installation du cron (une fois, sur le NAS) — cf. le bas de ce fichier.

set -euo pipefail

# --- Config (surchargeable par variables d'env) ---
OUT_DIR="${OUT_DIR:-/volume1/docker/fontsync/backups}"
CONTAINER="${CONTAINER:-}"          # sinon : découverte par nom (voir plus bas)
CONTAINER_MATCH="${CONTAINER_MATCH:-fontsync}"
KEEP="${KEEP:-14}"                  # instantanés de base conservés
DB_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --db-only) DB_ONLY=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Argument inconnu : $arg" >&2; exit 2 ;;
  esac
done

log() { printf '[backup] %s\n' "$*"; }
die() { printf '[backup] ERREUR : %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker introuvable — ce script tourne sur le NAS."

# --- Le conteneur ---
#
# Découverte par nom plutôt que par `docker compose` : le compose de prod n'est
# pas dans ce dépôt, et Container Manager peut l'avoir démarré autrement. On
# exige une correspondance UNIQUE — sauvegarder la mauvaise base serait pire
# que de ne pas sauvegarder.
if [[ -z "$CONTAINER" ]]; then
  mapfile -t found < <(docker ps --filter "name=$CONTAINER_MATCH" --format '{{.Names}}')
  (( ${#found[@]} == 1 )) || die \
    "${#found[@]} conteneur(s) correspondent à « $CONTAINER_MATCH » : ${found[*]:-aucun}. Précisez CONTAINER=…"
  CONTAINER="${found[0]}"
fi
log "conteneur : $CONTAINER"

mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

# --- 1. La base, par l'API de sauvegarde en ligne ---
#
# Écrit dans /tmp DU CONTENEUR (couche éphémère), jamais dans /data : une
# sauvegarde ne doit pas grossir le volume qu'elle sauvegarde.
TMP_IN_CONTAINER="/tmp/fontsync-backup-$STAMP.db"

log "instantané de la base (sqlite3.backup + integrity_check)…"
docker exec -i "$CONTAINER" python - "$TMP_IN_CONTAINER" <<'PY'
import sqlite3
import sys

from sqlalchemy.engine import make_url

from backend.config import settings

dest = sys.argv[1]
url = make_url(settings.database_url)
if url.get_backend_name() != "sqlite":
    raise SystemExit(f"Base non-SQLite ({url.get_backend_name()}) : ce script ne sait pas la sauvegarder.")

# Lecture seule sur la source : une sauvegarde ne prend jamais de verrou
# d'écriture sur la prod. `backup()` gère le WAL, c'est tout son intérêt.
src = sqlite3.connect(f"file:{url.database}?mode=ro", uri=True)
dst = sqlite3.connect(dest)
try:
    src.backup(dst)
finally:
    src.close()

try:
    verdict = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if verdict != "ok":
        raise SystemExit(f"integrity_check sur la copie : {verdict}")
    fonts, tombs, devices = dst.execute(
        "SELECT (SELECT COUNT(*) FROM fonts WHERE deleted_at IS NULL),"
        "       (SELECT COUNT(*) FROM fonts WHERE deleted_at IS NOT NULL),"
        "       (SELECT COUNT(*) FROM devices)"
    ).fetchone()
finally:
    dst.close()

print(f"copie saine : {fonts} police(s) en bibliothèque, {tombs} en corbeille, {devices} appareil(s)")
PY

docker cp "$CONTAINER:$TMP_IN_CONTAINER" "$OUT_DIR/fontsync-$STAMP.db"
docker exec "$CONTAINER" rm -f "$TMP_IN_CONTAINER"
log "base sauvegardée : $OUT_DIR/fontsync-$STAMP.db ($(du -h "$OUT_DIR/fontsync-$STAMP.db" | cut -f1))"

# Rotation. `ls -t` puis on jette la queue : les instantanés sont horodatés,
# l'ordre lexicographique et l'ordre chronologique coïncident.
mapfile -t old < <(ls -1t "$OUT_DIR"/fontsync-*.db 2>/dev/null | tail -n "+$((KEEP + 1))")
if (( ${#old[@]} )); then
  rm -f -- "${old[@]}"
  log "rotation : ${#old[@]} instantané(s) au-delà de $KEEP retiré(s)"
fi

# --- 2. Les blobs, en miroir incrémental ---
if (( DB_ONLY )); then
  log "--db-only : miroir des polices non touché."
  exit 0
fi

command -v rsync >/dev/null || die "rsync introuvable — relancez avec --db-only."

# Le point de montage hôte du volume monté sur /data/fonts. Le demander à Docker
# plutôt que le coder en dur : le nom du volume dépend du compose de prod.
BLOB_SRC="$(docker inspect -f \
  '{{range .Mounts}}{{if eq .Destination "/data/fonts"}}{{.Source}}{{end}}{{end}}' \
  "$CONTAINER")"
[[ -n "$BLOB_SRC" && -d "$BLOB_SRC" ]] || die \
  "point de montage de /data/fonts introuvable (« $BLOB_SRC »)."

log "miroir des polices : $BLOB_SRC → $OUT_DIR/fonts/"
mkdir -p "$OUT_DIR/fonts"
# Pas de --delete : le miroir ne perd jamais un fichier que la prod a purgé.
rsync -a --stats "$BLOB_SRC/" "$OUT_DIR/fonts/" | tail -n 4

log "terminé."

# --- Cron, sur le NAS (une fois) ---
#
#   scp -P 93 scripts/backup-prod.sh Leo@192.168.1.140:/volume1/docker/fontsync/
#   ssh -p 93 Leo@192.168.1.140 'sudo chmod +x /volume1/docker/fontsync/backup-prod.sh'
#
# Puis, en root (`sudo crontab -e`, ou DSM → Planificateur de tâches, qui
# survit mieux aux mises à jour de DSM) :
#
#   0 3 * * *  /volume1/docker/fontsync/backup-prod.sh --db-only >> /volume1/docker/fontsync/backups/backup.log 2>&1
#   0 4 * * 0  /volume1/docker/fontsync/backup-prod.sh          >> /volume1/docker/fontsync/backups/backup.log 2>&1
#
# Quotidien pour la base (quelques Mo, c'est elle qui porte l'état), et
# hebdomadaire pour le miroir des polices (write-once : rien ne se perd entre
# deux passes, seules les nouveautés arrivent).
#
# Restauration : `docker compose down`, puis poser le `.db` choisi à la place de
# `fontsync.db` dans le volume — en SUPPRIMANT d'abord `fontsync.db-wal` et
# `fontsync.db-shm`, sinon des frames étrangères se rejouent par-dessus.
# Garder les agents éteints le temps d'auditer la corbeille : restaurer une base
# antérieure réactive des polices supprimées depuis, et `auto_pull` les
# réinstalle sans qu'on l'ait demandé.
