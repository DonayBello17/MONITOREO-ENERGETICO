"""Servidor y API REST / WebSocket FastAPI para Monitoreo Energético.

Reutiliza al 100% la base de datos SQLite WAL, el gestor de configuración,
los perfiles de consumo, la generación de reportes PDF y el IPC dual (AF_UNIX / TCP)
con reconexión automática continua hacia el proceso recolector.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from scripts.seed_realistic_data import seed_data
from src.collector.validator import ReadingValidator
from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.paths import get_data_dir, get_socket_path
from src.common.profiles import CIRCUIT_PROFILES
from src.dashboard.cost_calculator import calculate_fixed_cost
from src.dashboard.reports.exporter import (
    export_readings_to_csv,
    import_readings_from_csv,
    import_readings_from_json,
)
from src.dashboard.reports.pdf_report import generate_monthly_pdf_report

logger = logging.getLogger("web")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# GESTOR DE CONEXIONES WEBSOCKET
# ==============================================================================
class ConnectionManager:
    """Administra conexiones activas de clientes WebSocket para difusión de telemetría."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            dead: List[WebSocket] = []
            for conn in self.active_connections:
                try:
                    await conn.send_json(message)
                except Exception:
                    dead.append(conn)
            for d in dead:
                if d in self.active_connections:
                    self.active_connections.remove(d)


ws_manager = ConnectionManager()


# ==============================================================================
# PUENTE IPC DUAL (AF_UNIX / TCP) CON RECONEXIÓN AUTOMÁTICA
# ==============================================================================
class IPCBridge:
    """Escucha eventos del recolector y los retransmite en vivo por WebSocket."""

    def __init__(self, host: str = "127.0.0.1", port: int = 50555) -> None:
        self.host = host
        self.port = port
        self.use_unix_socket = (sys.platform != "win32") and hasattr(socket, "AF_UNIX")
        self.socket_path = get_socket_path() if self.use_unix_socket else None
        self.transport_name = "AF_UNIX" if self.use_unix_socket else "TCP"

        self.is_connected = False
        self.last_reading: Optional[Dict[str, Any]] = None
        self.latest_readings_by_circuit: Dict[str, Dict[str, Any]] = {}
        self.last_status: Optional[Dict[str, Any]] = None
        self.collector_pid: Optional[int] = None

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="WebIPCBridge")
        self._thread.start()
        logger.info(
            "Puente IPC iniciado (Transporte previsto: %s)",
            self.transport_name,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self.is_connected = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            sock: Optional[socket.socket] = None
            try:
                if self.use_unix_socket and self.socket_path:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(3.0)
                    sock.connect(str(self.socket_path))
                else:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3.0)
                    sock.connect((self.host, self.port))

                sock.settimeout(1.0)
                self.is_connected = True
                logger.info("Puente IPC conectado exitosamente al recolector (%s)", self.transport_name)

                buffer = ""
                while not self._stop_event.is_set() and self.is_connected:
                    try:
                        chunk = sock.recv(4096).decode("utf-8")
                        if not chunk:
                            logger.warning("El servidor recolector cerró la conexión IPC.")
                            break
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            self._handle_message(line)
                    except socket.timeout:
                        continue
                    except Exception as exc:
                        logger.warning("Conexión perdida en puente IPC: %s", exc)
                        break

            except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
                # Recolector no iniciado aún
                pass
            finally:
                self.is_connected = False
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            if not self._stop_event.is_set():
                time.sleep(2.0)

    def _handle_message(self, line: str) -> None:
        try:
            msg = json.loads(line)
            mtype = msg.get("type")
            data = msg.get("data", {})

            if mtype == "reading" and isinstance(data, dict):
                # Normalizar claves para compatibilidad absoluta frontend / backend
                v = data.get("voltage_v") if data.get("voltage_v") is not None else data.get("voltage", 120.0)
                c = data.get("current_a") if data.get("current_a") is not None else data.get("current", 0.0)
                data["voltage_v"] = float(v)
                data["voltage"] = float(v)
                data["current_a"] = float(c)
                data["current"] = float(c)
                data["power_w"] = float(data.get("power_w", 0.0))
                data["energy_kwh"] = float(data.get("energy_kwh", 0.0))
                msg["data"] = data

                self.last_reading = data
                cid = data.get("circuit_id")
                if cid:
                    self.latest_readings_by_circuit[cid] = data

            elif mtype == "status":
                self.last_status = data
                if "pid" in data:
                    self.collector_pid = int(data["pid"])

            if self._loop and self._loop.is_running():
                future = asyncio.run_coroutine_threadsafe(ws_manager.broadcast(msg), self._loop)
                def _log_err(f):
                    try:
                        f.result()
                    except Exception as exc:
                        logger.debug("Error en corrutina broadcast WebSocket: %s", exc)
                future.add_done_callback(_log_err)
        except Exception as exc:
            logger.debug("Error procesando mensaje IPC: %s", exc)

    def get_all_latest_readings(self) -> Dict[str, Dict[str, Any]]:
        """Devuelve las lecturas más recientes para cada circuito (memoria + fallback SQLite)."""
        res = dict(self.latest_readings_by_circuit)
        try:
            for circuit in cfg_manager.get_circuits():
                if circuit.id not in res:
                    latest = db_manager.get_readings(circuit_id=circuit.id, limit=1)
                    if latest:
                        r_dict = latest[0].to_dict()
                        v = r_dict.get("voltage", 120.0)
                        curr = r_dict.get("current", 0.0)
                        r_dict["voltage_v"] = float(v)
                        r_dict["voltage"] = float(v)
                        r_dict["current_a"] = float(curr)
                        r_dict["current"] = float(curr)
                        r_dict["power_w"] = float(r_dict.get("power_w", 0.0))
                        r_dict["energy_kwh"] = float(r_dict.get("energy_kwh", 0.0))
                        res[circuit.id] = r_dict
        except Exception as exc:
            logger.debug("Error recuperando lecturas recientes de BD: %s", exc)
        return res


ipc_bridge: Optional[IPCBridge] = None
db_manager = DatabaseManager()
cfg_manager = ConfigManager()


# ==============================================================================
# CICLO DE VIDA DE LA APLICACIÓN FASTAPI
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global ipc_bridge
    loop = asyncio.get_running_loop()
    host = cfg_manager.ipc_host
    port = cfg_manager.ipc_port
    ipc_bridge = IPCBridge(host=host, port=port)
    ipc_bridge.start(loop)
    yield
    if ipc_bridge:
        ipc_bridge.stop()


app = FastAPI(
    title="Monitor Energético Residencial - Web API",
    description="Interfaz web y API REST para monitoreo en tiempo real, histórico y costos.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_collector_pid() -> Optional[int]:
    """Obtiene el PID del recolector en segundo plano si está disponible."""
    if ipc_bridge and ipc_bridge.collector_pid:
        return ipc_bridge.collector_pid
    try:
        pid_file = get_data_dir() / "collector.pid"
        if pid_file.exists():
            return int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    return None


# ==============================================================================
# MODELOS DE ENTRADA REST
# ==============================================================================
class ConfigUpdateRequest(BaseModel):
    base_rate_per_kwh: Optional[float] = None
    max_instant_power_w: Optional[float] = None


# ==============================================================================
# RUTAS PRINCIPALES Y WEBSOCKET
# ==============================================================================
@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Sirve la interfaz web moderna responsiva."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.websocket("/ws/realtime")
async def websocket_realtime_endpoint(websocket: WebSocket):
    """Canal WebSocket para difusión en tiempo real de telemetría hacia el navegador."""
    if ipc_bridge:
        try:
            active_loop = asyncio.get_running_loop()
            if ipc_bridge._loop != active_loop:
                ipc_bridge._loop = active_loop
        except RuntimeError:
            pass

    await ws_manager.connect(websocket)
    try:
        latest_by_circuit = ipc_bridge.get_all_latest_readings() if ipc_bridge else {}
        last_rd = ipc_bridge.last_reading if ipc_bridge else None
        if not last_rd and latest_by_circuit:
            last_rd = max(latest_by_circuit.values(), key=lambda r: r.get("timestamp", 0))

        init_payload = {
            "type": "welcome",
            "data": {
                "collector_connected": ipc_bridge.is_connected if ipc_bridge else False,
                "transport": ipc_bridge.transport_name if ipc_bridge else "TCP",
                "last_reading": last_rd,
                "latest_by_circuit": latest_by_circuit,
                "max_instant_power_w": cfg_manager.alert_thresholds.get("max_instant_power_w", 5500.0),
            },
        }
        await websocket.send_json(init_payload)

        # Enviar inmediatamente eventos reading para cada circuito para que las tarjetas se pinten al instante
        for cid, r_data in latest_by_circuit.items():
            await websocket.send_json({"type": "reading", "data": r_data})

        while True:
            # Mantener conexión viva recibiendo pings del cliente
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# ==============================================================================
# ENDPOINTS REST
# ==============================================================================
@app.get("/api/realtime")
async def get_realtime_telemetry():
    """Telemetría instantánea de todos los circuitos y demanda total (fallback REST)."""
    is_conn = ipc_bridge.is_connected if ipc_bridge else False
    transport = ipc_bridge.transport_name if ipc_bridge else "TCP"
    latest_by_circuit = ipc_bridge.get_all_latest_readings() if ipc_bridge else {}
    last_rd = ipc_bridge.last_reading if ipc_bridge else None
    if not last_rd and latest_by_circuit:
        last_rd = max(latest_by_circuit.values(), key=lambda r: r.get("timestamp", 0))

    total_power = sum(float(r.get("power_w", 0.0)) for r in latest_by_circuit.values())

    return {
        "collector_connected": is_conn,
        "transport": transport,
        "total_power_w": round(total_power, 1),
        "last_reading": last_rd,
        "latest_by_circuit": latest_by_circuit,
        "max_instant_power_w": cfg_manager.alert_thresholds.get("max_instant_power_w", 5500.0),
    }


@app.get("/api/status")
async def get_status():
    """Estado de conexión, transporte IPC, conteo de BD y métricas del sistema operativo."""
    is_conn = ipc_bridge.is_connected if ipc_bridge else False
    transport = ipc_bridge.transport_name if ipc_bridge else "TCP"
    total_records = db_manager.get_total_readings_count()

    vm = psutil.virtual_memory()
    sys_metrics = {
        "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
        "ram_percent": round(vm.percent, 1),
        "ram_used_mb": round(vm.used / (1024 * 1024), 1),
        "ram_total_mb": round(vm.total / (1024 * 1024), 1),
        "platform": sys.platform,
    }

    latest_by_circuit = ipc_bridge.get_all_latest_readings() if ipc_bridge else {}
    last_rd = ipc_bridge.last_reading if ipc_bridge else None
    if not last_rd and latest_by_circuit:
        last_rd = max(latest_by_circuit.values(), key=lambda r: r.get("timestamp", 0))

    total_power = sum(float(r.get("power_w", 0.0)) for r in latest_by_circuit.values())

    return {
        "collector_status": "conectado" if is_conn else "desconectado",
        "transport": transport,
        "total_readings": total_records,
        "last_reading": last_rd,
        "total_power_w": round(total_power, 1),
        "latest_by_circuit": latest_by_circuit,
        "collector_pid": get_collector_pid(),
        "web_pid": os.getpid(),
        "system_metrics": sys_metrics,
    }


@app.get("/api/readings")
async def get_readings(
    circuit: Optional[str] = Query(None, description="ID del circuito o None para todos"),
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, description="Filas por página (50, 100, 500)"),
):
    """Consulta paginada directa a SQLite de las lecturas registradas."""
    valid_size = 500 if page_size >= 300 else (100 if page_size >= 75 else 50)
    total = db_manager.get_total_readings_count(circuit_id=circuit)
    total_pages = max(1, (total + valid_size - 1) // valid_size)
    current_page = min(page, total_pages)
    offset = (current_page - 1) * valid_size

    records = db_manager.get_readings_paginated(
        circuit_id=circuit,
        limit=valid_size,
        offset=offset,
        order_desc=True,
    )

    # Asegurar compatibilidad dual con voltage/voltage_v y current/current_a
    normalized_records = []
    for r in records:
        item = dict(r)
        item["voltage_v"] = item.get("voltage", 0.0)
        item["current_a"] = item.get("current", 0.0)
        normalized_records.append(item)

    return {
        "records": normalized_records,
        "total": total,
        "page": current_page,
        "page_size": valid_size,
        "total_pages": total_pages,
    }


@app.get("/api/history")
async def get_history(period: str = Query("daily", pattern="^(hourly|daily|monthly)$")):
    """Agregados históricos de consumo y cálculo de costo estimado según tarifa."""
    aggs = db_manager.get_aggregates(period_type=period)
    tariff = cfg_manager.tariff
    base_rate = float(tariff.get("base_rate_per_kwh", 0.15))
    currency = tariff.get("currency", "USD")

    total_kwh = sum(a.total_energy_kwh for a in aggs)
    estimated_cost = calculate_fixed_cost(total_kwh, base_rate)

    # Agrupar por circuito
    by_circuit: Dict[str, float] = {}
    for a in aggs:
        by_circuit[a.circuit_id] = round(by_circuit.get(a.circuit_id, 0.0) + a.total_energy_kwh, 4)

    # Agrupar por timestamp de periodo para evolución temporal
    time_series: Dict[float, float] = {}
    for a in aggs:
        time_series[a.period_start] = round(time_series.get(a.period_start, 0.0) + a.total_energy_kwh, 4)

    series_sorted = [{"timestamp": k, "kwh": v} for k, v in sorted(time_series.items())]

    return {
        "period": period,
        "total_kwh": round(total_kwh, 4),
        "estimated_cost": estimated_cost,
        "currency": currency,
        "by_circuit": by_circuit,
        "time_series": series_sorted,
    }


@app.get("/api/alerts")
async def get_alerts():
    """Listado de alertas y anomalías detectadas."""
    alerts = db_manager.get_alerts()
    return {
        "alerts": [
            {
                "id": a.id,
                "timestamp": a.timestamp,
                "datetime": datetime.fromtimestamp(a.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                "circuit_id": a.circuit_id or "General",
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "value": a.value,
                "threshold": a.threshold,
                "is_acknowledged": bool(a.is_acknowledged),
            }
            for a in alerts
        ]
    }


@app.get("/api/config")
async def get_config():
    """Consulta la configuración activa de tarifas, umbrales y circuitos."""
    return {
        "tariff": cfg_manager.tariff,
        "alert_thresholds": cfg_manager.alert_thresholds,
        "circuits": [c.to_dict() for c in cfg_manager.get_circuits()],
    }


@app.post("/api/config")
async def update_config(payload: ConfigUpdateRequest):
    """Actualiza la tarifa por kWh y/o el umbral de alerta de potencia."""
    updated = False
    if payload.base_rate_per_kwh is not None:
        t = cfg_manager.tariff
        t["base_rate_per_kwh"] = max(0.01, float(payload.base_rate_per_kwh))
        cfg_manager.update_section("tariff", t)
        updated = True

    if payload.max_instant_power_w is not None:
        th = cfg_manager.alert_thresholds
        th["max_instant_power_w"] = max(100.0, float(payload.max_instant_power_w))
        cfg_manager.update_section("alert_thresholds", th)
        updated = True

    if updated:
        saved = cfg_manager.save()
        return {"success": saved, "message": "Configuración guardada exitosamente."}
    return {"success": False, "message": "No se enviaron campos para actualizar."}


@app.post("/api/seed")
async def run_seed():
    """Ejecuta el generador realista de telemetría (15 días) y devuelve el resumen."""
    try:
        result = seed_data(
            db_manager=db_manager,
            days=15,
            interval_minutes=15,
            clear=False,
        )
        return {"success": True, "result": result}
    except Exception as exc:
        logger.error("Error al poblar BD desde API web: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/import")
async def import_file(file: UploadFile = File(...)):
    """Importa lecturas desde un archivo .csv o .json subido por el usuario."""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in (".csv", ".json"):
        raise HTTPException(
            status_code=400,
            detail="Formato de archivo no soportado. Debe ser .csv o .json",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        shutil.copyfileobj(file.file, tmp)

    try:
        if suffix == ".csv":
            count, errs = import_readings_from_csv(tmp_path, db=db_manager)
        else:
            count, errs = import_readings_from_json(tmp_path, db=db_manager)

        # Recalcular agregados
        db_manager.calculate_hourly_aggregates()
        db_manager.calculate_daily_aggregates()
        db_manager.calculate_monthly_aggregates()

        return {"success": True, "imported_count": count, "error_count": len(errs)}
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/export/csv")
async def export_csv():
    """Descarga el historial completo de lecturas en formato CSV."""
    readings = db_manager.get_readings(limit=100000)
    circuits_map = {c.id: c.name for c in cfg_manager.get_circuits()}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp_path = Path(tmp.name)

    export_readings_to_csv(readings, circuits_map, tmp_path)

    return FileResponse(
        path=str(tmp_path),
        media_type="text/csv",
        filename="lecturas_energia.csv",
        background=None,
    )


@app.get("/api/export/pdf")
async def export_pdf():
    """Genera y descarga el reporte mensual en PDF con ReportLab."""
    now = datetime.now()
    year = now.year
    month = now.month

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = Path(tmp.name)

    generate_monthly_pdf_report(
        db=db_manager,
        config=cfg_manager,
        year=year,
        month=month,
        output_path=str(tmp_path),
    )

    return FileResponse(
        path=str(tmp_path),
        media_type="application/pdf",
        filename=f"reporte_energia_{year}_{month:02d}.pdf",
        background=None,
    )
