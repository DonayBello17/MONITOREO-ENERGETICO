"""Pruebas unitarias para el cálculo de costos de energía y detección de anomalías."""

from datetime import datetime
import pytest

from src.dashboard.anomaly_detector import compute_mean_and_std, is_consumption_anomaly
from src.dashboard.cost_calculator import (
    calculate_fixed_cost,
    calculate_projected_monthly,
    calculate_tiered_cost,
    calculate_time_of_use_cost,
)


def test_fixed_cost_calculation():
    """Valida el cálculo elemental de costo bajo tarifa plana (kWh * tarifa)."""
    # 100 kWh a $0.15/kWh = $15.00
    assert calculate_fixed_cost(100.0, 0.15) == 15.0
    # Consumo nulo o negativo
    assert calculate_fixed_cost(0.0, 0.20) == 0.0
    assert calculate_fixed_cost(-10.0, 0.20) == 0.0
    # Tarifa con decimales
    assert calculate_fixed_cost(234.56, 0.185) == 43.39


def test_time_of_use_and_tiered_cost_calculation():
    """Valida el cálculo de costos bajo esquema de tarifas por horarios (TOU) y por escalones."""
    # 1. Tarifa por horarios
    tou_rates = [
        {"name": "Valle", "rate_per_kwh": 0.08, "start_time": "00:00", "end_time": "08:00"},
        {"name": "Llano", "rate_per_kwh": 0.14, "start_time": "08:00", "end_time": "18:00"},
        {"name": "Punta", "rate_per_kwh": 0.22, "start_time": "18:00", "end_time": "24:00"},
    ]

    # Timestamp a las 04:00 (Valle, 10 kWh)
    t_valle = datetime(2026, 11, 23, 4, 0, 0).timestamp()
    # Timestamp a las 14:00 (Llano, 10 kWh)
    t_llano = datetime(2026, 11, 23, 14, 0, 0).timestamp()
    # Timestamp a las 20:00 (Punta, 10 kWh)
    t_punta = datetime(2026, 11, 23, 20, 0, 0).timestamp()

    intervals = [
        (t_valle, 10.0),  # 10 * 0.08 = 0.80
        (t_llano, 10.0),  # 10 * 0.14 = 1.40
        (t_punta, 10.0),  # 10 * 0.22 = 2.20
    ]
    # Total esperado: 0.80 + 1.40 + 2.20 = 4.40
    cost_tou = calculate_time_of_use_cost(intervals, tou_rates, base_rate=0.15)
    assert cost_tou == 4.40

    # 2. Tarifa por escalones (Tiered)
    tiers = [
        {"limit_kwh": 100.0, "rate_per_kwh": 0.10},  # Primeros 100 kWh a 0.10
        {"limit_kwh": 250.0, "rate_per_kwh": 0.15},  # Siguientes 150 kWh a 0.15
        {"limit_kwh": None, "rate_per_kwh": 0.25},   # Excedente a 0.25
    ]
    # Consumo total de 300 kWh:
    # 100 * 0.10 = $10.0
    # 150 * 0.15 = $22.5
    #  50 * 0.25 = $12.5
    # Total: $45.0
    assert calculate_tiered_cost(300.0, tiers) == 45.0

    # Consumo de 50 kWh (solo primer escalón): 50 * 0.10 = $5.0
    assert calculate_tiered_cost(50.0, tiers) == 5.0

    # 3. Proyección a fin de mes
    # 100 kWh en 10 días de un mes de 30 días -> 300 kWh proyectados a $0.15 = $45.00
    proj_kwh, proj_cost = calculate_projected_monthly(100.0, day_of_month=10, days_in_month=30, rate_per_kwh=0.15)
    assert proj_kwh == 300.0
    assert proj_cost == 45.0


def test_anomaly_detection_triggers_above_two_sigmas():
    """Verifica que una lectura que supere la media en más de 2 desviaciones estándar sea detectada como anomalía."""
    # Muestra histórica con media ~150W y desviación estándar de ~10W
    historical_powers = [140.0, 150.0, 160.0, 145.0, 155.0, 148.0, 152.0]
    mean, std = compute_mean_and_std(historical_powers)
    assert 145.0 <= mean <= 155.0

    # Una lectura normal dentro de 2 sigmas (ej. 165W)
    is_anom, _, _ = is_consumption_anomaly(165.0, historical_powers, threshold_sigmas=2.0)
    assert is_anom is False

    # Una lectura que supere ampliamente 2 sigmas (ej. 400W vs media ~150W + 2*10W = ~170W)
    is_anom, m, s = is_consumption_anomaly(400.0, historical_powers, threshold_sigmas=2.0)
    assert is_anom is True
    assert m == mean


def test_anomaly_detection_normal_distribution_bounds():
    """Verifica que lecturas dentro de la distribución normal histórica no generen falsos positivos."""
    # Valores de consumo de refrigerador (alrededor de 150W con variación natural)
    historical_powers = [148.0, 152.0, 150.0, 149.0, 151.0, 153.0, 147.0]

    # Valores normales cercanos a la media
    for val in [145.0, 150.0, 155.0]:
        is_anom, _, _ = is_consumption_anomaly(val, historical_powers, threshold_sigmas=2.0)
        assert is_anom is False

    # Verificación de muestra insuficiente (menos de 3 registros no deben disparar falso positivo)
    is_anom, _, _ = is_consumption_anomaly(500.0, [150.0, 155.0], threshold_sigmas=2.0)
    assert is_anom is False
