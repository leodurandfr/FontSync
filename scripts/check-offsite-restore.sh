#!/usr/bin/env bash
# check-offsite-restore.sh <dossier restauré> [nombre de polices vivantes attendu]
#
# Contrôle reproductible d'une restauration d'essai depuis la copie HORS SITE
# des sauvegardes (audit H-01, P1-2f). À lancer sur un Mac, sur le dossier que
# Hyper Backup (ou rclone) a restauré « vers un autre emplacement » puis copié
# ici. Lecture seule : rien n'est écrit dans le dossier.
#
# Vérifie :
#   - au moins un instantané SQLite (*.db) ; le plus récent est contrôlé ;
#   - PRAGMA integrity_check = ok (copie de travail : la restauration n'est
#     jamais ouverte en écriture, même par SQLite) ;
#   - une révision Alembic et des polices vivantes ; si un nombre attendu est
#     donné (celui de /api/stats en prod), un écart de plus de 1 % échoue ;
#   - le miroir des fichiers de polices, s'il est restauré : au moins autant
#     de fichiers que de polices vivantes non purgées.
# Code de sortie : 0 si tout passe, 1 sinon.
set -euo pipefail

dir=${1:?usage : check-offsite-restore.sh <dossier restauré> [polices vivantes attendues]}
expected=${2:-}
fail=0
ok() { printf 'OK   %s\n' "$1"; }
ko() { printf 'KO   %s\n' "$1"; fail=1; }

[[ -d "$dir" ]] || { ko "dossier introuvable : $dir"; exit 1; }

# Le plus récent sans `xargs ls -t` : sans fichier, GNU xargs lancerait quand
# même `ls -t` sur le dossier courant.
latest=""
while IFS= read -r -d '' f; do
  if [[ -z "$latest" || "$f" -nt "$latest" ]]; then latest=$f; fi
done < <(find "$dir" -type f -name '*.db' -print0 2>/dev/null)
if [[ -z "$latest" ]]; then
  ko "aucun instantané *.db sous $dir"
  exit 1
fi
ok "instantané le plus récent : ${latest#"$dir"/}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp "$latest" "$work/check.db"

integrity=$(sqlite3 "$work/check.db" 'PRAGMA integrity_check;' 2>&1 | head -n 1 || true)
[[ "$integrity" == ok ]] && ok "integrity_check = ok" || ko "integrity_check : $integrity"

revision=$(sqlite3 "$work/check.db" 'SELECT version_num FROM alembic_version;' 2>/dev/null || true)
[[ -n "$revision" ]] && ok "révision Alembic : $revision" || ko "pas de révision Alembic"

live=$(sqlite3 "$work/check.db" 'SELECT count(*) FROM fonts WHERE deleted_at IS NULL;' 2>/dev/null || echo 0)
stored=$(sqlite3 "$work/check.db" 'SELECT count(*) FROM fonts WHERE purged_at IS NULL;' 2>/dev/null || echo 0)
if (( live > 0 )); then ok "polices vivantes : $live"; else ko "aucune police vivante"; fi

if [[ -n "$expected" ]]; then
  diff=$(( live > expected ? live - expected : expected - live ))
  if (( diff * 100 <= expected )); then
    ok "écart avec la prod : $diff (attendu $expected)"
  else
    ko "écart avec la prod : $diff sur $expected (> 1 %)"
  fi
fi

mirror=$(find "$dir" -type f \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.ttc' -o -iname '*.woff' -o -iname '*.woff2' \) 2>/dev/null | wc -l | tr -d ' ')
if (( mirror == 0 )); then
  ko "miroir des fichiers de polices absent de la restauration"
elif (( mirror >= stored )); then
  ok "miroir : $mirror fichiers (≥ $stored polices stockées)"
else
  ko "miroir incomplet : $mirror fichiers pour $stored polices stockées"
fi

exit "$fail"
