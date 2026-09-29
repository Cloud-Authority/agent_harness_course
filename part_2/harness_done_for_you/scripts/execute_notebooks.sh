#!/usr/bin/env bash
# Execute one or both notebooks in place, with outputs saved.
#
#   scripts/execute_notebooks.sh memorizz
#   scripts/execute_notebooks.sh metaharness
#   scripts/execute_notebooks.sh            # both, in teaching order
#
# Keys are read from the environment. They are never written to a file.
# Each notebook is standalone and gets its own state folder under data/.
set -euo pipefail

TRACK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${PPA_VENV:-$TRACK/.venv}"
PYTHON="$VENV/bin/python"
# Put the environment first on PATH. `python -m jupyter` looks up `jupyter-nbconvert`
# on PATH, and the kernelspec starts `python` from PATH, so without this line another
# Jupyter installation on the machine would run the notebook with its own packages.
export PATH="$VENV/bin:$PATH"
DATA="${PPA_DATA_DIR:-$TRACK/data}"
export PPA_WORKSPACE="${PPA_WORKSPACE:-$TRACK/workspace/notebook}"
export MEMORIZZ_PI_COMMAND="${MEMORIZZ_PI_COMMAND:-$TRACK/.tools/node_modules/.bin/pi}"
export MEMORIZZ_HERMES_COMMAND="${MEMORIZZ_HERMES_COMMAND:-$TRACK/.tools/hermes-venv/bin/hermes}"

run() {
  local notebook="$1" home="$2"
  echo "executing ${notebook#$TRACK/} with state in ${home#$TRACK/}"
  ( cd "$(dirname "$notebook")" && PPA_HOME="$home" "$VENV/bin/jupyter-nbconvert" \
      --to notebook --execute --inplace \
      --ExecutePreprocessor.timeout=1800 --ExecutePreprocessor.kernel_name=python3 \
      "$(basename "$notebook")" )
}

MEMAGENT="$TRACK/memorizz/assistant/notebook/ppa_memorizz_complete.ipynb"
METAHARNESS="$TRACK/metaharness/notebook/ppa_metaharness_pi_deepseek_hermes.ipynb"
case "${1:-both}" in
  memorizz)    run "$MEMAGENT" "$DATA/memagent" ;;
  metaharness) run "$METAHARNESS" "$DATA/metaharness" ;;
  both)        run "$MEMAGENT" "$DATA/memagent"
               run "$METAHARNESS" "$DATA/metaharness" ;;
  *) echo "usage: $0 [memorizz|metaharness|both]" >&2; exit 2 ;;
esac
"$PYTHON" "$TRACK/scripts/scan_notebooks.py"
