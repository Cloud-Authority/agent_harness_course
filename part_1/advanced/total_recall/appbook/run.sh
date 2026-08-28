#!/usr/bin/env bash
set -euo pipefail

APPBOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${APPBOOK_DIR}/../../../.." && pwd)"
cd "${PROJECT_ROOT}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8013}"
PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi
echo "Total Recall appbook: http://${HOST}:${PORT}"
exec "${PYTHON_BIN}" -m uvicorn part_1.advanced.total_recall.appbook.backend.main:app \
  --host "${HOST}" --port "${PORT}" "$@"
