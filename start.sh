#!/usr/bin/env bash
# Forte video summarizer: install what's missing, then run the backend and frontend together.
# Usage: ./start.sh        (Ctrl-C stops both; NO_OPEN=1 ./start.sh to not open the browser)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173

say() { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Requirements
command -v uv >/dev/null || fail "uv is not installed. Install it with: brew install uv  (or curl -LsSf https://astral.sh/uv/install.sh | sh)"
command -v npm >/dev/null || fail "Node.js is not installed. Install Node 20+ with: brew install node"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 20 ] || fail "Node.js 20+ is needed (found $(node -v))."
command -v ffmpeg >/dev/null || say "ffmpeg not found: fine for videos with captions; install it (brew install ffmpeg) for speech-to-text."

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Port $port is already in use. Stop whatever is running there (is the app already started?)."
  fi
done

# 2. Config: a local .env from the example (keys are optional; they can be entered in the app)
if [ ! -f "$ROOT/backend/.env" ]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  say "Created backend/.env from .env.example (add API keys there, or enter them in the app)."
fi

# 3. Dependencies (fast no-ops when already installed)
say "Installing backend dependencies…"
(cd "$ROOT/backend" && uv sync --quiet)
if [ ! -d "$ROOT/frontend/node_modules" ] || [ "$ROOT/frontend/package-lock.json" -nt "$ROOT/frontend/node_modules/.package-lock.json" ]; then
  say "Installing frontend dependencies…"
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund --silent)
fi

# 4. Run both; stop both on Ctrl-C or if either one exits
pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

prefix() { while IFS= read -r line; do printf '%s %s\n' "$1" "$line"; done; }

(cd "$ROOT/backend" && exec uv run --env-file .env uvicorn app.api.main:app --port "$BACKEND_PORT" --reload) \
  > >(prefix $'\033[35m[api]\033[0m') 2>&1 &
pids+=($!)
(cd "$ROOT/frontend" && exec npm run dev -- --port "$FRONTEND_PORT" --strictPort) \
  > >(prefix $'\033[36m[web]\033[0m') 2>&1 &
pids+=($!)

say "Starting… open http://localhost:$FRONTEND_PORT  (Ctrl-C to stop)"

# Open the browser once the frontend answers (macOS `open`, Linux `xdg-open`). NO_OPEN=1 skips it.
[ -n "${NO_OPEN:-}" ] || (
  for _ in $(seq 60); do
    if curl -fsS "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
      if command -v open >/dev/null; then open "http://localhost:$FRONTEND_PORT"
      elif command -v xdg-open >/dev/null; then xdg-open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1
      fi
      break
    fi
    sleep 1
  done
) &

# bash 3.2 (macOS) has no `wait -n`: poll until one of the servers stops.
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 1; done
say "A server stopped; shutting down."
