#!/bin/bash
set -euo pipefail

VENV_PATH="${VENV_PATH:-/root/venv}"
if [ -f "${VENV_PATH}/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${VENV_PATH}/bin/activate"
fi

# Single worker is required for in-memory SSE broadcaster and linear SQLite audit hash chain
exec uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
