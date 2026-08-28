#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COURSE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$COURSE_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing course environment. From $COURSE_ROOT run:" >&2
  echo "  python3.12 -m venv .venv && .venv/bin/python -m pip install -r part_1/advanced/requirements.txt" >&2
  exit 1
fi
export PYTHONPATH="$COURSE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export ADVANCED_BACKEND=oracle
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-${WORKFLOW_PORT:-8010}}"
cd "$SCRIPT_DIR"
echo "→ Durable Workflow appbook on http://${HOST}:${PORT}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$HOST" --port "$PORT" "$@"
