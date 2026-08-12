#!/usr/bin/env bash
# Launch the ERPA on MemoRizz appbook.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PYTHON_BIN="${ERPA_PYTHON:-python}"

if ! "${PYTHON_BIN}" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "The selected Python interpreter is missing appbook dependencies: ${PYTHON_BIN}" >&2
  echo "Install requirements.txt and requirements-live.txt in that environment." >&2
  exit 1
fi

echo "→ ERPA on MemoRizz appbook on http://${HOST}:${PORT}"
echo "  Python: ${PYTHON_BIN}"
exec "${PYTHON_BIN}" -m uvicorn backend.main:app --host "${HOST}" --port "${PORT}" "$@"
