#!/usr/bin/env bash
# ==============================================================
# Script de inicio del Servidor Web FastAPI para Linux / macOS
# ==============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

echo "==================================================="
echo "Iniciando Servidor Web FastAPI en http://127.0.0.1:8000"
echo "==================================================="

# Abrir navegador si existe comando xdg-open
if command -v xdg-open >/dev/null 2>&1; then
    (sleep 2 && xdg-open "http://127.0.0.1:8000") &
fi

if [ -f ".venv/bin/python" ]; then
    echo "Usando entorno virtual .venv..."
    exec .venv/bin/python -m uvicorn src.web.app:app --host 0.0.0.0 --port 8000
else
    echo "Usando Python del sistema..."
    exec python3 -m uvicorn src.web.app:app --host 0.0.0.0 --port 8000
fi
