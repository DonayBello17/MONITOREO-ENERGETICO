"""Pruebas unitarias para el simulador de telemetría energética (EnergySimulator)."""

from datetime import datetime
import pytest

from src.collector.simulator import DataSourceError, EnergySimulator
from src.common.models import Circuit


def test_generation_of_circuits():
    """Verifica que el simulador genere lecturas completas para los 5 circuitos configurados."""
    sim = EnergySimulator()
    readings = sim.generate_readings()

    # Verificar que se generen exactamente 5 circuitos
    assert len(readings) == 5

    circuit_ids = {r.circuit_id for r in readings}
    expected_ids = {"circ_01", "circ_02", "circ_03", "circ_04", "circ_05"}
    assert circuit_ids == expected_ids

    # Verificar que los campos no estén vacíos
    for r in readings:
        assert r.timestamp > 0
        assert r.voltage > 100.0
        assert r.current >= 0.0
        assert r.power_w >= 0.0
        assert r.energy_kwh >= 0.0


def test_consistent_power_and_energy_calculation():
    """Verifica la consistencia física entre voltaje, corriente, potencia y acumulación de energía."""
    sim = EnergySimulator(base_voltage=120.0, seed=42)

    # 1. Primera lectura en t=1000.0
    t0 = 1700000000.0
    readings_t0 = sim.generate_readings(timestamp=t0)

    for r in readings_t0:
        # El voltaje debe fluctuar alrededor de 120V
        assert 110.0 <= r.voltage <= 130.0

        # Consistencia de corriente y potencia: P <= V * I * 1.25 + 5
        apparent = r.voltage * r.current
        assert r.power_w <= (apparent * 1.25 + 5.0)

    # 2. Segunda lectura tras un intervalo de tiempo (ej. 3600 segundos = 1 hora)
    t1 = t0 + 3600.0
    readings_t1 = sim.generate_readings(timestamp=t1)

    # La energía acumulada debe haber aumentado para los circuitos activos
    for r1 in readings_t1:
        r0 = next(r for r in readings_t0 if r.circuit_id == r1.circuit_id)
        if r1.power_w > 1.0:
            assert r1.energy_kwh > r0.energy_kwh, f"La energía de {r1.circuit_id} no aumentó tras 1 hora"


def test_cyclic_and_realistic_behavior():
    """Verifica el comportamiento cíclico por perfiles horarios y la inyección de fallos."""
    sim = EnergySimulator(seed=123)

    # 1. Perfil Nevera: ciclo de compresor ON (primeros minutos) vs OFF (minuto 20)
    # Ciclo period = 1800s, duty = 720s (12 min)
    t_nevera_on = 300.0  # 5 minutos dentro del ciclo -> ON
    t_nevera_off = 1000.0  # 16.6 minutos dentro del ciclo -> OFF

    readings_on = sim.generate_readings(timestamp=t_nevera_on)
    readings_off = sim.generate_readings(timestamp=t_nevera_off)

    nevera_on = next(r for r in readings_on if r.circuit_id == "circ_01")
    nevera_off = next(r for r in readings_off if r.circuit_id == "circ_01")

    # Compresor encendido (~130W-180W) vs reposo (~3W)
    assert nevera_on.power_w > 100.0, f"Potencia compresor ON muy baja: {nevera_on.power_w}"
    assert nevera_off.power_w < 15.0, f"Potencia compresor OFF muy alta: {nevera_off.power_w}"

    # 2. Perfil Iluminación: pico nocturno (20:00) vs madrugada (03:00)
    dt_madrugada = datetime(2026, 11, 23, 3, 0, 0).timestamp()
    dt_noche = datetime(2026, 11, 23, 20, 0, 0).timestamp()

    r_madrugada = next(r for r in sim.generate_readings(timestamp=dt_madrugada) if r.circuit_id == "circ_02")
    r_noche = next(r for r in sim.generate_readings(timestamp=dt_noche) if r.circuit_id == "circ_02")

    assert r_noche.power_w > 150.0, f"Potencia nocturna de iluminación muy baja: {r_noche.power_w}"
    assert r_madrugada.power_w < 30.0, f"Potencia de madrugada de iluminación muy alta: {r_madrugada.power_w}"

    # 3. Inyección de fallos
    assert sim.failure_injected is False
    sim.inject_fault(enabled=True, message="Sensor I2C desconectado")
    assert sim.failure_injected is True

    with pytest.raises(DataSourceError) as exc_info:
        sim.generate_readings()
    assert "Sensor I2C desconectado" in str(exc_info.value)

    # Restauración normal tras desactivar fallo
    sim.inject_fault(enabled=False)
    assert sim.failure_injected is False
    restored_readings = sim.generate_readings()
    assert len(restored_readings) == 5
