#!/usr/bin/env bash
# ==============================================================
# Script de inicio del Dashboard de Escritorio para Linux / macOS
# ==============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/python" ]; then
    echo "Iniciando Dashboard con entorno virtual (.venv)..."
    exec .venv/bin/python -m src.dashboard.main "$@"
else
    echo "Iniciando Dashboard con Python del sistema..."
    exec python3 -m src.dashboard.main "$@"
fi
