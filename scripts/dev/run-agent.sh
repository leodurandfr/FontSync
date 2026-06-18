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
#   scripts/dev/run-agent.sh [profil] <commande agent...>
#     ex : scripts/dev/run-agent.sh sync        (profil par défaut)
#          scripts/dev/run-agent.sh listen      (profil par défaut)
#          scripts/dev/run-agent.sh A sync      (profil explicite)
#          scripts/dev/run-agent.sh B listen
#
# Le profil est optionnel : s'il est omis (1er argument = une commande agent
# connue), on utilise FONTSYNC_PROFILE (défaut : « A »). Indiquer un profil
# explicite reste nécessaire pour simuler plusieurs devices sur un seul Mac.
#
# Variables d'env utiles :
#   FONTSYNC_DEV_ROOT    racine des profils (défaut : <repo>/.dev)
#   FONTSYNC_SERVER_URL  serveur ciblé      (défaut : http://localhost:8080)
#   FONTSYNC_PROFILE     profil par défaut quand il est omis (défaut : A)
#   FONTSYNC_TOKEN       token d'instance partagé (= côté serveur) ; injecté
#                        dans la config du profil (défaut : null = pas d'auth)

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 [profil] <commande agent...>" >&2
  echo "  ex : $0 sync   |   $0 A listen" >&2
  exit 2
fi

# Profil optionnel : si le 1er argument est une commande agent connue, on
# n'attend pas de profil et on retombe sur FONTSYNC_PROFILE (défaut « A »).
case "$1" in
  sync | listen | setup | teardown | status)
    profile="${FONTSYNC_PROFILE:-A}"
    ;;
  *)
    profile="$1"
    shift
    ;;
esac

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
  token: ${FONTSYNC_TOKEN:-null}
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
