"""Módulo de detección de anomalías de consumo eléctrico.

Identifica patrones de consumo inusuales basándose en umbrales estadísticos
(cuando una lectura supera en más de 2 desviaciones estándar la media histórica
de esa hora para el circuito respectivo).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import List, Optional, Tuple

from src.common.database import DatabaseManager
from src.common.models import Alert, Reading

logger = logging.getLogger(__name__)


def compute_mean_and_std(values: List[float]) -> Tuple[float, float]:
    """Calcula la media aritmética y la desviación estándar de una muestra.

    Args:
        values: Lista de valores numéricos de potencia o energía.

    Returns:
        Tuple[float, float]: (media, desviacion_estandar)
    """
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), 0.0

    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std = math.sqrt(max(0.0, variance))
    return round(mean, 2), round(std, 2)


def is_consumption_anomaly(
    current_value: float,
    historical_values: List[float],
    threshold_sigmas: float = 2.0,
    min_std: float = 10.0,
) -> Tuple[bool, float, float]:
    """Evalúa si un valor instantáneo constituye una anomalía estadística.

    Una lectura es anómala si:
        valor > media + (threshold_sigmas * max(std, min_std))

    Args:
        current_value: Valor actual de potencia (W) o energía (kWh).
        historical_values: Muestra de valores históricos para ese horario y circuito.
        threshold_sigmas: Número de desviaciones estándar umbral (por defecto 2.0).
        min_std: Desviación estándar mínima para evitar falsos positivos con cargas constantes.

    Returns:
        Tuple[bool, float, float]: (es_anomalia, media, desviacion_usada)
    """
    if len(historical_values) < 3:
        # Se requieren al menos 3 muestras históricas para un cálculo estadístico mínimo
        return False, 0.0, 0.0

    mean, std = compute_mean_and_std(historical_values)
    effective_std = max(std, min_std)
    upper_threshold = mean + (threshold_sigmas * effective_std)

    if current_value > upper_threshold:
        return True, mean, effective_std
    return False, mean, effective_std


class AnomalyDetector:
    """Detector de anomalías de consumo integrado con la base de datos."""

    def __init__(self, db_manager: DatabaseManager, threshold_sigmas: float = 2.0) -> None:
        """Inicializa el detector con conexión a base de datos.

        Args:
            db_manager: Gestor de base de datos SQLite.
            threshold_sigmas: Cantidad de desviaciones estándar de tolerancia (por defecto 2.0).
        """
        self.db = db_manager
        self.threshold_sigmas = threshold_sigmas

    def get_hourly_historical_powers(self, circuit_id: str, target_timestamp: float) -> List[float]:
        """Recupera potencias históricas para el mismo circuito y la misma hora del día.

        Consulta los agregados horarios o lecturas crudas de los últimos 30 días.
        """
        target_dt = datetime.fromtimestamp(target_timestamp)
        target_hour = target_dt.hour

        # Consultar tabla de agregados horarios para este circuito
        aggregates = self.db.get_aggregates(period_type="hourly", circuit_id=circuit_id)
        matching_powers = []

        for agg in aggregates:
            agg_dt = datetime.fromtimestamp(agg.period_start)
            if agg_dt.hour == target_hour:
                matching_powers.append(agg.avg_power_w)

        # Si hay pocos agregados, complementar con lecturas directas
        if len(matching_powers) < 5:
            recent_readings = self.db.get_readings(circuit_id=circuit_id, limit=200)
            for r in recent_readings:
                rdt = datetime.fromtimestamp(r.timestamp)
                if rdt.hour == target_hour:
                    matching_powers.append(r.power_w)

        return matching_powers

    def evaluate_reading(self, reading: Reading) -> Optional[Alert]:
        """Evalúa una lectura individual en busca de anomalías de potencia.

        Si se detecta anomalía, crea, guarda en base de datos y retorna un objeto Alert.
        Si la lectura está dentro de parámetros normales, retorna None.
        """
        historical = self.get_hourly_historical_powers(reading.circuit_id, reading.timestamp)
        is_anom, mean, std = is_consumption_anomaly(
            current_value=reading.power_w,
            historical_values=historical,
            threshold_sigmas=self.threshold_sigmas,
        )

        if is_anom:
            threshold = mean + (self.threshold_sigmas * std)
            msg = (
                f"Consumo anómalo en circuito '{reading.circuit_id}': "
                f"{reading.power_w:.1f} W supera en > {self.threshold_sigmas}σ la media de la hora "
                f"({mean:.1f} W ± {std:.1f} W)."
            )
            alert = Alert(
                timestamp=reading.timestamp,
                circuit_id=reading.circuit_id,
                alert_type="ANOMALIA",
                severity="WARNING",
                message=msg,
                value=reading.power_w,
                threshold=threshold,
                is_acknowledged=False,
            )
            try:
                alert_id = self.db.insert_alert(alert)
                alert.id = alert_id
            except Exception as exc:
                logger.error("Error al persistir alerta de anomalía en base de datos: %s", exc)

            logger.warning("ANOMALÍA DETECTADA: %s", msg)
            return alert

        return None
