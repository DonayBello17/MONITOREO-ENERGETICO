"""Pruebas unitarias de la API Web, autenticación, protección de sesiones y exportación CSV."""

from __future__ import annotations

import io
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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

    # Variables de entorno para prueba de autenticación
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "monitor2026")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-session-key-12345")

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client_isolated: TestClient) -> TestClient:
    """Provee un TestClient con sesión iniciada exitosamente."""
    res = client_isolated.post("/login", data={"username": "admin", "password": "monitor2026"})
    assert res.status_code in (200, 303)
    return client_isolated


# ==============================================================================
# PRUEBAS DE AUTENTICACIÓN Y SEGURIDAD
# ==============================================================================
def test_unauthenticated_access_denied(client_isolated: TestClient):
    """Verifica acceso denegado (303 a /login y 401 en /api/*) sin iniciar sesión."""
    # 1. GET / sin sesión redirige con 303 a /login
    res_index = client_isolated.get("/", follow_redirects=False)
    assert res_index.status_code == 303
    assert res_index.headers.get("location") == "/login"

    # 2. Endpoints /api/* devuelven 401 Unauthorized
    res_status = client_isolated.get("/api/status")
    assert res_status.status_code == 401
    assert "detail" in res_status.json()

    res_me = client_isolated.get("/api/auth/me")
    assert res_me.status_code == 401


def test_public_static_and_favicon_unauthenticated(client_isolated: TestClient):
    """Verifica que los assets locales (/static/vendor/tailwind.js, chart.umd.min.js y /favicon.ico) sean públicos."""
    # 1. tailwind.js se sirve públicamente
    res_tw = client_isolated.get("/static/vendor/tailwind.js")
    assert res_tw.status_code == 200
    assert len(res_tw.content) > 10000

    # 2. chart.umd.min.js se sirve públicamente
    res_chart = client_isolated.get("/static/vendor/chart.umd.min.js")
    assert res_chart.status_code == 200
    assert len(res_chart.content) > 10000

    # 3. favicon.ico se sirve públicamente
    res_fav = client_isolated.get("/favicon.ico")
    assert res_fav.status_code == 200

    # 4. favicon.svg se sirve públicamente
    res_svg = client_isolated.get("/favicon.svg")
    assert res_svg.status_code == 200
    assert "image/svg+xml" in res_svg.headers.get("content-type", "")

    # 5. La página de login enlaza a los recursos locales y no a CDNs externos
    res_login = client_isolated.get("/login")
    assert res_login.status_code == 200
    assert "/static/vendor/tailwind.js" in res_login.text
    assert "https://cdn.tailwindcss.com" not in res_login.text


def test_login_success_and_cache_headers(client_isolated: TestClient):
    """Verifica inicio de sesión exitoso, cabeceras anti-caché y verificación de sesión."""
    # 1. POST /login con credenciales correctas
    res_login = client_isolated.post(
        "/login",
        data={"username": "admin", "password": "monitor2026"},
        follow_redirects=False,
    )
    assert res_login.status_code == 303
    assert res_login.headers.get("location") == "/"
    assert "energy_session" in client_isolated.cookies

    # 2. Acceso a GET / con sesión válida y verificación de cabeceras no-store
    res_index = client_isolated.get("/")
    assert res_index.status_code == 200
    assert "Monitor Energético" in res_index.text
    # Blindaje contra botón Atrás (cabeceras Cache-Control)
    cc = res_index.headers.get("cache-control", "").lower()
    assert "no-store" in cc
    assert "no-cache" in cc
    assert "must-revalidate" in cc
    assert res_index.headers.get("pragma", "").lower() == "no-cache"
    assert res_index.headers.get("expires") == "0"

    # 3. GET /api/auth/me devuelve usuario autenticado
    res_me = client_isolated.get("/api/auth/me")
    assert res_me.status_code == 200
    data_me = res_me.json()
    assert data_me["authenticated"] is True
    assert data_me["user"] == "admin"

    # 4. Cabeceras anti-caché presentes en respuestas /api/*
    cc_api = res_me.headers.get("cache-control", "").lower()
    assert "no-store" in cc_api


def test_login_invalid_credentials(client_isolated: TestClient):
    """Verifica que credenciales incorrectas devuelvan 401 tanto en formulario como en JSON."""
    # Formulario HTML
    res_form = client_isolated.post(
        "/login",
        data={"username": "admin", "password": "wrong_password"},
    )
    assert res_form.status_code == 401
    assert "Usuario o contraseña incorrectos" in res_form.text

    # JSON API
    res_json = client_isolated.post(
        "/login",
        json={"username": "invalid_user", "password": "wrong_password"},
    )
    assert res_json.status_code == 401
    assert res_json.json()["success"] is False


def test_logout_flow(client_isolated: TestClient):
    """Verifica el flujo completo de cierre de sesión y bloqueo posterior."""
    # Iniciar sesión
    client_isolated.post("/login", data={"username": "admin", "password": "monitor2026"})
    assert client_isolated.get("/api/status").status_code == 200

    # Cerrar sesión
    res_logout = client_isolated.get("/logout", follow_redirects=False)
    assert res_logout.status_code == 303
    assert res_logout.headers.get("location") == "/login"

    # Verificar que los endpoints protegidos vuelven a responder 401
    res_status = client_isolated.get("/api/status")
    assert res_status.status_code == 401

    res_root = client_isolated.get("/", follow_redirects=False)
    assert res_root.status_code == 303
    assert res_root.headers.get("location") == "/login"


def test_websocket_unauthenticated(client_isolated: TestClient):
    """Verifica que el WebSocket rechace conexiones sin sesión con código 1008."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client_isolated.websocket_connect("/ws/realtime"):
            pass
    assert exc_info.value.code == 1008


# ==============================================================================
# PRUEBAS DE ENDPOINTS DE NEGOCIO Y TELEMETRÍA (AUTENTICADOS)
# ==============================================================================
def test_serve_index(auth_client: TestClient):
    """Verifica que GET / sirva la página HTML del dashboard para usuario autenticado."""
    response = auth_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Monitor Energético" in response.text
    assert "Tiempo Real" in response.text
    assert "Cerrar Sesión" in response.text
    assert "/static/vendor/tailwind.js" in response.text
    assert "/static/vendor/chart.umd.min.js" in response.text
    assert "https://cdn.tailwindcss.com" not in response.text


def test_api_status(auth_client: TestClient):
    """Verifica GET /api/status con métricas del sistema operativo y base de datos."""
    response = auth_client.get("/api/status")
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


def test_api_readings(auth_client: TestClient):
    """Verifica la consulta paginada de lecturas con filtros."""
    response = auth_client.get("/api/readings?page=1&page_size=50")
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

    res_c1 = auth_client.get("/api/readings?circuit=circ_01")
    assert res_c1.status_code == 200
    data_c1 = res_c1.json()
    assert data_c1["total"] == 1
    assert data_c1["records"][0]["circuit_id"] == "circ_01"


def test_api_history(auth_client: TestClient):
    """Verifica agregados históricos y costo estimado."""
    response = auth_client.get("/api/history?period=daily")
    assert response.status_code == 200
    data = response.json()

    assert data["period"] == "daily"
    assert "total_kwh" in data
    assert data["total_kwh"] > 0
    assert "estimated_cost" in data
    assert "currency" in data
    assert "by_circuit" in data
    assert "time_series" in data


def test_api_alerts(auth_client: TestClient):
    """Verifica la consulta del listado de alertas."""
    response = auth_client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert "alerts" in data
    assert isinstance(data["alerts"], list)


def test_api_config_get_and_post(auth_client: TestClient):
    """Verifica consulta y modificación de tarifa y límites de potencia."""
    get_res = auth_client.get("/api/config")
    assert get_res.status_code == 200
    cfg = get_res.json()
    assert "tariff" in cfg
    assert "alert_thresholds" in cfg

    post_res = auth_client.post(
        "/api/config",
        json={"base_rate_per_kwh": 0.22, "max_instant_power_w": 4500.0},
    )
    assert post_res.status_code == 200
    res_data = post_res.json()
    assert res_data["success"] is True

    get_res2 = auth_client.get("/api/config")
    cfg2 = get_res2.json()
    assert cfg2["tariff"]["base_rate_per_kwh"] == 0.22
    assert cfg2["alert_thresholds"]["max_instant_power_w"] == 4500.0


def test_api_export_csv_and_reimport(auth_client: TestClient):
    """Verifica la exportación profesional en español (UTF-8-SIG, punto y coma) y su reimportación."""
    response = auth_client.get("/api/export/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "lecturas_energia.csv" in response.headers.get("content-disposition", "")

    # 1. Verificar BOM UTF-8 (bytes iniciales)
    raw_content = response.content
    assert raw_content.startswith(b"\xef\xbb\xbf")

    # 2. Decodificar texto con utf-8-sig
    text_content = raw_content.decode("utf-8-sig")
    lines = [line.strip() for line in text_content.splitlines() if line.strip()]
    assert len(lines) >= 3  # Encabezado + 2 filas

    # 3. Encabezados en español con delimitador punto y coma
    expected_header = "ID;Fecha y Hora;ID Circuito;Circuito;Voltaje (V);Corriente (A);Potencia (W);Energía (kWh)"
    assert lines[0] == expected_header

    # 4. Verificar tildes intactas y formato en filas
    assert "Iluminación" in text_content or "circ_02" in text_content
    row_parts = lines[1].split(";")
    assert len(row_parts) == 8
    assert row_parts[2] == "circ_01"
    # Voltaje 2 decimales, corriente 3 decimales, potencia 2 decimales, energía 6 decimales
    assert "." in row_parts[4]
    assert len(row_parts[4].split(".")[1]) == 2
    assert len(row_parts[5].split(".")[1]) == 3
    assert len(row_parts[6].split(".")[1]) == 2
    assert len(row_parts[7].split(".")[1]) == 6

    # 5. Probar re-importación del archivo exportado vía POST /api/import
    files = {"file": ("export_reimport.csv", io.BytesIO(raw_content), "text/csv")}
    res_import = auth_client.post("/api/import", files=files)
    assert res_import.status_code == 200
    import_data = res_import.json()
    assert import_data["success"] is True
    assert import_data["imported_count"] == 2
    assert import_data["error_count"] == 0


def test_api_seed_endpoint(auth_client: TestClient, monkeypatch):
    """Verifica la ejecución del generador de datos aleatorios vía POST /api/seed."""
    dummy_result = {
        "days": 15,
        "interval_minutes": 15,
        "total_inserted": 50,
        "daily_averages_kwh": {"c1": 1.5, "c2": 0.8},
    }
    monkeypatch.setattr("src.web.app.seed_data", lambda **kwargs: dummy_result)

    response = auth_client.post("/api/seed")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["result"]["total_inserted"] == 50


def test_api_import_invalid_file(auth_client: TestClient):
    """Verifica que rechace archivos con extensiones no soportadas."""
    file_content = b"invalid content"
    files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    response = auth_client.post("/api/import", files=files)
    assert response.status_code == 400


def test_api_realtime_endpoint(auth_client: TestClient):
    """Verifica GET /api/realtime para fallback REST con telemetría de circuitos."""
    response = auth_client.get("/api/realtime")
    assert response.status_code == 200
    data = response.json()

    assert "collector_connected" in data
    assert "transport" in data
    assert "total_power_w" in data
    assert "latest_by_circuit" in data
    assert "max_instant_power_w" in data

    circuits = data["latest_by_circuit"]
    assert "circ_01" in circuits
    assert circuits["circ_01"]["power_w"] == 180.0
    assert "voltage_v" in circuits["circ_01"]
    assert "current_a" in circuits["circ_01"]


def test_websocket_realtime(auth_client: TestClient):
    """Verifica conexión WebSocket /ws/realtime autenticada recibiendo welcome y lecturas."""
    with auth_client.websocket_connect("/ws/realtime") as websocket:
        welcome_msg = websocket.receive_json()
        assert welcome_msg["type"] == "welcome"
        assert "collector_connected" in welcome_msg["data"]
        assert "max_instant_power_w" in welcome_msg["data"]

        reading_msg = websocket.receive_json()
        assert reading_msg["type"] == "reading"
        assert "circuit_id" in reading_msg["data"]
        assert "voltage_v" in reading_msg["data"]
        assert "current_a" in reading_msg["data"]


def test_api_circuits_crud(auth_client: TestClient):
    """Verifica listar, crear y eliminar circuitos dinámicamente y los valores canónicos de perfiles."""
    # 1. GET /api/circuits
    res_get = auth_client.get("/api/circuits")
    assert res_get.status_code == 200
    circuits = res_get.json()
    assert isinstance(circuits, list)
    initial_count = len(circuits)
    assert initial_count >= 1

    # Verificar que los 5 circuitos por defecto tienen los valores canónicos reales
    c_map = {c["id"]: c for c in circuits}
    if "circ_01" in c_map:
        assert c_map["circ_01"]["min_power_w"] == 120.0
        assert c_map["circ_01"]["max_power_w"] == 180.0
        assert c_map["circ_01"]["daily_kwh_target"] == 1.5
    if "circ_02" in c_map:
        assert c_map["circ_02"]["min_power_w"] == 60.0
        assert c_map["circ_02"]["max_power_w"] == 180.0
        assert c_map["circ_02"]["daily_kwh_target"] == 0.9
    if "circ_03" in c_map:
        assert c_map["circ_03"]["min_power_w"] == 900.0
        assert c_map["circ_03"]["max_power_w"] == 1500.0
        assert c_map["circ_03"]["daily_kwh_target"] == 6.0
    if "circ_04" in c_map:
        assert c_map["circ_04"]["min_power_w"] == 400.0
        assert c_map["circ_04"]["max_power_w"] == 700.0
        assert c_map["circ_04"]["daily_kwh_target"] == 1.0
    if "circ_05" in c_map:
        assert c_map["circ_05"]["min_power_w"] == 40.0
        assert c_map["circ_05"]["max_power_w"] == 350.0
        assert c_map["circ_05"]["daily_kwh_target"] == 1.6

    # 2. POST /api/circuits - Crear nuevo circuito
    payload = {
        "name": "Televisor Sala",
        "location": "Sala",
        "min_power_w": 30.0,
        "max_power_w": 180.0,
        "nominal_power_w": 150.0,
        "daily_kwh_target": 1.1,
    }
    res_post = auth_client.post("/api/circuits", json=payload)
    assert res_post.status_code == 200
    created_data = res_post.json()
    assert created_data["success"] is True
    new_circuit = created_data["circuit"]
    assert new_circuit["name"] == "Televisor Sala"
    assert new_circuit["id"].startswith("circ_")
    assert new_circuit["min_power_w"] == 30.0
    assert new_circuit["max_power_w"] == 180.0
    assert new_circuit["daily_kwh_target"] == 1.1
    new_id = new_circuit["id"]

    # Verificar que aparece en GET con sus propiedades exactas
    res_get2 = auth_client.get("/api/circuits")
    c_ids = [c["id"] for c in res_get2.json()]
    assert new_id in c_ids
    found = next(c for c in res_get2.json() if c["id"] == new_id)
    assert found["min_power_w"] == 30.0
    assert found["max_power_w"] == 180.0
    assert found["daily_kwh_target"] == 1.1

    # 3. DELETE /api/circuits/{circuit_id}
    res_del = auth_client.delete(f"/api/circuits/{new_id}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Verificar que ya no está
    res_get3 = auth_client.get("/api/circuits")
    c_ids3 = [c["id"] for c in res_get3.json()]
    assert new_id not in c_ids3

    # 4. DELETE inexistente -> 404
    res_del_404 = auth_client.delete("/api/circuits/circ_9999")
    assert res_del_404.status_code == 404
