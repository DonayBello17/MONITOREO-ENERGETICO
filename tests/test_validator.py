"""Pruebas unitarias para el validador de telemetría (ReadingValidator)."""

import time
import pytest
from src.collector.validator import ReadingValidator
from src.common.models import Reading


@pytest.fixture
def validator():
    """Instancia limpia de ReadingValidator para cada prueba."""
    val = ReadingValidator()
    val.clear_cache()
    return val


def test_valid_reading(validator):
    """Verifica que una lectura estándar con parámetros físicos coherentes sea aceptada."""
    reading = Reading(
        timestamp=time.time(),
        circuit_id="circ_01",
        voltage=120.5,
        current=1.25,
        power_w=150.0,
        energy_kwh=0.05,
    )
    is_valid, reason = validator.check_reading(reading)
    assert is_valid is True
    assert reason is None
    assert validator.validate(reading) is True


def test_voltage_out_of_range(validator):
    """Verifica que voltajes fuera del rango [80V - 260V] sean rechazados."""
    ts = time.time()

    # Voltaje por debajo del mínimo (ej. 60V)
    under_voltage = Reading(
        timestamp=ts,
        circuit_id="circ_01",
        voltage=60.0,
        current=1.0,
        power_w=60.0,
        energy_kwh=0.1,
    )
    assert validator.validate(under_voltage) is False
    is_valid, reason = validator.check_reading(under_voltage)
    assert is_valid is False
    assert "Voltaje fuera del rango" in reason

    # Voltaje por encima del máximo (ej. 280V)
    over_voltage = Reading(
        timestamp=ts + 1,
        circuit_id="circ_01",
        voltage=280.0,
        current=1.0,
        power_w=280.0,
        energy_kwh=0.1,
    )
    assert validator.validate(over_voltage) is False
    is_valid, reason = validator.check_reading(over_voltage)
    assert is_valid is False
    assert "Voltaje fuera del rango" in reason


def test_null_or_negative_values(validator):
    """Verifica el descarte de lecturas con valores nulos, negativos o inconsistentes."""
    ts = time.time()

    # Lectura nula completa
    assert validator.validate(None) is False

    # Corriente negativa
    neg_current = Reading(
        timestamp=ts,
        circuit_id="circ_01",
        voltage=120.0,
        current=-2.5,
        power_w=100.0,
        energy_kwh=0.1,
    )
    assert validator.validate(neg_current) is False
    assert "Corriente negativa" in validator.check_reading(neg_current)[1]

    # Potencia negativa
    neg_power = Reading(
        timestamp=ts + 1,
        circuit_id="circ_01",
        voltage=120.0,
        current=1.5,
        power_w=-50.0,
        energy_kwh=0.1,
    )
    assert validator.validate(neg_power) is False
    assert "Potencia activa negativa" in validator.check_reading(neg_power)[1]

    # Energía acumulada negativa
    neg_energy = Reading(
        timestamp=ts + 2,
        circuit_id="circ_01",
        voltage=120.0,
        current=1.0,
        power_w=120.0,
        energy_kwh=-0.5,
    )
    assert validator.validate(neg_energy) is False
    assert "Energía acumulada negativa" in validator.check_reading(neg_energy)[1]

    # Campo nulo (None)
    class DummyReading:
        def __init__(self):
            self.circuit_id = "circ_01"
            self.timestamp = ts + 3
            self.voltage = None
            self.current = 1.0
            self.power_w = 100.0
            self.energy_kwh = 0.1

    assert validator.validate(DummyReading()) is False
    assert "valor nulo" in validator.check_reading(DummyReading())[1]

    # Potencia inconsistente con corriente nula
    inconsistent_power = Reading(
        timestamp=ts + 4,
        circuit_id="circ_01",
        voltage=120.0,
        current=0.0,
        power_w=500.0,  # 500W con 0 amperios
        energy_kwh=0.1,
    )
    assert validator.validate(inconsistent_power) is False
    assert "inconsistente" in validator.check_reading(inconsistent_power)[1].lower()


def test_duplicate_detection(validator):
    """Verifica que lecturas repetidas para el mismo circuito y timestamp se detecten y descarten."""
    ts = 1700000000.123
    r1 = Reading(
        timestamp=ts,
        circuit_id="circ_01",
        voltage=120.0,
        current=1.0,
        power_w=120.0,
        energy_kwh=1.0,
    )

    # La primera vez debe ser válida
    assert validator.validate(r1) is True

    # La segunda vez con exactamente el mismo circuit_id y timestamp debe ser rechazada
    r1_duplicate = Reading(
        timestamp=ts,
        circuit_id="circ_01",
        voltage=121.0,
        current=1.1,
        power_w=130.0,
        energy_kwh=1.0,
    )
    assert validator.validate(r1_duplicate) is False
    is_valid, reason = validator.check_reading(r1_duplicate)
    assert is_valid is False
    assert "duplicada" in reason.lower()

    # Mismo timestamp pero distinto circuito: debe ser válida
    r2_other_circuit = Reading(
        timestamp=ts,
        circuit_id="circ_02",
        voltage=120.0,
        current=1.0,
        power_w=120.0,
        energy_kwh=1.0,
    )
    assert validator.validate(r2_other_circuit) is True

    # Mismo circuito pero timestamp posterior: debe ser válida
    r3_next_time = Reading(
        timestamp=ts + 2.0,
        circuit_id="circ_01",
        voltage=120.0,
        current=1.0,
        power_w=120.0,
        energy_kwh=1.01,
    )
    assert validator.validate(r3_next_time) is True
