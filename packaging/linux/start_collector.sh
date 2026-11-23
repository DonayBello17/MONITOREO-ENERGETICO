#!/usr/bin/env bash
# ==============================================================
# Script de inicio del Recolector Energético para Linux / macOS
# ==============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/python" ]; then
    echo "Iniciando recolector con entorno virtual (.venv)..."
    exec .venv/bin/python -m src.collector.main
else
    echo "Iniciando recolector con Python del sistema..."
    exec python3 -m src.collector.main
fi
