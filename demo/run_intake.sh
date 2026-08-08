#!/usr/bin/env bash
# Launch the S7 epic intake — the interactive clarify-then-plan demo.
#
# Binds to 127.0.0.1 deliberately: a presenter's local demo, not a service.
#
# Unlike the console, this beat is interactive — answers are free text — so
# LLM_MODE defaults to *live* here and needs a provider key in .env. A
# rehearsed conversation (same epic, same answers) replays offline after a
# LLM_MODE=record run, per hard rule 5.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8710}"
export LLM_MODE="${LLM_MODE:-live}"

if [ -x .venv/bin/uvicorn ]; then
  PY=.venv/bin/uvicorn
elif command -v uvicorn >/dev/null 2>&1; then
  PY=uvicorn
else
  echo "uvicorn not found. Create the venv first:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

echo "S7 epic intake -> http://127.0.0.1:${PORT}  (LLM_MODE=${LLM_MODE})"
echo "Ctrl-C to stop."
exec "$PY" apps.intake.server:app --host 127.0.0.1 --port "$PORT" "$@"
