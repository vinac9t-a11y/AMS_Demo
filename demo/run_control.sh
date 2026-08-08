#!/usr/bin/env bash
# Launch the S7 Delivery Control Centre.
#
# Binds to 127.0.0.1 deliberately: a presenter's local demo, not a service.
# No API key needed — the default demo mode is deterministic simulation, and
# run state persists under artifacts/runs/ so a restart loses nothing.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8720}"

if [ -x .venv/bin/uvicorn ]; then
  UV=.venv/bin/uvicorn
elif command -v uvicorn >/dev/null 2>&1; then
  UV=uvicorn
else
  echo "uvicorn not found. Create the venv first:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

echo "S7 Delivery Control Centre -> http://127.0.0.1:${PORT}"
echo "Ctrl-C to stop."
exec "$UV" apps.control.server:app --host 127.0.0.1 --port "$PORT" "$@"
