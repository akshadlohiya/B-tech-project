#!/usr/bin/env bash
# One-command launcher for the UWB RTLS stack.
# Starts backend -> waits until it is healthy -> anchor-source -> frontend.
# Ctrl+C stops all three. Run from anywhere:  ./run.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "!! Python venv missing. Create it first:"
  echo "   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# Free ports / clear any stale copies of OUR services (won't touch other projects).
echo "clearing stale services..."
pkill -f "Model/backend.*server.js" 2>/dev/null || true
pkill -f "node server.js" 2>/dev/null || true
pkill -f "anchor-source/main.py" 2>/dev/null || true
pkill -f "Model/frontend/node_modules/.bin/vite" 2>/dev/null || true
sleep 1

# Install node deps on first run.
[ -d Model/backend/node_modules ]  || (echo "installing backend deps...";  cd Model/backend  && npm install)
[ -d Model/frontend/node_modules ] || (echo "installing frontend deps..."; cd Model/frontend && npm install)

pids=()
cleanup() { echo; echo "stopping services..."; for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

echo "[1/3] starting backend (:3000)..."
( cd Model/backend && node server.js ) &
pids+=($!)

# Wait for the backend to actually serve before starting the others.
printf "      waiting for backend"
for _ in $(seq 1 40); do
  if curl -s -o /dev/null http://localhost:3000/api/site 2>/dev/null; then echo " — up"; break; fi
  printf "."; sleep 0.5
done

echo "[2/3] starting anchor-source (simulator)..."
( cd Model/anchor-source && SOURCE="${SOURCE:-sim}" "$PY" main.py ) &
pids+=($!)

echo "[3/3] starting frontend (:5173)..."
( cd Model/frontend && npm run dev ) &
pids+=($!)

echo
echo "======================================================"
echo "  Open the digital twin:   http://localhost:5173"
echo "  Press Ctrl+C to stop all three services."
echo "======================================================"
wait
