#!/usr/bin/env bash
#
# preflight.sh — Répétition générale locale de la checklist E2E (tests/e2e/CHECKLIST.md).
#
# Monte, sur un SEUL Mac, un banc complet pour dérouler à blanc la logique
# réseau/serveur de la sync multi-machines AVANT le vrai test 2 Macs :
#
#   • serveur FontSync (FastAPI + SQLite jetable dans .dev/), exposé sur le LAN
#   • frontend Vite (UI web) — pour les scénarios upload / suppression / appareils
#   • 2 agents `listen` (profils isolés A et B = 2 devices distincts)
#
# Ce que ça NE couvre PAS (réservé au vrai 2ᵉ Mac, cf. CHECKLIST.md) :
#   • découverte Core Text réelle (ici : scan d'un dossier isolé)
#   • installation système dans ~/Library/Fonts
#   • déclenchement launchd (WatchPaths / StartInterval / KeepAlive)
# Ici, un push se provoque à la main (`run-agent.sh A sync`) ; le chemin réactif
# serveur → B (signal SSE → pull/install chez B) est, lui, bien exercé.
#
# Ctrl-C arrête proprement tout ce qui a été lancé ici.
#
# Usage :
#   tests/e2e/preflight.sh
#
# Variables d'env :
#   PORT         port serveur            (défaut : 8080)
#   HOST         interface d'écoute      (défaut : 0.0.0.0 → joignable sur le LAN)
#   NO_FRONTEND  =1 pour ne pas lancer Vite (banc serveur + 2 agents seulement)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dev_root="${FONTSYNC_DEV_ROOT:-$repo_root/.dev}"
log_dir="$dev_root/e2e"
port="${PORT:-8080}"
host="${HOST:-0.0.0.0}"
server_url="http://localhost:$port"

python_bin="$repo_root/.venv/bin/python"
[ -x "$python_bin" ] || python_bin="python3"

mkdir -p "$log_dir"

pids=()

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "==> Arrêt du banc E2E…"
  # 1) tuer les processus lancés ici (PIDs mémorisés).
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  # 2) filet de sécurité, scopé à FontSync pour ne jamais toucher un autre process.
  pkill -f "uvicorn backend.main:app" 2>/dev/null || true
  pkill -f "$repo_root/frontend/node_modules/.bin/vite" 2>/dev/null || true
  pkill -f "$repo_root/.venv/bin/python -m agent listen" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> Serveur FontSync (LAN) sur $host:$port"
HOST="$host" PORT="$port" "$repo_root/scripts/dev/run-server.sh" \
  >"$log_dir/server.log" 2>&1 &
pids+=("$!")

echo "==> Attente du serveur ($server_url/health)"
ready=0
for _ in $(seq 1 30); do
  if curl -fsS "$server_url/health" >/dev/null 2>&1; then
    ready=1
    echo "    serveur prêt"
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "ERREUR : serveur injoignable. Voir $log_dir/server.log" >&2
  exit 1
fi

if [ "${NO_FRONTEND:-0}" != "1" ] && [ -d "$repo_root/frontend" ]; then
  if [ ! -d "$repo_root/frontend/node_modules" ]; then
    echo "==> npm install (frontend, première fois)"
    (cd "$repo_root/frontend" && npm install) \
      || echo "    (npm install a échoué — frontend ignoré)"
  fi
  if [ -d "$repo_root/frontend/node_modules" ]; then
    echo "==> Frontend (Vite) sur http://localhost:8765"
    (cd "$repo_root/frontend" && npm run dev) >"$log_dir/frontend.log" 2>&1 &
    pids+=("$!")
  fi
fi

# Les 2 agents `listen` : devices isolés A et B, pointant sur ce serveur.
echo "==> Agent A (listen)"
FONTSYNC_SERVER_URL="$server_url" "$repo_root/scripts/dev/run-agent.sh" A listen \
  >"$log_dir/agent-A.log" 2>&1 &
pids+=("$!")

echo "==> Agent B (listen)"
FONTSYNC_SERVER_URL="$server_url" "$repo_root/scripts/dev/run-agent.sh" B listen \
  >"$log_dir/agent-B.log" 2>&1 &
pids+=("$!")

lan_ip="$(ipconfig getifaddr en0 2>/dev/null || true)"

cat <<EOF

================== Banc E2E prêt ==================
 Serveur   : $server_url${lan_ip:+   (LAN : http://$lan_ip:$port)}
 Frontend  : http://localhost:8765      (proxy → $server_url)
 Agents    : A et B en 'listen' (devices isolés sous $dev_root/{A,B})
 Logs      : $log_dir/{server,frontend,agent-A,agent-B}.log

 Provoquer un push chez A (→ serveur → signal SSE → pull/install chez B) :
   $python_bin scripts/dev/seed-font.py $dev_root/A/fonts --family "Inter" --style Regular
   scripts/dev/run-agent.sh A sync

 Suivre la propagation réactive vers B :
   tail -f $log_dir/agent-B.log
   ls $dev_root/B/fonts

 Ctrl-C pour tout arrêter.
==================================================
EOF

# Attend qu'un service s'arrête (ou un signal) ; cleanup fait le reste.
wait
