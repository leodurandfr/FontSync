#!/usr/bin/env bash
#
# Restaure la base FontSync depuis un instantané de /backups (runbook :
# docs/INSTALL-NAS.md §5, « Restore from /backups » et « Roll back an update »).
#
# À lancer sur l'hôte Docker (le NAS), en root, dans le dossier du compose :
#   sudo scripts/restore-from-backup.sh <instantané.db>
#   sudo COMPOSE_FILE=autre.yml scripts/restore-from-backup.sh <instantané.db>
#     ex. sudo scripts/restore-from-backup.sh fontsync-20261112-030000.db
#         sudo scripts/restore-from-backup.sh pre-migrate-a43134c85b44-20261112-194615.db
#
# Le compose doit d'abord pointer sur une image qui contient l'outil de
# restauration (celle de ce dépôt ou plus récente) : il sert aux étapes 1 et 3.
# Pour un RETOUR ARRIÈRE d'image, épingler l'image précédente à l'étape 4,
# juste avant le redémarrage (le script la montre avant de démarrer).
#
# Variables : COMPOSE_FILE (défaut docker-compose.nas.yml), SERVICE (défaut
# fontsync), ASSUME_YES=1 (répétition locale uniquement : répond « oui » à tout).
#
# Rien n'est supprimé : la base remplacée et ses -wal/-shm sont DÉPLACÉS dans
# /data/pre-restore-<date>/ avec une copie de l'instantané restauré ; les
# instantanés quotidiens existants sont mis à l'abri de la rotation dans
# /backups/pre-restore-<date>/ ; les polices du miroir sont recopiées sans
# rien retirer. Auto-pull et « Propager les suppressions » sont coupés sur
# tous les appareils DANS la base restaurée, avant qu'elle ne serve (réglages
# d'avant dans /backups/pre-restore-devices-<date>.json). Le serveur redémarre
# d'abord avec un jeton de maintenance (Macs refusés) pour l'audit.
#
# À chaque étape, l'état courant et la commande à taper ensuite sont écrits
# dans restore-state-<date>.txt (dossier du compose, lisible par root seul) et
# affichés si le script s'arrête.

set -euo pipefail
umask 077

# DSM retire /usr/local/bin (où vit docker) du PATH de sudo.
export PATH="/usr/local/bin:/usr/local/sbin:$PATH"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.nas.yml}"
SERVICE="${SERVICE:-fontsync}"
snapshot="${1:-}"
stage=start
maint=""

die() { echo "ERREUR : $*" >&2; exit 1; }
say() { printf '\n==> %s\n' "$*"; }
confirm() {
  if [ "${ASSUME_YES:-}" = 1 ]; then echo "$1 [oui] (ASSUME_YES)"; return 0; fi
  local answer
  read -r -p "$1 [oui/N] " answer
  [ "$answer" = oui ] || { echo "Abandon à votre demande."; exit 1; }
}
dc() { docker compose -f "$COMPOSE_FILE" "$@"; }
# Appel dans le conteneur ; le jeton passe par le NOM de variable (-e VAR),
# jamais en clair dans la ligne de commande (visible dans `ps`).
in_container() { # in_container <jeton|""> <code python>
  RESTORE_TOKEN="$1" dc exec -T -e RESTORE_TOKEN "$SERVICE" python -c "$2"
}
healthy() {
  in_container "" "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
    >/dev/null 2>&1
}
wait_healthy() {
  local i
  for i in $(seq 1 150); do
    healthy && return 0
    [ $((i % 15)) -eq 0 ] && echo "    … toujours en démarrage ($((i * 2)) s)"
    sleep 2
  done
  return 1
}
# Code HTTP d'un GET authentifié (jeton fourni, ou celui du conteneur si vide).
api_status() {
  in_container "$1" "
import os, urllib.error, urllib.request
token = os.environ.get('RESTORE_TOKEN') or os.environ['FONTSYNC_TOKEN']
req = urllib.request.Request('http://127.0.0.1:8000/api/devices', headers={'Authorization': 'Bearer ' + token})
try:
    print(urllib.request.urlopen(req, timeout=10).status)
except urllib.error.HTTPError as error:
    print(error.code)
" 2>/dev/null || echo "?"
}

state_text() {
  local DC="sudo $DOCKER compose -f $COMPOSE_ABS"
  local MAINT_UP="sudo env FONTSYNC_TOKEN=$maint $DOCKER compose -f $COMPOSE_ABS up -d $SERVICE"
  echo "État de la restauration FontSync ($snapshot) — étape « $stage »"
  case "$stage" in
    start)
      echo "  Rien n'a changé : le serveur tourne comme avant." ;;
    stopping | down)
      echo "  Serveur arrêté (ou arrêt partiel), base NON restaurée (inchangée)."
      echo "  Pour repartir comme avant :  $DC up -d" ;;
    restoring)
      echo "  Restauration interrompue : état à vérifier AVANT tout démarrage."
      echo "  Si /data contient un pre-restore-$stamp* avec fontsync.db, la base est restaurée"
      echo "  (réglages des appareils déjà coupés dans la base restaurée) ; sinon elle est inchangée."
      echo "  Voir :  $DC run --rm --no-deps --entrypoint ls $SERVICE -la /data" ;;
    uncertain)
      echo "  ÉTAT INCERTAIN : la remise en place a échoué. NE PAS démarrer le serveur."
      echo "  Les fichiers d'origine sont dans /data/pre-restore-$stamp*/ (volume db)."
      echo "  Voir :  $DC run --rm --no-deps --entrypoint ls $SERVICE -laR /data" ;;
    restored)
      echo "  Serveur ARRÊTÉ, base RESTAURÉE ; auto-pull et propagation coupés dans la base."
      echo "  Pour auditer avant que les Macs ne se reconnectent (jeton de maintenance) :"
      echo "    $MAINT_UP"
      echo "  puis, l'audit fait :  $DC up -d"
      echo "  (Démarrer directement avec $DC up -d ne réinstalle ni ne propage rien, mais"
      echo "  les Macs se reconnectent avant l'audit.)" ;;
    starting)
      echo "  Serveur en cours de démarrage avec le jeton de maintenance (il migre peut-être"
      echo "  la base, ou redémarre en boucle). Jeton : $maint"
      echo "  Journal :  $DC logs -f $SERVICE      Arrêter :  $DC stop $SERVICE"
      echo "  Une fois prêt et l'audit fait :  $DC up -d" ;;
    maintenance)
      echo "  Serveur en JETON DE MAINTENANCE (Macs refusés), réglages des appareils coupés."
      echo "  Jeton : $maint"
      echo "  L'audit fait :  $DC up -d" ;;
    finishing)
      echo "  Retour au vrai jeton lancé ; vérification non terminée."
      echo "  Voir :  $DC ps   et   $DC logs $SERVICE ;  relancer au besoin :  $DC up -d" ;;
    done)
      echo "  Terminé : vrai jeton actif, jeton de maintenance refusé." ;;
  esac
}
set_stage() {
  stage="$1"
  state_text >"$STATE_FILE"
}
on_exit() {
  local code=$?
  [ "$stage" = done ] && return
  echo
  echo "---- Arrêt du script (code $code). État écrit dans $STATE_FILE :"
  state_text | sed 's/^/    /'
}

[ -n "$snapshot" ] || die "usage : $0 <instantané.db> (nom d'un fichier de /backups)"
case "$snapshot" in */* | .*) die "donner le NOM du fichier dans /backups, pas un chemin" ;; esac
[ -f "$COMPOSE_FILE" ] || die "$COMPOSE_FILE introuvable : lancer depuis le dossier du compose"
DOCKER="$(command -v docker)" || die "docker introuvable dans le PATH ($PATH)"
COMPOSE_ABS="$(cd "$(dirname "$COMPOSE_FILE")" && pwd)/$(basename "$COMPOSE_FILE")"
maint="$(openssl rand -hex 24 2>/dev/null || od -An -tx1 -N24 /dev/urandom | tr -d ' \n')"
[ "${#maint}" -eq 48 ] || die "impossible de générer un jeton de maintenance"
stamp="$(date -u +%Y%m%d-%H%M%S)"
devices_file="pre-restore-devices-$stamp.json"
STATE_FILE="$(dirname "$COMPOSE_ABS")/restore-state-$stamp.txt"
trap on_exit EXIT
set_stage start

cat <<EOF
Restauration FontSync
  compose    : $COMPOSE_ABS (service $SERVICE)
  instantané : /backups/$snapshot
  état écrit : $STATE_FILE
Étapes : 1 vérifications → 2 arrêt du serveur → 3 base mise de côté (rien
supprimé), instantané posé avec les réglages des appareils coupés, polices
recopiées → 4 redémarrage avec un jeton de maintenance (Macs refusés) →
5 audit par vous → 6 retour au vrai jeton.
EOF

say "1/6 Vérifications (serveur toujours en marche)"
current_image="$(dc config --images "$SERVICE")" || die "docker compose config a échoué"
echo "    image actuelle : $current_image"
rc=0
dc run --rm --no-deps -T --entrypoint python "$SERVICE" -c "import backend.maintenance.restore" \
  >/dev/null 2>&1 || rc=$?
[ "$rc" -eq 0 ] || die "l'image actuelle n'a pas l'outil de restauration (ou docker compose a échoué, code $rc). Pointer d'abord le compose sur une image récente, ou suivre la procédure à la main (docs/INSTALL-NAS.md §5, By hand)."
dc run --rm --no-deps -T --entrypoint python "$SERVICE" \
  -m backend.maintenance.restore --check "/backups/$snapshot" \
  || die "instantané refusé (voir ci-dessus) : rien n'a été touché"

confirm "2/6 Arrêter le serveur (docker compose down, volumes conservés) ?"
set_stage stopping
dc down
set_stage down

say "3/6 Restauration"
set_stage restoring
rc=0
dc run --rm --no-deps -T --entrypoint python "$SERVICE" \
  -m backend.maintenance.restore "/backups/$snapshot" \
  --protect-backups /backups --devices-json "/backups/$devices_file" \
  --fonts-from /backups/fonts || rc=$?
case "$rc" in
  0) set_stage restored ;;
  3) set_stage restored; echo "    ATTENTION : une étape annexe a échoué (voir ci-dessus) ; la base EST restaurée." ;;
  1 | 2) set_stage down; die "restauration refusée (code $rc) : base inchangée" ;;
  *) set_stage uncertain; die "restauration interrompue ou incertaine (code $rc)" ;;
esac

say "4/6 Redémarrage avec un jeton de maintenance"
cat <<EOF
    Retour arrière d'image ? Épinglez MAINTENANT l'image précédente
    (image: …:sha-<court>) dans $COMPOSE_ABS, puis répondez.
EOF
confirm "Compose prêt ?"
start_image="$(dc config --images "$SERVICE")" || die "docker compose config a échoué"
echo "    image qui va démarrer : $start_image"
echo "    Les Macs vont recevoir 401 (« Token invalide ») : c'est voulu, ne saisissez"
echo "    pas le jeton de maintenance dans l'app."
confirm "Démarrer cette image avec le jeton de maintenance ?"
set_stage starting
FONTSYNC_TOKEN="$maint" dc up -d "$SERVICE"
wait_healthy || die "le serveur ne répond pas (toujours en démarrage, ou en échec)"
if [ "$(api_status "$maint")" != 200 ]; then
  dc stop "$SERVICE" || true
  set_stage restored
  die "le jeton de maintenance n'est pas pris en compte (compose sans \${FONTSYNC_TOKEN} ?) : serveur arrêté par sécurité"
fi
set_stage maintenance
echo "    serveur prêt, jeton de maintenance actif."

say "5/6 Audit (à faire par vous)"
cat <<EOF
    Ouvrez l'interface avec le jeton de maintenance (aussi dans $STATE_FILE) :
      $maint
    - Auto-pull et « Propager les suppressions » sont coupés sur tous les
      appareils (valeurs d'avant : /backups/$devices_file).
    - Les polices supprimées APRÈS l'instantané sont redevenues actives. Celles
      que les Macs avaient retirées (supprimées sur un Mac, ou dans l'interface
      avec « Propager les suppressions ») repartiront en corbeille au premier
      sync de chaque Mac — en quarantaine si elles sont nombreuses. Après une
      suppression massive par erreur : restaurez-les depuis la corbeille APRÈS
      ce premier sync, puis seulement réactivez auto-pull pour les réinstaller.
    - Une police supprimée dans l'interface SANS propagation reste active
      (les Macs l'ont encore) : à remettre en corbeille si besoin.
    - Les polices envoyées après l'instantané ne sont plus dans la bibliothèque
      (leurs fichiers restent dans /fonts) : un Mac qui les a les renverra.
EOF
confirm "Audit terminé : revenir au VRAI jeton (les Macs se reconnectent) ?"

say "6/6 Retour au vrai jeton (tous les services du compose)"
set_stage finishing
dc up -d
wait_healthy || die "le serveur ne répond pas après le retour au vrai jeton"
[ "$(api_status "")" = 200 ] || die "le vrai jeton ne répond pas"
[ "$(api_status "$maint")" = 401 ] || die "le jeton de maintenance est encore accepté"
set_stage done
cat <<EOF
    Fait : vrai jeton actif, jeton de maintenance refusé.
    Laissez chaque Mac synchroniser une fois, regardez la corbeille (et la
    quarantaine), restaurez ce qui doit l'être, puis seulement réactivez
    auto-pull / propagation appareil par appareil dans Réglages → Appareils
    (valeurs d'avant : /backups/$devices_file).
    Mis de côté (rien supprimé) : /data/pre-restore-*/ (ancienne base, copie de
    l'instantané restauré) et /backups/pre-restore-*/ (instantanés quotidiens).
EOF
