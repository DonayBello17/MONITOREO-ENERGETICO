#!/usr/bin/env bash
set -e

echo "=================================================="
echo "Iniciando Monitor Energético Residencial en la Nube"
echo "=================================================="

# 1. Verificar si la base de datos existe y tiene registros; si no, poblar automáticamente
python -c "from src.common.database import DatabaseManager; db = DatabaseManager(); exit(0 if db.get_total_readings_count() > 0 else 1)" || {
    echo "[INIT] Base de datos vacía o no inicializada. Generando telemetría realista inicial (15 días)..."
    python -m scripts.seed_realistic_data --days 15 --interval-minutes 15
}

# 2. Iniciar el recolector en segundo plano (usará socket AF_UNIX en Linux)
echo "[INIT] Lanzando proceso recolector en segundo plano..."
python -m src.collector.main &
COLLECTOR_PID=$!
echo "[INIT] Recolector iniciado con PID $COLLECTOR_PID"

# Manejo de señales para apagado limpio
cleanup() {
    echo "[SHUTDOWN] Señal recibida. Deteniendo recolector (PID $COLLECTOR_PID)..."
    kill -TERM "$COLLECTOR_PID" 2>/dev/null || true
    wait "$COLLECTOR_PID" 2>/dev/null || true
    echo "[SHUTDOWN] Recolector detenido. Saliendo."
    exit 0
}
trap cleanup SIGTERM SIGINT

# 3. Lanzar servidor web FastAPI con Uvicorn
PORT_TO_USE="${PORT:-8000}"
echo "[INIT] Servidor Web iniciando en el puerto $PORT_TO_USE..."
uvicorn src.web.app:app --host 0.0.0.0 --port "$PORT_TO_USE" &
UVICORN_PID=$!

wait $UVICORN_PID
