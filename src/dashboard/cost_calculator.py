"""Módulo de cálculo de costos de energía eléctrica y tarifas configurables.

Soporta:
- Tarifa fija: costo directo (kWh * tarifa base).
- Tarifa por horarios (Time-of-Use / TOU): según la franja horaria (Valle, Llano, Punta).
- Tarifa por rangos/escalones de consumo (Tiered rates).
- Proyección estimada de consumo y costo a fin de mes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def calculate_fixed_cost(energy_kwh: float, rate_per_kwh: float) -> float:
    """Calcula el costo con tarifa plana fija.

    Args:
        energy_kwh: Energía consumida en kilovatios-hora.
        rate_per_kwh: Tarifa unitaria por kWh.

    Returns:
        float: Costo total redondeado a 2 decimales.
    """
    if energy_kwh <= 0.0 or rate_per_kwh <= 0.0:
        return 0.0
    return round(energy_kwh * rate_per_kwh, 2)


def is_time_in_range(time_str: str, start_str: str, end_str: str) -> bool:
    """Verifica si una hora 'HH:MM' está dentro del rango [start_str, end_str).

    Soporta '24:00' como límite superior de fin de día.
    """
    # Normalizar 24:00
    if end_str == "24:00":
        end_str = "23:59:59"

    # Comparación lexicográfica directa para formato HH:MM
    if len(time_str) == 5 and len(start_str) == 5 and len(end_str) == 5:
        if start_str <= end_str:
            return start_str <= time_str < end_str
        else:
            # Rango que cruza la medianoche (ej. 22:00 a 06:00)
            return time_str >= start_str or time_str < end_str

    # Respaldo por componentes de tiempo
    try:
        t_parts = [int(p) for p in time_str.split(":")[:2]]
        s_parts = [int(p) for p in start_str.split(":")[:2]]
        e_parts = [int(p) for p in end_str.split(":")[:2]]

        t_min = t_parts[0] * 60 + t_parts[1]
        s_min = s_parts[0] * 60 + s_parts[1]
        e_min = e_parts[0] * 60 + e_parts[1]

        if s_min <= e_min:
            return s_min <= t_min < e_min
        else:
            return t_min >= s_min or t_min < e_min
    except Exception:
        return False


def get_rate_for_timestamp(
    timestamp: float,
    tou_rates: List[Dict[str, Any]],
    base_rate: float,
) -> Tuple[float, str]:
    """Determina la tarifa aplicable para un instante temporal según las reglas horarias.

    Returns:
        Tuple[float, str]: (tarifa_por_kwh, nombre_franja)
    """
    dt = datetime.fromtimestamp(timestamp)
    time_str = dt.strftime("%H:%M")

    for franja in tou_rates:
        start = franja.get("start_time", "00:00")
        end = franja.get("end_time", "24:00")
        if is_time_in_range(time_str, start, end):
            rate = float(franja.get("rate_per_kwh", base_rate))
            name = franja.get("name", "Horario")
            return rate, name

    return base_rate, "Base"


def calculate_time_of_use_cost(
    energy_by_interval: List[Tuple[float, float]],
    tou_rates: List[Dict[str, Any]],
    base_rate: float,
) -> float:
    """Calcula el costo total para un conjunto de consumos en distintos instantes temporales.

    Args:
        energy_by_interval: Lista de tuplas (timestamp_unix, delta_energia_kwh).
        tou_rates: Lista de configuraciones de franjas horarias con 'start_time', 'end_time', 'rate_per_kwh'.
        base_rate: Tarifa base en caso de no coincidir con franjas.

    Returns:
        float: Costo total calculado.
    """
    total_cost = 0.0
    for ts, kwh in energy_by_interval:
        if kwh <= 0.0:
            continue
        rate, _ = get_rate_for_timestamp(ts, tou_rates, base_rate)
        total_cost += kwh * rate

    return round(total_cost, 2)


def calculate_tiered_cost(
    total_kwh: float,
    tiers: List[Dict[str, Any]],
    fallback_rate: float = 0.15,
) -> float:
    """Calcula el costo de energía bajo esquema de tarifas por rangos o escalones acumulados.

    Ejemplo de tiers:
    [
        {"limit_kwh": 100.0, "rate_per_kwh": 0.10},
        {"limit_kwh": 250.0, "rate_per_kwh": 0.15},
        {"limit_kwh": None,  "rate_per_kwh": 0.25}  # Excedente
    ]

    Args:
        total_kwh: Consumo acumulado total en kWh.
        tiers: Lista ordenada de escalones de consumo.
        fallback_rate: Tarifa a usar si no se proveen tiers válidos.

    Returns:
        float: Costo total calculado.
    """
    if total_kwh <= 0.0:
        return 0.0

    if not tiers:
        return round(total_kwh * fallback_rate, 2)

    total_cost = 0.0
    remaining_kwh = total_kwh
    prev_limit = 0.0

    for tier in tiers:
        limit = tier.get("limit_kwh")
        rate = float(tier.get("rate_per_kwh", fallback_rate))

        if limit is None:
            # Último escalón para todo el consumo excedente
            total_cost += remaining_kwh * rate
            remaining_kwh = 0.0
            break
        else:
            limit = float(limit)
            tier_capacity = max(0.0, limit - prev_limit)
            kwh_in_tier = min(remaining_kwh, tier_capacity)
            total_cost += kwh_in_tier * rate
            remaining_kwh -= kwh_in_tier
            prev_limit = limit

            if remaining_kwh <= 0.0:
                break

    # Si aún queda energía y no hubo tier sin límite
    if remaining_kwh > 0.0:
        total_cost += remaining_kwh * fallback_rate

    return round(total_cost, 2)


def calculate_projected_monthly(
    current_kwh: float,
    day_of_month: int,
    days_in_month: int = 30,
    rate_per_kwh: float = 0.15,
) -> Tuple[float, float]:
    """Estima la proyección de consumo y costo para el cierre del mes en curso.

    Args:
        current_kwh: Consumo acumulado en lo que va del mes.
        day_of_month: Día actual del mes (ej. día 10).
        days_in_month: Días totales del mes (28, 29, 30 o 31).
        rate_per_kwh: Tarifa estimada de costo.

    Returns:
        Tuple[float, float]: (proyección_kwh, proyección_costo)
    """
    if current_kwh <= 0.0 or day_of_month <= 0:
        return 0.0, 0.0

    days_in_month = max(1, days_in_month)
    day_of_month = min(day_of_month, days_in_month)

    daily_average = current_kwh / float(day_of_month)
    projected_kwh = round(daily_average * days_in_month, 2)
    projected_cost = round(projected_kwh * rate_per_kwh, 2)

    return projected_kwh, projected_cost
