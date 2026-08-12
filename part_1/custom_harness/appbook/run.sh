#!/usr/bin/env bash
# Launch the ERPA — Custom Harness appbook.
set -euo pipefail
cd "$(dirname "$0")"

if ! python -c "import fastapi, sse_starlette, uvicorn" 2>/dev/null; then
  echo "Missing local appbook dependencies. Provision them before the workshop with:" >&2
  echo "  python -m pip install -r requirements.txt" >&2
  exit 1
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "→ ERPA — Custom Harness appbook on http://${HOST}:${PORT}"
exec uvicorn backend.main:app --host "${HOST}" --port "${PORT}" "$@"
