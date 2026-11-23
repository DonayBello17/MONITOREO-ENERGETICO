"""Pruebas unitarias para el gestor de base de datos SQLite y el modelo de datos.

Verifica la correcta inicialización con SQLite WAL, inserción en lote de lecturas,
consultas por rango, cálculo de agregaciones estadísticas y política de retención.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.common.database import DatabaseManager
from src.common.models import Alert, Circuit, Reading


@pytest.fixture
def db(tmp_path: Path) -> DatabaseManager:
    """Fixture que proporciona una instancia aislada de DatabaseManager en disco temporal."""
    db_file = tmp_path / "test_energy_monitor.db"
    manager = DatabaseManager(db_path=db_file)
    yield manager
    manager.close()


def test_database_initialization(db: DatabaseManager) -> None:
    """Prueba 1: Verifica la creación de todas las tablas, índices y activación de modo WAL."""
    conn = db.get_connection()

    # Verificar modo WAL
    cursor = conn.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    assert mode.lower() == "wal", f"Se esperaba modo WAL, pero se obtuvo {mode}"

    # Verificar tablas creadas
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    expected_tables = {
        "circuits",
        "readings",
        "hourly_aggregates",
        "daily_aggregates",
        "monthly_aggregates",
        "alerts",
    }
    assert expected_tables.issubset(tables), f"Faltan tablas: {expected_tables - tables}"

    # Verificar existencia de índices clave para escala
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_readings_circuit_timestamp" in indexes
    assert "idx_readings_timestamp" in indexes


def test_batch_insert_readings(db: DatabaseManager) -> None:
    """Prueba 2: Verifica la inserción en lote (executemany) de lecturas."""
    # Crear circuito previo por integridad referencial
    circuit = Circuit(
        id="c_test",
        name="Circuito Prueba",
        location="Laboratorio",
        nominal_power_w=1000.0,
    )
    db.upsert_circuit(circuit)

    # Generar lote de 500 lecturas
    base_time = 1700000000.0
    readings = []
    for i in range(500):
        readings.append(
            Reading(
                timestamp=base_time + (i * 2.0),
                circuit_id="c_test",
                voltage=120.0 + (i % 5),
                current=2.0 + (i % 3),
                power_w=240.0 + (i * 2),
                energy_kwh=0.000133,
            )
        )

    count = db.insert_readings_batch(readings)
    assert count == 500

    stored = db.get_readings(circuit_id="c_test")
    assert len(stored) == 500
    assert stored[0].timestamp == base_time
    assert stored[-1].timestamp == base_time + (499 * 2.0)


def test_query_readings_by_range_and_filters(db: DatabaseManager) -> None:
    """Prueba 3: Verifica la consulta de lecturas por rango temporal, circuito y límite."""
    db.upsert_circuits([
        Circuit(id="c1", name="Nevera", location="Cocina", nominal_power_w=300.0),
        Circuit(id="c2", name="Clima", location="Sala", nominal_power_w=2000.0),
    ])

    base_time = 1700000000.0
    readings = [
        Reading(timestamp=base_time + 10, circuit_id="c1", voltage=120.0, current=1.0, power_w=120.0, energy_kwh=0.01),
        Reading(timestamp=base_time + 20, circuit_id="c2", voltage=120.0, current=5.0, power_w=600.0, energy_kwh=0.05),
        Reading(timestamp=base_time + 30, circuit_id="c1", voltage=120.0, current=1.2, power_w=144.0, energy_kwh=0.012),
        Reading(timestamp=base_time + 40, circuit_id="c2", voltage=120.0, current=5.2, power_w=624.0, energy_kwh=0.052),
        Reading(timestamp=base_time + 50, circuit_id="c1", voltage=120.0, current=1.1, power_w=132.0, energy_kwh=0.011),
    ]
    db.insert_readings_batch(readings)

    # Filtrar solo c1
    c1_readings = db.get_readings(circuit_id="c1")
    assert len(c1_readings) == 3
    assert all(r.circuit_id == "c1" for r in c1_readings)

    # Filtrar por rango [base_time + 20, base_time + 40]
    range_readings = db.get_readings(start_time=base_time + 20, end_time=base_time + 40)
    assert len(range_readings) == 3
    assert [r.timestamp for r in range_readings] == [base_time + 20, base_time + 30, base_time + 40]

    # Filtrar con limit
    limited = db.get_readings(limit=2)
    assert len(limited) == 2


def test_hourly_and_daily_aggregations(db: DatabaseManager) -> None:
    """Prueba 4: Verifica el cálculo de agregados horarios y diarios con cálculos exactos."""
    db.upsert_circuit(Circuit(id="c1", name="Nevera", location="Cocina", nominal_power_w=300.0))

    # Definir una hora exacta: 2023-11-14 22:00:00 UTC (1699999200)
    hour_start = 1699999200.0
    day_start = (int(hour_start) // 86400) * 86400.0

    readings = [
        # 3 lecturas dentro de la misma hora
        Reading(timestamp=hour_start + 100, circuit_id="c1", voltage=120.0, current=1.0, power_w=100.0, energy_kwh=0.05),
        Reading(timestamp=hour_start + 200, circuit_id="c1", voltage=120.0, current=2.0, power_w=200.0, energy_kwh=0.10),
        Reading(timestamp=hour_start + 300, circuit_id="c1", voltage=120.0, current=3.0, power_w=300.0, energy_kwh=0.15),
    ]
    db.insert_readings_batch(readings)

    # Ejecutar agregación horaria
    hourly_rows = db.calculate_hourly_aggregates()
    assert hourly_rows >= 1

    hourly_aggs = db.get_aggregates(period_type="hourly", circuit_id="c1")
    assert len(hourly_aggs) == 1
    agg = hourly_aggs[0]
    assert agg.period_start == hour_start
    assert agg.circuit_id == "c1"
    assert agg.avg_power_w == pytest.approx(200.0)
    assert agg.min_power_w == pytest.approx(100.0)
    assert agg.max_power_w == pytest.approx(300.0)
    assert agg.total_energy_kwh == pytest.approx(0.30, abs=1e-4)
    assert agg.reading_count == 3

    # Ejecutar agregación diaria
    daily_rows = db.calculate_daily_aggregates()
    assert daily_rows >= 1

    daily_aggs = db.get_aggregates(period_type="daily", circuit_id="c1")
    assert len(daily_aggs) == 1
    d_agg = daily_aggs[0]
    assert d_agg.period_start == day_start
    assert d_agg.avg_power_w == pytest.approx(200.0)
    assert d_agg.total_energy_kwh == pytest.approx(0.30, abs=1e-4)
    assert d_agg.reading_count == 3


def test_retention_policy_cleanup(db: DatabaseManager) -> None:
    """Prueba 5: Verifica la purga de lecturas crudas y agregados según la política de retención."""
    db.upsert_circuit(Circuit(id="c1", name="General", location="Entrada", nominal_power_w=5000.0))

    now = 1700000000.0
    day_seconds = 86400.0

    # Lectura muy antigua: hace 35 días (debe eliminarse con retención de 30 días)
    old_reading = Reading(
        timestamp=now - (35 * day_seconds),
        circuit_id="c1",
        voltage=120.0,
        current=1.0,
        power_w=100.0,
        energy_kwh=0.01,
    )
    # Lectura reciente: hace 5 días (debe conservarse)
    recent_reading = Reading(
        timestamp=now - (5 * day_seconds),
        circuit_id="c1",
        voltage=120.0,
        current=1.0,
        power_w=100.0,
        energy_kwh=0.01,
    )
    db.insert_readings_batch([old_reading, recent_reading])

    # Insertar agregado muy antiguo (> 730 días, p. ej. 800 días)
    conn = db.get_connection()
    old_agg_time = now - (800 * day_seconds)
    recent_agg_time = now - (100 * day_seconds)
    with conn:
        conn.execute(
            """INSERT INTO hourly_aggregates
               (period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (old_agg_time, "c1", 100.0, 100.0, 100.0, 1.0, 10),
        )
        conn.execute(
            """INSERT INTO hourly_aggregates
               (period_start, circuit_id, avg_power_w, min_power_w, max_power_w, total_energy_kwh, reading_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (recent_agg_time, "c1", 100.0, 100.0, 100.0, 1.0, 10),
        )

    # Insertar alerta atendida antigua y alerta no atendida
    old_alert_id = db.insert_alert(
        Alert(
            timestamp=now - (40 * day_seconds),
            circuit_id="c1",
            alert_type="OVERPOWER",
            severity="WARNING",
            message="Sobrecarga antigua",
            is_acknowledged=True,
        )
    )
    recent_alert_id = db.insert_alert(
        Alert(
            timestamp=now - (2 * day_seconds),
            circuit_id="c1",
            alert_type="OVERPOWER",
            severity="CRITICAL",
            message="Sobrecarga reciente",
            is_acknowledged=False,
        )
    )

    # Aplicar política de retención
    result = db.apply_retention_policy(
        raw_days=30,
        aggregates_days=730,
        reference_time=now,
    )

    assert result["readings_deleted"] == 1
    assert result["hourly_deleted"] == 1
    assert result["alerts_deleted"] == 1

    # Verificar que las lecturas y agregados recientes persisten
    remaining_readings = db.get_readings()
    assert len(remaining_readings) == 1
    assert remaining_readings[0].timestamp == pytest.approx(recent_reading.timestamp)

    remaining_hourly = db.get_aggregates(period_type="hourly")
    assert len(remaining_hourly) == 1
    assert remaining_hourly[0].period_start == pytest.approx(recent_agg_time)

    remaining_alerts = db.get_alerts()
    assert any(a.id == recent_alert_id for a in remaining_alerts)
    assert not any(a.id == old_alert_id for a in remaining_alerts)


def test_circuits_and_alerts_crud(db: DatabaseManager) -> None:
    """Prueba 6: Verifica operaciones CRUD de circuitos y ciclo de vida de alertas."""
    # Circuitos
    c = Circuit(id="c_air", name="Aire", location="Dormitorio", nominal_power_w=1500.0, icon="fan")
    db.upsert_circuit(c)
    circuits = db.get_circuits()
    assert len(circuits) == 1
    assert circuits[0].name == "Aire"

    # Actualizar circuito
    c.nominal_power_w = 1800.0
    db.upsert_circuit(c)
    circuits_updated = db.get_circuits()
    assert circuits_updated[0].nominal_power_w == 1800.0

    # Alertas
    alert = Alert(
        timestamp=time.time(),
        circuit_id="c_air",
        alert_type="HIGH_CONSUMPTION",
        severity="WARNING",
        message="Consumo elevado detectado",
        value=2100.0,
        threshold=1800.0,
    )
    alert_id = db.insert_alert(alert)
    assert alert_id > 0

    unack = db.get_alerts(unacknowledged_only=True)
    assert len(unack) == 1
    assert unack[0].id == alert_id
    assert not unack[0].is_acknowledged

    success = db.acknowledge_alert(alert_id)
    assert success is True

    unack_after = db.get_alerts(unacknowledged_only=True)
    assert len(unack_after) == 0


def test_database_filesystem_resilience(tmp_path: Path, monkeypatch) -> None:
    """Verifica que DatabaseManager maneje fallos de disco y permisos sin abortar (SO-10)."""
    import sqlite3

    # 1. Fallo al crear directorio por permisos denegados -> Conmuta a :memory:
    def mock_mkdir_fail(self, *args, **kwargs):
        raise PermissionError("Permiso denegado para crear directorio de BD")

    with monkeypatch.context() as m:
        m.setattr(Path, "mkdir", mock_mkdir_fail)
        db_fallback = DatabaseManager(db_path=tmp_path / "unwritable" / "db.sqlite")
        assert db_fallback.db_path == ":memory:"

        # La base de datos en memoria debe operar con normalidad
        c = Circuit(id="c_fallback", name="Respaldo", location="Memoria", nominal_power_w=500.0)
        db_fallback.upsert_circuit(c)
        assert len(db_fallback.get_circuits()) == 1
        db_fallback.close()

    # 2. Simulación de disco lleno (sqlite3.OperationalError) durante inserción en lote
    db_mem = DatabaseManager(db_path=":memory:")
    c = Circuit(id="c_mem", name="Test", location="Mem", nominal_power_w=100.0)
    db_mem.upsert_circuit(c)

    sample_reading = Reading(
        timestamp=1700000000.0,
        circuit_id="c_mem",
        voltage=120.0,
        current=1.0,
        power_w=120.0,
        energy_kwh=0.01,
    )

    from unittest.mock import MagicMock
    mock_conn = MagicMock()
    mock_conn.executemany.side_effect = sqlite3.OperationalError("database or disk is full")
    with monkeypatch.context() as m:
        m.setattr(db_mem, "get_connection", lambda: mock_conn)
        # insert_readings_batch no debe provocar cierre abrupto, debe retornar 0
        inserted = db_mem.insert_readings_batch([sample_reading])
        assert inserted == 0

    db_mem.close()
