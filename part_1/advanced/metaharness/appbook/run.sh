#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COURSE_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$COURSE_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing course environment. Install part_1/advanced/requirements.txt first." >&2
  exit 1
fi
export PYTHONPATH="$COURSE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-${METAHARNESS_PORT:-8012}}"
cd "$SCRIPT_DIR"
echo "→ MemoRizz MetaHarness appbook on http://${HOST}:${PORT}"
exec "$PYTHON_BIN" -m uvicorn backend.main:app --host "$HOST" --port "$PORT" "$@"
