#!/usr/bin/env bash
#
# Installe / désinstalle les LaunchAgents de l'agent FontSync (macOS).
#
# Deux jobs (cf. PLAN.md B8 / SPECS.md §6.10) :
#   - com.fontsync.sync   : commande `sync` déclenchée (WatchPaths + StartInterval + RunAtLoad)
#   - com.fontsync.listen : process SSE long-vécu (KeepAlive + RunAtLoad)
#
# Les gabarits *.plist (jetons @...@) sont matérialisés dans
# ~/Library/LaunchAgents, puis chargés via `launchctl bootstrap`.
#
# Usage :
#   ./install.sh install     # génère les plists et charge les jobs
#   ./install.sh uninstall   # décharge les jobs et supprime les plists
#   ./install.sh status      # état des jobs
#
# Le Python utilisé est, par ordre de priorité : $FONTSYNC_PYTHON,
# le venv du repo (.venv/bin/python), sinon `python3` du PATH.

set -euo pipefail

# --- Chemins ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/FontSync"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

LABELS=(com.fontsync.sync com.fontsync.listen)

# --- Couleurs --------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
log() { echo -e "${GREEN}[fontsync]${NC} $1"; }
warn() { echo -e "${YELLOW}[fontsync]${NC} $1"; }
err() {
    echo -e "${RED}[fontsync]${NC} $1" >&2
    exit 1
}

[ "$(uname)" = "Darwin" ] || err "Ces LaunchAgents sont spécifiques à macOS."

# --- Résolution du Python --------------------------------------------------
resolve_python() {
    if [ -n "${FONTSYNC_PYTHON:-}" ]; then
        echo "$FONTSYNC_PYTHON"
    elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        echo "$REPO_ROOT/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    else
        err "Aucun interpréteur Python trouvé (ni FONTSYNC_PYTHON, ni .venv, ni python3)."
    fi
}

bootout_one() {
    # Décharge un job s'il est présent ; ignore l'absence.
    launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
}

do_install() {
    local python
    python="$(resolve_python)"
    log "Python      : $python"
    log "Repo        : $REPO_ROOT"
    log "LaunchAgents: $LAUNCH_AGENTS_DIR"

    "$python" -c 'import agent' >/dev/null 2>&1 ||
        warn "Le module 'agent' n'est pas importable par ce Python — vérifier les dépendances (agent/requirements.txt)."

    mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

    for label in "${LABELS[@]}"; do
        local template="$SCRIPT_DIR/$label.plist"
        local target="$LAUNCH_AGENTS_DIR/$label.plist"
        [ -f "$template" ] || err "Gabarit introuvable : $template"

        sed -e "s|@PYTHON@|$python|g" \
            -e "s|@WORKDIR@|$REPO_ROOT|g" \
            -e "s|@HOME@|$HOME|g" \
            -e "s|@LOGDIR@|$LOG_DIR|g" \
            "$template" >"$target"

        plutil -lint "$target" >/dev/null || err "plist invalide après substitution : $target"

        bootout_one "$label"
        launchctl bootstrap "$DOMAIN" "$target"
        log "Chargé : $label"
    done

    # Un premier sync immédiat (utile à la 1re installation).
    launchctl kickstart "$DOMAIN/com.fontsync.sync" 2>/dev/null || true
    log "Installation terminée. Logs : $LOG_DIR"
}

do_uninstall() {
    for label in "${LABELS[@]}"; do
        bootout_one "$label"
        rm -f "$LAUNCH_AGENTS_DIR/$label.plist"
        log "Déchargé et supprimé : $label"
    done
    warn "Logs conservés dans $LOG_DIR (à supprimer manuellement si besoin)."
}

do_status() {
    for label in "${LABELS[@]}"; do
        if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
            log "$label : chargé"
        else
            warn "$label : absent"
        fi
    done
}

case "${1:-}" in
install) do_install ;;
uninstall) do_uninstall ;;
status) do_status ;;
*)
    echo "Usage: $0 {install|uninstall|status}" >&2
    exit 2
    ;;
esac
