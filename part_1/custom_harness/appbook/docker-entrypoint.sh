#!/usr/bin/env sh
set -eu

if [ "${ERPA_MODE:-local}" = "live" ]; then
  python docker/bootstrap_oracle.py
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
