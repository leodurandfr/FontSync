#!/usr/bin/env bash
#
# « dev:full » — lance les deux services **persistants** ensemble :
# le serveur FontSync (hôte, reload) + le frontend Vite. Ctrl-C arrête les deux.
#
# L'agent n'est PAS inclus à dessein : il est one-shot (`sync`) ou par-device
# (`listen`), donc il ne rentre pas dans un launcher persistant unique. Utilise
# scripts/dev/run-agent.sh / demo.sh pour la partie client.
#
# Usage :
#   scripts/dev/up.sh          (ou, depuis frontend/ :  npm run dev:full)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
server_url="${FONTSYNC_SERVER_URL:-http://localhost:8080}"

server_pid=""
frontend_pid=""

cleanup() {
  trap - INT TERM EXIT
  # Tue les processus lancés ici. Les pkill sont **scopés à FontSync** pour ne
  # jamais toucher un autre serveur/Vite tournant sur la machine.
  [ -n "$frontend_pid" ] && kill "$frontend_pid" 2>/dev/null || true
  [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
  pkill -f "uvicorn backend.main:app" 2>/dev/null || true
  pkill -f "$repo_root/frontend/node_modules/.bin/vite" 2>/dev/null || true
}
# Les deux services tournent en arrière-plan + `wait` : un signal interrompt le
# `wait` et déclenche `cleanup` immédiatement (un enfant en avant-plan, lui,
# retarderait le trap jusqu'à sa propre fin).
trap cleanup INT TERM EXIT

echo "==> Démarrage du serveur"
"$repo_root/scripts/dev/run-server.sh" &
server_pid=$!

echo "==> Attente du serveur ($server_url)"
for _ in $(seq 1 30); do
  if curl -fsS "$server_url/health" >/dev/null 2>&1; then
    echo "    serveur prêt"
    break
  fi
  sleep 1
done

if [ ! -d "$repo_root/frontend/node_modules" ]; then
  echo "==> npm install (première fois)"
  (cd "$repo_root/frontend" && npm install)
fi

echo "==> Démarrage du frontend (Ctrl-C pour tout arrêter)"
(cd "$repo_root/frontend" && npm run dev) &
frontend_pid=$!

# Attend que l'un des deux s'arrête (ou un signal) ; cleanup fait le reste.
wait
