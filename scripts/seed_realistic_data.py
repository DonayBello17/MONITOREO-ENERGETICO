"""Script generador y poblador de base de datos con consumos aleatorios realistas.

Genera lecturas históricas coherentes con el consumo normal diario en kWh de cada
uno de los 5 circuitos residenciales respetando los perfiles de consumo de la vivienda.
Puede ejecutarse desde línea de comandos: `python -m scripts.seed_realistic_data`
o invocarse programáticamente desde el Dashboard o pruebas unitarias.
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.database import DatabaseManager
from src.common.models import Circuit, Reading
from src.common.profiles import CIRCUIT_PROFILES, calculate_circuit_power

logger = logging.getLogger("seeder")

DEFAULT_CIRCUITS = [
    Circuit(id="circ_01", name="Nevera", location="Cocina", nominal_power_w=350.0, icon="refrigerator"),
    Circuit(id="circ_02", name="Iluminación", location="General", nominal_power_w=400.0, icon="lightbulb"),
    Circuit(id="circ_03", name="Aire Acondicionado", location="Sala", nominal_power_w=2200.0, icon="air-conditioner"),
    Circuit(id="circ_04", name="Lavadora", location="Lavandería", nominal_power_w=1800.0, icon="washing-machine"),
    Circuit(id="circ_05", name="Toma General", location="Dormitorios", nominal_power_w=1500.0, icon="power-socket"),
]


def generate_realistic_voltage(timestamp: float, rng: random.Random) -> float:
    """Genera voltaje de red físicamente consistente entre ~118V y ~123V."""
    slow_oscillation = 1.2 * math.sin(timestamp / 600.0)
    noise = rng.gauss(0.0, 0.6)
    v = 120.0 + slow_oscillation + noise
    return max(118.0, min(123.0, round(v, 2)))


def seed_data(
    db_manager: Optional[DatabaseManager] = None,
    days: int = 15,
    interval_minutes: int = 15,
    clear: bool = False,
    rng_seed: Optional[int] = 42,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """Puebla la base de datos con lecturas realistas para los 5 circuitos.

    Args:
        db_manager: Instancia de DatabaseManager. Si es None, usa la BD predeterminada en disco.
        days: Número de días históricos hacia atrás a generar (15 por defecto).
        interval_minutes: Frecuencia de muestreo en minutos (15 por defecto).
        clear: Si es True, limpia las lecturas previas antes de poblar.
        rng_seed: Semilla para reproducibilidad de las pruebas.
        progress_callback: Función opcional para reportar progreso (0 a 100).

    Returns:
        Dict[str, Any]: Resumen con total_inserted, daily_averages_kwh y métricas.
    """
    db = db_manager if db_manager is not None else DatabaseManager()
    rng = random.Random(rng_seed)

    # 1. Asegurar circuitos en la base de datos (soporta circuitos dinámicos y personalizados)
    existing_db_circuits = db.get_circuits(active_only=True)
    if existing_db_circuits:
        target_circuits = existing_db_circuits
    else:
        try:
            from src.common.config_manager import ConfigManager
            cfg = ConfigManager()
            cfg_circuits = cfg.get_circuits()
            target_circuits = cfg_circuits if cfg_circuits else list(DEFAULT_CIRCUITS)
        except Exception:
            target_circuits = list(DEFAULT_CIRCUITS)

    if not target_circuits:
        target_circuits = list(DEFAULT_CIRCUITS)

    db.upsert_circuits(target_circuits)

    # 2. Limpiar base de datos si se solicitó
    if clear:
        deleted = db.clear_readings(clear_aggregates=True)
        logger.info("Lecturas anteriores limpiadas: %d registros eliminados.", deleted)

    # 3. Calcular rangos temporales
    days = max(1, int(days))
    interval_minutes = max(1, min(60, int(interval_minutes)))
    interval_seconds = interval_minutes * 60
    interval_hours = interval_minutes / 60.0

    # Alinear al final de la hora actual más reciente
    now_ts = time.time()
    end_ts = (int(now_ts) // interval_seconds) * interval_seconds
    total_seconds = days * 86400
    start_ts = end_ts - total_seconds

    total_steps = int(total_seconds // interval_seconds)
    circuit_ids = [c.id for c in target_circuits]

    accumulated_kwh_per_circuit: Dict[str, float] = {cid: 0.0 for cid in circuit_ids}
    batch: List[Reading] = []
    total_inserted = 0
    batch_size = 500

    logger.info(
        "Iniciando generación de datos: %d días (%d pasos de %d min cada uno)",
        days,
        total_steps,
        interval_minutes,
    )

    for step in range(total_steps):
        step_ts = start_ts + (step * interval_seconds)
        dt = datetime.fromtimestamp(step_ts)
        voltage = generate_realistic_voltage(step_ts, rng)

        for circuit in target_circuits:
            power_w, pf = calculate_circuit_power(
                circuit_id_or_name=circuit.id,
                timestamp=step_ts,
                dt=dt,
                rng=rng,
                is_interval_average=True,
                allow_occasional_spike=True,
                circuit=circuit,
            )

            # Corriente consistente con la ley de Ohm / potencia AC: I = P / (V * PF)
            if power_w > 0.05:
                current = round(power_w / (voltage * pf), 3)
            else:
                current = 0.0

            # Energía consumida en este intervalo (kWh)
            interval_kwh = round((power_w * interval_hours) / 1000.0, 6)
            accumulated_kwh_per_circuit[circuit.id] += interval_kwh

            reading = Reading(
                timestamp=step_ts,
                circuit_id=circuit.id,
                voltage=voltage,
                current=current,
                power_w=power_w,
                energy_kwh=interval_kwh,
            )
            batch.append(reading)

        # Inserción atómica por lotes
        if len(batch) >= batch_size:
            inserted = db.insert_readings_batch(batch)
            total_inserted += inserted
            batch.clear()

        if progress_callback and step % 50 == 0:
            pct = int((step / total_steps) * 90)
            progress_callback(pct)

    # Insertar remanente
    if batch:
        inserted = db.insert_readings_batch(batch)
        total_inserted += inserted
        batch.clear()

    # 4. Calcular agregaciones para que las pestañas de historial y KPIs se sincronicen
    logger.info("Calculando agregaciones estadísticas (horarias, diarias, mensuales)...")
    db.calculate_hourly_aggregates()
    db.calculate_daily_aggregates()
    db.calculate_monthly_aggregates()

    if progress_callback:
        progress_callback(100)

    # 5. Calcular promedios diarios por circuito
    daily_averages: Dict[str, float] = {}
    for cid, total_kwh in accumulated_kwh_per_circuit.items():
        daily_averages[cid] = round(total_kwh / days, 3)

    return {
        "total_inserted": total_inserted,
        "days": days,
        "interval_minutes": interval_minutes,
        "daily_averages_kwh": daily_averages,
        "accumulated_kwh": accumulated_kwh_per_circuit,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Función de entrada para ejecución desde terminal."""
    parser = argparse.ArgumentParser(
        description="Poblador de base de datos con consumos aleatorios realistas para Monitoreo Energético."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=15,
        help="Días históricos a generar hacia atrás (por defecto: 15).",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=15,
        help="Intervalo de muestreo entre lecturas en minutos (por defecto: 15).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Limpia todas las lecturas previas de la base de datos antes de insertar.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("\n" + "=" * 70)
    print("⚡ GENERADOR Y POBLADOR DE TELEMETRÍA ENERGÉTICA RESIDENCIAL")
    print("=" * 70)
    print(f"Parámetros: Días = {args.days} | Intervalo = {args.interval_minutes} min | Limpiar previo = {args.clear}\n")

    res = seed_data(
        days=args.days,
        interval_minutes=args.interval_minutes,
        clear=args.clear,
    )

    print("\n" + "-" * 70)
    print("📊 RESUMEN DE DATOS GENERADOS E INSERTADOS EN SQLITE:")
    print("-" * 70)
    print(f"Total de registros insertados: {res['total_inserted']:,}")
    print(f"Periodo cubierto: {args.days} días ({args.interval_minutes} min/lectura)\n")
    print(f"{'Circuito':<22} | {'Nombre':<20} | {'Consumo Diario':<16} | {'Rango Esperado':<16}")
    print("-" * 70)

    for cid, avg_kwh in res["daily_averages_kwh"].items():
        profile = CIRCUIT_PROFILES.get(cid)
        cname = profile.name if profile else cid
        expected = f"{profile.daily_kwh_min:.1f} - {profile.daily_kwh_max:.1f} kWh" if profile else "N/A"
        print(f"{cid:<22} | {cname:<20} | {avg_kwh:>6.2f} kWh/día  | {expected:<16}")

    print("-" * 70)
    total_daily = sum(res["daily_averages_kwh"].values())
    print(f"Consumo total diario estimado de la vivienda: {total_daily:.2f} kWh/día")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
