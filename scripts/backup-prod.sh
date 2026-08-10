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
# Déposer le script, puis l'exécuter EN ROOT sur le NAS :
#
#   scp -P 93 scripts/backup-prod.sh Leo@192.168.1.140:/volume1/docker/fontsync/
#   ssh -p 93 Leo@192.168.1.140
#   sudo bash /volume1/docker/fontsync/backup-prod.sh --db-only
#
# Ne PAS tenter `ssh … 'sudo bash -s' < ce-fichier` : `sudo` demande un mot de
# passe sur ce NAS (vérifié), et avec le script sur l'entrée standard il n'y a
# pas de terminal pour le saisir — au mieux ça échoue, au pire sudo lit la
# première ligne du script comme mot de passe. Il faut que le fichier soit posé.
#
# Installation de la tâche planifiée (une fois) — cf. le bas de ce fichier.

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

# DSM n'expose pas /usr/local/bin aux shells non interactifs — le PATH d'un
# `ssh … 'commande'` se limite à /usr/bin:/bin:/usr/sbin:/sbin — et c'est
# précisément là que ContainerManager pose le binaire docker (vérifié sur le
# NAS : /usr/local/bin/docker → /var/packages/ContainerManager/…). Le PATH du
# cron DSM, lui, l'inclut déjà : cette ligne ne sert qu'au lancement manuel.
PATH="$PATH:/usr/local/bin:/usr/local/sbin"

command -v docker >/dev/null || die "docker introuvable — ce script tourne sur le NAS."

# Joignabilité du démon, testée AVANT la découverte du conteneur. Sans ce test,
# un `docker ps` refusé faute de droits rend une liste vide, et le script
# annonce « aucun conteneur ne correspond » — un diagnostic faux qui envoie
# chercher le problème du mauvais côté.
docker info >/dev/null 2>&1 || die \
  "démon Docker injoignable — ce script s'exécute en root (sudo bash <chemin>)."

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

# --- Planification, sur le NAS (une fois) ---
#
# **Par DSM → Panneau de configuration → Planificateur de tâches**, en tâche
# planifiée « Script défini par l'utilisateur », utilisateur **root**. Deux
# tâches :
#
#   quotidienne  03:00  bash /volume1/docker/fontsync/backup-prod.sh --db-only
#   hebdomadaire 04:00  bash /volume1/docker/fontsync/backup-prod.sh
#
# Quotidien pour la base (quelques Mo, c'est elle qui porte l'état), hebdomadaire
# pour le miroir des polices (write-once : rien ne se perd entre deux passes,
# seules les nouveautés arrivent).
#
# **Pas d'édition à la main de `/etc/crontab`.** DSM y matérialise ses propres
# tâches (`synoschedtask --run id=…`, vérifié sur ce NAS) et réécrit le fichier :
# une ligne ajoutée à la main disparaît sans bruit à la prochaine modification
# depuis l'interface ou à une mise à jour de DSM. Une sauvegarde qui cesse
# silencieusement est pire que pas de sauvegarde — on croit avoir un filet.
#
# Restauration : `docker compose down`, puis poser le `.db` choisi à la place de
# `fontsync.db` dans le volume — en SUPPRIMANT d'abord `fontsync.db-wal` et
# `fontsync.db-shm`, sinon des frames étrangères se rejouent par-dessus.
# Garder les agents éteints le temps d'auditer la corbeille : restaurer une base
# antérieure réactive des polices supprimées depuis, et `auto_pull` les
# réinstalle sans qu'on l'ait demandé.
