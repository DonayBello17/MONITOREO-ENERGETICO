"""Perfiles realistas de consumo energético residencial (Fuente única de verdad).

Define los rangos diarios normales en kWh, potencias típicas y perfiles horarios
para los 5 circuitos monitoreados en la vivienda:
- Nevera: 1.2 – 1.8 kWh/día (120 – 180 W en ciclos periódicos de compresor 24h)
- Aire Acondicionado: 4.0 – 8.0 kWh/día (900 – 1500 W, uso bajo en mañana y alto en tarde 13:00-17:00 y noche 21:00-02:00)
- Iluminación: 0.6 – 1.2 kWh/día (60 – 180 W, mínimo de día, picos 06:00-07:30 y 18:00-23:00)
- Lavadora: 0.5 – 1.5 kWh/día (400 – 700 W, 0 W casi todo el día con 1 o 2 ciclos aleatorios de 45-60 min)
- Toma General: 1.0 – 2.2 kWh/día (40 – 350 W, consumo base standby 40-70 W + picos aleatorios de equipos)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class CircuitProfile:
    """Especificación técnica y de consumo de un circuito residencial."""

    id: str
    name: str
    daily_kwh_min: float
    daily_kwh_max: float
    power_min_w: float
    power_max_w: float
    power_factor: float
    description: str


# Diccionario canónico de perfiles de los 5 circuitos
CIRCUIT_PROFILES: Dict[str, CircuitProfile] = {
    "circ_01": CircuitProfile(
        id="circ_01",
        name="Nevera",
        daily_kwh_min=1.2,
        daily_kwh_max=1.8,
        power_min_w=120.0,
        power_max_w=180.0,
        power_factor=0.86,
        description="120 – 180 W en ciclos periódicos de compresor 24h",
    ),
    "circ_02": CircuitProfile(
        id="circ_02",
        name="Iluminación",
        daily_kwh_min=0.6,
        daily_kwh_max=1.2,
        power_min_w=60.0,
        power_max_w=180.0,
        power_factor=0.95,
        description="60 – 180 W, mínimo de día, picos 06:00–07:30 y 18:00–23:00",
    ),
    "circ_03": CircuitProfile(
        id="circ_03",
        name="Aire Acondicionado",
        daily_kwh_min=4.0,
        daily_kwh_max=8.0,
        power_min_w=900.0,
        power_max_w=1500.0,
        power_factor=0.92,
        description="900 – 1500 W, uso bajo en mañana y alto en tarde 13:00–17:00 y noche 21:00–02:00",
    ),
    "circ_04": CircuitProfile(
        id="circ_04",
        name="Lavadora",
        daily_kwh_min=0.5,
        daily_kwh_max=1.5,
        power_min_w=400.0,
        power_max_w=700.0,
        power_factor=0.88,
        description="400 – 700 W, 0 W casi todo el día con 1 o 2 ciclos aleatorios de 45–60 min",
    ),
    "circ_05": CircuitProfile(
        id="circ_05",
        name="Toma General",
        daily_kwh_min=1.0,
        daily_kwh_max=2.2,
        power_min_w=40.0,
        power_max_w=350.0,
        power_factor=0.94,
        description="40 – 350 W, consumo base standby + picos aleatorios de equipos",
    ),
}


def get_profile_by_circuit_or_name(circuit_id_or_name: str) -> Optional[CircuitProfile]:
    """Busca el perfil por ID exacto ('circ_01') o por coincidencia en el nombre."""
    key = circuit_id_or_name.lower().strip()
    if key in CIRCUIT_PROFILES:
        return CIRCUIT_PROFILES[key]

    for profile in CIRCUIT_PROFILES.values():
        if profile.name.lower() in key or key in profile.name.lower():
            return profile

    if "nevera" in key or "refriger" in key:
        return CIRCUIT_PROFILES["circ_01"]
    elif "iluminaci" in key or "luz" in key:
        return CIRCUIT_PROFILES["circ_02"]
    elif "aire" in key or "ac" in key or "clima" in key:
        return CIRCUIT_PROFILES["circ_03"]
    elif "lavadora" in key or "lava" in key:
        return CIRCUIT_PROFILES["circ_04"]
    elif "toma" in key or "enchufe" in key or "general" in key:
        return CIRCUIT_PROFILES["circ_05"]

    return None


def calculate_circuit_power(
    circuit_id_or_name: str,
    timestamp: float,
    dt: Optional[datetime] = None,
    rng: Optional[random.Random] = None,
    is_interval_average: bool = False,
    allow_occasional_spike: bool = False,
) -> Tuple[float, float]:
    """Calcula la potencia (W) y factor de potencia para un circuito en un instante o intervalo.

    Args:
        circuit_id_or_name: ID del circuito ('circ_01') o nombre descriptivo.
        timestamp: Marca de tiempo Unix en segundos.
        dt: Instancia datetime correspondiente (opcional, se calcula si es None).
        rng: Generador pseudoaleatorio opcional. Si es None, usa random global.
        is_interval_average: Si es True, modela el valor medio eficaz del intervalo (útil para
                             muestreos discretos de 5, 10 o 15 minutos). Si es False, modela
                             el estado instantáneo del ciclo on/off (útil para el simulador 1Hz).
        allow_occasional_spike: Si es True, permite un 0.5% de probabilidad de picos de anomalía.

    Returns:
        Tuple[float, float]: (potencia_w, factor_de_potencia).
    """
    _rng = rng if rng is not None else random
    if dt is None:
        dt = datetime.fromtimestamp(timestamp)

    profile = get_profile_by_circuit_or_name(circuit_id_or_name)
    cid = profile.id if profile else "circ_05"
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    # 1. Picos ocasionales de alerta (anomalías)
    if allow_occasional_spike and _rng.random() < 0.005:
        if cid == "circ_01":
            return round(_rng.uniform(280.0, 360.0), 2), 0.85
        elif cid == "circ_02":
            return round(_rng.uniform(250.0, 380.0), 2), 0.95
        elif cid == "circ_03":
            return round(_rng.uniform(2100.0, 2600.0), 2), 0.90
        elif cid == "circ_04":
            return round(_rng.uniform(1700.0, 2200.0), 2), 0.88
        elif cid == "circ_05":
            return round(_rng.uniform(1600.0, 2300.0), 2), 0.93

    # 2. Generación según perfil normal del circuito
    if cid == "circ_01":  # Nevera (1.2 - 1.8 kWh/día, 120 - 180 W activo, ciclos 24h)
        if is_interval_average:
            # En promedios de intervalo (ej. 15 min), el compresor opera ~38% a 42% del tiempo
            active_p = _rng.uniform(130.0, 165.0)
            duty = _rng.uniform(0.36, 0.43)
            standby_p = _rng.uniform(3.0, 4.5)
            p = duty * active_p + (1.0 - duty) * standby_p
        else:
            # En tiempo real (ciclo de 30 min = 1800 s, ~12 min activo / 18 min standby)
            pos = timestamp % 1800.0
            if pos < 720.0:  # 12 min activo
                p = _rng.uniform(130.0, 175.0)
            else:
                p = _rng.uniform(3.0, 4.5)
        return round(p, 2), 0.86

    elif cid == "circ_02":  # Iluminación (0.6 - 1.2 kWh/día, 60 - 180 W picos)
        # Picos en 06:00-07:30 y 18:00-23:00, mínimo diurno, casi nulo de madrugada
        if 6.0 <= hour < 7.5:
            p = _rng.uniform(65.0, 115.0)
        elif 18.0 <= hour < 23.0:
            p = _rng.uniform(145.0, 180.0)
        elif 7.5 <= hour < 18.0:
            p = _rng.uniform(10.0, 22.0)
        else:
            p = _rng.uniform(1.0, 4.0)
        return round(p, 2), 0.95

    elif cid == "circ_03":  # Aire Acondicionado (4.0 - 8.0 kWh/día, 900 - 1500 W)
        # Uso bajo en mañana, alto en tarde (13:00-17:00) y noche (21:00-02:00)
        active_p = _rng.uniform(980.0, 1300.0)
        standby_p = 4.5

        if 13.0 <= hour < 17.0:  # Tarde calurosa
            duty = 0.65
        elif 21.0 <= hour or hour < 2.0:  # Noche / dormitorio
            duty = 0.40
        elif 2.0 <= hour < 6.0:  # Madrugada
            duty = 0.12
        else:  # Mañanas frescas y resto
            duty = 0.03

        if is_interval_average:
            duty_var = max(0.0, min(1.0, duty + _rng.uniform(-0.04, 0.04)))
            p = duty_var * active_p + (1.0 - duty_var) * standby_p
        else:
            # Termostato con ciclos de 15 min (900 s)
            cycle_pos = (timestamp % 900.0) / 900.0
            p = active_p if cycle_pos < duty else standby_p

        return round(p, 2), 0.92

    elif cid == "circ_04":  # Lavadora (0.5 - 1.5 kWh/día, 400 - 700 W, 1 o 2 ciclos de 45-60 min)
        # 1 ciclo diario (09:45-10:35), y un 2do ciclo (15:45-16:35) en días pares
        day_seed = int(timestamp // 86400)
        has_second = (day_seed % 2 == 0)

        in_cycle1 = 9.75 <= hour < 10.60
        in_cycle2 = has_second and (15.75 <= hour < 16.60)

        if in_cycle1 or in_cycle2:
            p = _rng.uniform(450.0, 680.0)
        else:
            p = _rng.uniform(1.0, 2.5)
        return round(p, 2), 0.88

    elif cid == "circ_05":  # Toma General (1.0 - 2.2 kWh/día, 40 - 350 W)
        # Standby base 40-55 W constante + actividad diurna/nocturna 10-60 W + picos 60-150 W
        base = _rng.uniform(42.0, 56.0)
        if 7.0 <= hour < 23.0:
            extra = _rng.uniform(10.0, 45.0)
            if _rng.random() < 0.15:
                extra += _rng.uniform(50.0, 140.0)
        else:
            extra = _rng.uniform(0.0, 5.0)
        p = base + extra
        return round(p, 2), 0.94

    # Circuito genérico de respaldo
    return round(_rng.uniform(30.0, 100.0), 2), 0.90
