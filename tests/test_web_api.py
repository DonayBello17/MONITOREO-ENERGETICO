"""Pruebas unitarias de la API Web y endpoints REST con FastAPI TestClient."""

from __future__ import annotations

import io
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Reading
from src.web.app import app


@pytest.fixture
def client_isolated(tmp_path: Path, monkeypatch):
    """Provee un TestClient con base de datos y configuración aisladas en tmp_path."""
    test_db_path = tmp_path / "test_web.db"
    test_cfg_path = tmp_path / "test_config.json"

    db = DatabaseManager(db_path=test_db_path)
    cfg = ConfigManager(config_path=test_cfg_path)
    db.upsert_circuits(cfg.get_circuits())

    now = time.time()
    r1 = Reading(
        timestamp=now - 100,
        circuit_id="circ_01",
        voltage=120.0,
        current=1.5,
        power_w=180.0,
        energy_kwh=0.045,
    )
    r2 = Reading(
        timestamp=now,
        circuit_id="circ_02",
        voltage=121.0,
        current=0.5,
        power_w=60.5,
        energy_kwh=0.015,
    )
    db.insert_readings_batch([r1, r2])
    db.calculate_hourly_aggregates()
    db.calculate_daily_aggregates()

    monkeypatch.setattr("src.web.app.db_manager", db)
    monkeypatch.setattr("src.web.app.cfg_manager", cfg)

    with TestClient(app) as test_client:
        yield test_client


def test_serve_index(client_isolated: TestClient):
    """Verifica que GET / responda 200 y sirva la página HTML del dashboard."""
    response = client_isolated.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Monitor Energético" in response.text
    assert "Tiempo Real" in response.text


def test_api_status(client_isolated: TestClient):
    """Verifica GET /api/status con métricas del sistema operativo y base de datos."""
    response = client_isolated.get("/api/status")
    assert response.status_code == 200
    data = response.json()

    assert "collector_status" in data
    assert "transport" in data
    assert "total_readings" in data
    assert data["total_readings"] == 2
    assert "web_pid" in data
    assert "system_metrics" in data

    metrics = data["system_metrics"]
    assert "cpu_percent" in metrics
    assert "ram_percent" in metrics
    assert "ram_used_mb" in metrics
    assert "platform" in metrics


def test_api_readings(client_isolated: TestClient):
    """Verifica la consulta paginada de lecturas con filtros."""
    # Consulta general
    response = client_isolated.get("/api/readings?page=1&page_size=50")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert len(data["records"]) == 2

    rec0 = data["records"][0]
    assert "id" in rec0
    assert "circuit_id" in rec0
    assert "voltage_v" in rec0
    assert "power_w" in rec0

    # Consulta filtrando por circuito
    res_c1 = client_isolated.get("/api/readings?circuit=circ_01")
    assert res_c1.status_code == 200
    data_c1 = res_c1.json()
    assert data_c1["total"] == 1
    assert data_c1["records"][0]["circuit_id"] == "circ_01"


def test_api_history(client_isolated: TestClient):
    """Verifica agregados históricos y costo estimado."""
    response = client_isolated.get("/api/history?period=daily")
    assert response.status_code == 200
    data = response.json()

    assert data["period"] == "daily"
    assert "total_kwh" in data
    assert data["total_kwh"] > 0
    assert "estimated_cost" in data
    assert "currency" in data
    assert "by_circuit" in data
    assert "time_series" in data


def test_api_alerts(client_isolated: TestClient):
    """Verifica la consulta del listado de alertas."""
    response = client_isolated.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


def test_api_config_get_and_post(client_isolated: TestClient):
    """Verifica consulta y modificación de tarifa y límites de potencia."""
    get_res = client_isolated.get("/api/config")
    assert get_res.status_code == 200
    cfg = get_res.json()
    assert "tariff" in cfg
    assert "alert_thresholds" in cfg

    # Modificar valores
    post_res = client_isolated.post(
        "/api/config",
        json={"base_rate_per_kwh": 0.22, "max_instant_power_w": 4500.0},
    )
    assert post_res.status_code == 200
    res_data = post_res.json()
    assert res_data["success"] is True

    # Comprobar actualización
    get_res2 = client_isolated.get("/api/config")
    cfg2 = get_res2.json()
    assert cfg2["tariff"]["base_rate_per_kwh"] == 0.22
    assert cfg2["alert_thresholds"]["max_instant_power_w"] == 4500.0


def test_api_export_csv(client_isolated: TestClient):
    """Verifica la descarga del histórico completo en formato CSV."""
    response = client_isolated.get("/api/export/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "lecturas_energia.csv" in response.headers.get("content-disposition", "")
    content = response.text
    assert "id,timestamp,circuit_id" in content or "circuit_id" in content


def test_api_seed_endpoint(client_isolated: TestClient, monkeypatch):
    """Verifica la ejecución del generador de datos aleatorios vía POST /api/seed."""
    dummy_result = {
        "days": 15,
        "interval_minutes": 15,
        "total_inserted": 50,
        "daily_averages_kwh": {"c1": 1.5, "c2": 0.8},
    }
    monkeypatch.setattr("src.web.app.seed_data", lambda **kwargs: dummy_result)

    response = client_isolated.post("/api/seed")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["result"]["total_inserted"] == 50


def test_api_import_invalid_file(client_isolated: TestClient):
    """Verifica que rechace archivos con extensiones no soportadas."""
    file_content = b"invalid content"
    files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    response = client_isolated.post("/api/import", files=files)
    assert response.status_code == 400


def test_api_realtime_endpoint(client_isolated: TestClient):
    """Verifica GET /api/realtime para fallback REST con telemetría de circuitos."""
    response = client_isolated.get("/api/realtime")
    assert response.status_code == 200
    data = response.json()

    assert "collector_connected" in data
    assert "transport" in data
    assert "total_power_w" in data
    assert "latest_by_circuit" in data
    assert "max_instant_power_w" in data

    # Debe contener lecturas de los circuitos previamente insertados
    circuits = data["latest_by_circuit"]
    assert "circ_01" in circuits
    assert circuits["circ_01"]["power_w"] == 180.0
    assert "voltage_v" in circuits["circ_01"]
    assert "current_a" in circuits["circ_01"]


def test_websocket_realtime(client_isolated: TestClient):
    """Verifica conexión WebSocket /ws/realtime recibiendo mensaje de bienvenida y lecturas."""
    with client_isolated.websocket_connect("/ws/realtime") as websocket:
        # Primer mensaje debe ser welcome
        welcome_msg = websocket.receive_json()
        assert welcome_msg["type"] == "welcome"
        assert "collector_connected" in welcome_msg["data"]
        assert "max_instant_power_w" in welcome_msg["data"]

        # Mensajes siguientes deben ser reading iniciales para los circuitos en BD
        reading_msg = websocket.receive_json()
        assert reading_msg["type"] == "reading"
        assert "circuit_id" in reading_msg["data"]
        assert "voltage_v" in reading_msg["data"]
        assert "current_a" in reading_msg["data"]


def test_api_circuits_crud(client_isolated: TestClient):
    """Verifica listar, crear y eliminar circuitos dinámicamente."""
    # 1. GET /api/circuits
    res_get = client_isolated.get("/api/circuits")
    assert res_get.status_code == 200
    circuits = res_get.json()
    assert isinstance(circuits, list)
    initial_count = len(circuits)
    assert initial_count >= 1

    # 2. POST /api/circuits - Crear nuevo circuito
    payload = {
        "name": "Televisor Sala",
        "location": "Sala",
        "min_power_w": 30.0,
        "max_power_w": 180.0,
        "nominal_power_w": 150.0,
        "daily_kwh_target": 1.1,
    }
    res_post = client_isolated.post("/api/circuits", json=payload)
    assert res_post.status_code == 200
    created_data = res_post.json()
    assert created_data["success"] is True
    new_circuit = created_data["circuit"]
    assert new_circuit["name"] == "Televisor Sala"
    assert new_circuit["id"].startswith("circ_")
    new_id = new_circuit["id"]

    # Verificar que aparece en GET
    res_get2 = client_isolated.get("/api/circuits")
    c_ids = [c["id"] for c in res_get2.json()]
    assert new_id in c_ids

    # 3. DELETE /api/circuits/{circuit_id}
    res_del = client_isolated.delete(f"/api/circuits/{new_id}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Verificar que ya no está
    res_get3 = client_isolated.get("/api/circuits")
    c_ids3 = [c["id"] for c in res_get3.json()]
    assert new_id not in c_ids3

    # 4. DELETE inexistente -> 404
    res_del_404 = client_isolated.delete("/api/circuits/circ_9999")
    assert res_del_404.status_code == 404
