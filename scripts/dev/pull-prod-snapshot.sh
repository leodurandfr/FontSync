#!/usr/bin/env bash
#
# Snapshot de la PROD vers le serveur de DEV local — par REJEU API.
#
# Pourquoi pas une copie de fichiers ? La base SQLite et les blobs de fonts de la
# prod vivent dans des volumes Docker root-only sur le NAS (illisibles sans sudo).
# On passe donc par l'API : on liste /api/fonts sur la prod, on télécharge les
# blobs /file, et on les ré-ingère dans le serveur local via /api/fonts/upload.
#
#   - Côté prod : LECTURE SEULE (aucune écriture). Le token prod est lu dans le
#     .env du NAS et n'est JAMAIS exposé côté Mac (tout curl authentifié tourne
#     SUR le NAS via SSH).
#   - Côté local : ingestion dans la base de dev jetable (.dev/), zéro risque.
#
# Les blobs téléchargés sont conservés dans .dev/snapshot/fonts/ → ré-exécutions
# rapides (téléchargement sauté si déjà présent) et ré-ingestion offline possible.
#
# Usage :
#   scripts/dev/pull-prod-snapshot.sh                # ~300 fonts (échantillon aléatoire représentatif)
#   scripts/dev/pull-prod-snapshot.sh --count 500    # N fonts
#   scripts/dev/pull-prod-snapshot.sh --all          # toute la bibliothèque (2296)
#   scripts/dev/pull-prod-snapshot.sh --reupload     # ré-ingère .dev/snapshot/fonts/ sans retoucher le NAS
#
# Pré-requis : serveur local démarré (scripts/dev/up.sh ou run-server.sh) et
# clé SSH installée sur le NAS (ssh-copy-id -p 93 Leo@192.168.1.140).

set -euo pipefail

# --- Config (surchargeable par variables d'env) ---
NAS_USER="${NAS_USER:-Leo}"
NAS_HOST="${NAS_HOST:-192.168.1.140}"
NAS_PORT="${NAS_PORT:-93}"
NAS_ENV="${NAS_ENV:-/volume1/docker/fontsync/.env}"
PROD_API="${PROD_API:-http://localhost:8070}"          # vu DEPUIS le NAS
LOCAL_API="${LOCAL_API:-http://localhost:8080}"
LOCAL_TOKEN="${FONTSYNC_TOKEN:-fontsync-dev}"
BATCH="${BATCH:-25}"                                    # fonts par requête /upload

COUNT=300
MODE=sample        # sample | all | reupload

while [ $# -gt 0 ]; do
  case "$1" in
    --count) COUNT="$2"; MODE=sample; shift 2 ;;
    --all)   MODE=all; shift ;;
    --reupload) MODE=reupload; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "Argument inconnu : $1" >&2; exit 2 ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
snap_dir="$repo_root/.dev/snapshot/fonts"
mkdir -p "$snap_dir"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[snapshot]${NC} $1"; }
warn() { echo -e "${YELLOW}[snapshot]${NC} $1"; }
err()  { echo -e "${RED}[snapshot]${NC} $1" >&2; exit 1; }

# Multiplexage SSH : une seule connexion réutilisée pour tous les appels.
# -n : stdin depuis /dev/null, sinon ssh « avale » le stdin de la boucle
# `while read` du téléchargement et celle-ci ne s'exécute qu'une fois.
ssh_ctl="/tmp/fontsync-snapshot-%r@%h:%p"
SSH=(ssh -n -p "$NAS_PORT" -o BatchMode=yes -o ConnectTimeout=8
     -o ControlMaster=auto -o ControlPath="$ssh_ctl" -o ControlPersist=120)

# Exécute un snippet bash SUR le NAS, avec le token prod sourcé dans l'env
# (jamais imprimé). $1 = snippet.
nas() { "${SSH[@]}" "$NAS_USER@$NAS_HOST" "set -a; . '$NAS_ENV' 2>/dev/null; set +a; $1"; }

# --- 0. Serveur local joignable ? ---
if ! curl -fsS -m 5 "$LOCAL_API/health" >/dev/null 2>&1; then
  err "Serveur local injoignable sur $LOCAL_API — lance d'abord 'scripts/dev/up.sh' (ou run-server.sh)."
fi

# Ré-ingère le contenu d'un dossier de blobs vers le serveur local, par lots.
# $1 = dossier source.
upload_dir() {
  local dir="$1" total imported=0 duplicates=0 errors=0 done=0
  local -a files=() args=()
  while IFS= read -r -d '' f; do files+=("$f"); done \
    < <(find "$dir" -type f \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' \
        -o -iname '*.woff' -o -iname '*.woff2' \) -print0)
  total=${#files[@]}
  [ "$total" -gt 0 ] || err "Aucun fichier de font à ingérer dans $dir."
  log "Ingestion locale de $total fichiers (lots de $BATCH)…"

  local i=0
  while [ $i -lt $total ]; do
    args=()
    local j=0
    while [ $j -lt "$BATCH" ] && [ $i -lt $total ]; do
      args+=(-F "files=@${files[$i]}")
      i=$((i+1)); j=$((j+1))
    done
    local resp
    resp=$(curl -fsS -m 120 -H "Authorization: Bearer $LOCAL_TOKEN" \
                "${args[@]}" "$LOCAL_API/api/fonts/upload" 2>/dev/null) || {
      warn "Échec d'un lot d'upload (poursuite)."; continue; }
    # Cumule les compteurs renvoyés par FontUploadResponse.
    local _imp=0 _dup=0 _err=0
    if [ -n "$resp" ]; then
      read -r _imp _dup _err < <(printf '%s' "$resp" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(len(d["imported"]), len(d["duplicates"]), len(d["errors"]))
except Exception:
    print(0, 0, 0)
')
    fi
    imported=$((imported + _imp)); duplicates=$((duplicates + _dup)); errors=$((errors + _err))
    done=$i
    printf "\r  %d/%d  (importées:%d  doublons:%d  erreurs:%d)" "$done" "$total" "$imported" "$duplicates" "$errors"
  done
  echo
  log "Ingestion terminée — importées:$imported, doublons:$duplicates, erreurs:$errors"
}

if [ "$MODE" = reupload ]; then
  log "Mode --reupload : ré-ingestion de $snap_dir (le NAS n'est pas contacté)."
  upload_dir "$snap_dir"
  exit 0
fi

# --- 1. Liste des fonts depuis la prod (sur le NAS, token jamais exposé) ---
log "Connexion au NAS et récupération de la liste des fonts…"
list_file="$(mktemp)"
trap 'rm -f "$list_file"' EXIT
nas 'python3 - "'"$PROD_API"'" <<'\''PY'\''
import os, sys, json, urllib.request
base, tok = sys.argv[1], os.environ["FONTSYNC_TOKEN"]
def page(p):
    req = urllib.request.Request(f"{base}/api/fonts?per_page=200&page={p}",
                                 headers={"Authorization": f"Bearer {tok}"})
    return json.load(urllib.request.urlopen(req, timeout=30))
d = page(1); items = d["items"]
for p in range(2, d["pages"] + 1):
    items += page(p)["items"]
for f in items:
    print(f["id"] + "\t" + (f.get("originalFilename") or (f["id"] + "." + (f.get("fileFormat") or "ttf"))))
PY' > "$list_file"

avail=$(wc -l < "$list_file" | tr -d ' ')
[ "$avail" -gt 0 ] || err "Liste vide — vérifie le serveur prod et le token sur le NAS."
log "Prod : $avail fonts disponibles."

# --- 2. Sélection ---
sel_file="$(mktemp)"
trap 'rm -f "$list_file" "$sel_file"' EXIT
if [ "$MODE" = all ]; then
  cp "$list_file" "$sel_file"
  log "Sélection : TOUTE la bibliothèque ($avail)."
else
  # Échantillon aléatoire → proportionnel à la distribution réelle (familles,
  # classifications, formats), donc représentatif sans logique de quotas.
  # (perl shuffle : portable macOS/Linux, contrairement à `shuf`. Le head est
  # fait DANS perl pour éviter un SIGPIPE sous `set -o pipefail`.)
  perl -MList::Util=shuffle -e 'my $n=shift; my @l=shuffle(<>); $n=@l if $n>@l; print @l[0..$n-1];' \
    "$COUNT" "$list_file" > "$sel_file"
  log "Sélection : échantillon aléatoire de $(wc -l < "$sel_file" | tr -d ' ') / $avail."
fi

# --- 3. Téléchargement des blobs (résumable : saute ce qui est déjà là) ---
n=$(wc -l < "$sel_file" | tr -d ' '); i=0; skipped=0
log "Téléchargement vers $snap_dir …"
while IFS=$'\t' read -r id fn; do
  i=$((i+1))
  safe="${id:0:8}__$(printf '%s' "$fn" | tr '/ ' '__')"
  out="$snap_dir/$safe"
  if [ -s "$out" ]; then skipped=$((skipped+1)); else
    nas 'curl -fsS -m 60 -H "Authorization: Bearer $FONTSYNC_TOKEN" "'"$PROD_API"'/api/fonts/'"$id"'/file"' > "$out" \
      || { warn "Échec téléchargement $id ($fn)"; rm -f "$out"; }
  fi
  printf "\r  %d/%d  (déjà présents:%d)" "$i" "$n" "$skipped"
done < "$sel_file"
echo

# --- 4. Ré-ingestion locale ---
upload_dir "$snap_dir"

log "Terminé. Ouvre le frontend (http://localhost:8765) et colle le token : $LOCAL_TOKEN"
