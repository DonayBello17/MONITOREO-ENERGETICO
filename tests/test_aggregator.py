"""Pruebas unitarias para el trabajador de agregación estadística (AggregatorWorker)."""

import time
import pytest

from src.collector.aggregator import AggregatorWorker
from src.common.database import DatabaseManager
from src.common.models import Circuit, Reading


@pytest.fixture
def db_with_data():
    """Base de datos en memoria con circuito y lecturas cargadas para prueba de agregación."""
    db = DatabaseManager(db_path=":memory:")
    c = Circuit(id="c1", name="Nevera", location="Cocina", nominal_power_w=300.0)
    db.upsert_circuit(c)

    # Insertar lecturas de prueba
    base_ts = 1700000000.0
    readings = [
        Reading(timestamp=base_ts + i * 60, circuit_id="c1", voltage=120.0, current=1.0, power_w=120.0, energy_kwh=0.01 * i)
        for i in range(10)
    ]
    db.insert_readings_batch(readings)
    yield db
    db.close()


def test_aggregator_run_and_manual_trigger(db_with_data):
    """Verifica la ejecución manual y el cálculo de agregados con AggregatorWorker."""
    worker = AggregatorWorker(db_manager=db_with_data, interval_seconds=3600.0)

    # Ejecución directa del método de agregación
    stats = worker.run_aggregation()
    assert stats["status"] == "OK"
    assert stats["hourly_updated"] >= 1
    assert stats["daily_updated"] >= 1
    assert stats["monthly_updated"] >= 1

    # Iniciar hilo de trabajo en segundo plano
    worker.start()
    assert worker.is_alive is True

    # Disparar agregación manual inmediata
    triggered = worker.trigger_immediate()
    assert triggered is True

    time.sleep(0.2)
    assert worker.last_run_timestamp is not None
    assert worker.last_run_stats.get("status") == "OK"

    # Detener trabajador
    worker.stop(timeout=2.0)
    assert worker.is_alive is False
