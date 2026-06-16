#!/usr/bin/env bash
#
# Wrapper rétro-compatible : la logique launchd vit désormais dans la CLI de
# l'agent (sous-commandes `setup`/`teardown`/`status`, cf. PLAN.md B10 et
# agent/launchd_setup.py). Ce script ne fait que les router pour ne pas casser
# les habitudes / la doc existante.
#
# Usage :
#   ./install.sh install     → fontsync-agent setup
#   ./install.sh uninstall   → fontsync-agent teardown
#   ./install.sh status      → fontsync-agent status
#
# Python utilisé, par priorité : $FONTSYNC_PYTHON, le venv du repo
# (.venv/bin/python), sinon `python3`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

resolve_python() {
    if [ -n "${FONTSYNC_PYTHON:-}" ]; then
        echo "$FONTSYNC_PYTHON"
    elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        echo "$REPO_ROOT/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    else
        echo "Aucun interpréteur Python trouvé." >&2
        exit 1
    fi
}

case "${1:-}" in
install) command="setup" ;;
uninstall) command="teardown" ;;
status) command="status" ;;
*)
    echo "Usage: $0 {install|uninstall|status}" >&2
    exit 2
    ;;
esac

PYTHON="$(resolve_python)"
exec env PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$REPO_ROOT" "$PYTHON" -m agent "$command"
