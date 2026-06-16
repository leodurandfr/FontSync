#!/usr/bin/env bash
#
# Lance l'agent FontSync sous un « profil » de device isolé, pour simuler
# plusieurs machines sur un seul Mac (cf. DEVELOPMENT.md).
#
# Chaque profil possède son propre état (équivalent ~/.fontsync) et son propre
# dossier de fonts, sous $FONTSYNC_DEV_ROOT (défaut : .dev/ à la racine du repo).
# Ainsi « device A » et « device B » sont deux identités distinctes côté serveur,
# avec des jeux de fonts séparés, sans jamais toucher le vrai ~/Library/Fonts.
#
# Usage :
#   scripts/dev/run-agent.sh <profil> <commande agent...>
#     ex : scripts/dev/run-agent.sh A sync
#          scripts/dev/run-agent.sh B sync
#          scripts/dev/run-agent.sh B listen
#
# Variables d'env utiles :
#   FONTSYNC_DEV_ROOT    racine des profils (défaut : <repo>/.dev)
#   FONTSYNC_SERVER_URL  serveur ciblé      (défaut : http://localhost:8080)

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <profil> <commande agent...>" >&2
  echo "  ex : $0 A sync   |   $0 B listen" >&2
  exit 2
fi

profile="$1"
shift

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
profile_dir="$dev_root/$profile"
profile_fonts="$profile_dir/fonts"

mkdir -p "$profile_fonts"

# Python : venv du repo si présent, sinon python3 du système.
python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

# Isolation complète du device simulé.
export FONTSYNC_HOME="$profile_dir"            # config + cache de hash + disabled/
export FONTSYNC_FONTS_DIR="$profile_fonts"     # cible d'installation (= dossier du device)
export FONTSYNC_DISCOVERY="directories"        # scan du dossier isolé, pas Core Text
export FONTSYNC_HOSTNAME="${FONTSYNC_HOSTNAME:-mac-dev-$profile}"   # clé d'upsert distincte
export FONTSYNC_DEVICE_NAME="${FONTSYNC_DEVICE_NAME:-Dev $profile}"

# Config minimale écrite une fois : serveur local + dossier isolé,
# auto_pull/push activés pour que la démo bidirectionnelle fonctionne.
config="$profile_dir/config.yaml"
if [ ! -f "$config" ]; then
  cat > "$config" <<YAML
server:
  url: ${FONTSYNC_SERVER_URL:-http://localhost:8080}
  device_token: null
  device_id: null
scan:
  directories:
    - $profile_fonts
  ignore_patterns:
    - '.*'
sync:
  auto_push: true
  auto_pull: true
YAML
  chmod 600 "$config"
fi

echo "[dev] profil=$profile  home=$profile_dir  fonts=$profile_fonts" >&2
cd "$repo_root"
exec "$python_bin" -m agent "$@"
