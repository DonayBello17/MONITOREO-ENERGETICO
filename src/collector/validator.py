"""Validador de telemetría de lecturas energéticas.

Asegura la integridad física de los datos capturados antes de su almacenamiento,
descartando valores nulos, negativos, incoherentes o fuera de rangos razonables,
así como lecturas duplicadas en el tiempo.
"""

from __future__ import annotations

import collections
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from src.common.models import Reading

logger = logging.getLogger(__name__)

# Límites físicos estándar para instalaciones eléctricas residenciales
MIN_VOLTAGE_V = 80.0
MAX_VOLTAGE_V = 260.0
MIN_CURRENT_A = 0.0
MAX_CURRENT_A = 100.0
MIN_POWER_W = 0.0
MAX_POWER_W = 26000.0  # 260V * 100A
MIN_ENERGY_KWH = 0.0


class ReadingValidator:
    """Valida lecturas eléctricas garantizando consistencia física y ausencia de duplicados."""

    def __init__(self, max_duplicate_cache_size: int = 20000) -> None:
        """Inicializa el validador con una memoria acotada para detección de duplicados.

        Args:
            max_duplicate_cache_size: Cantidad máxima de firmas de lecturas recientes
                                      mantenidas en memoria para prevenir fugas de RAM.
        """
        self._max_cache = max_duplicate_cache_size
        # Usamos OrderedDict como LRU acotado para (circuit_id, timestamp_redondeado)
        self._seen_signatures: collections.OrderedDict[Tuple[str, float], None] = collections.OrderedDict()

    def clear_cache(self) -> None:
        """Limpia el registro de lecturas procesadas para detección de duplicados."""
        self._seen_signatures.clear()

    def check_reading(self, reading: Any) -> Tuple[bool, Optional[str]]:
        """Comprueba si una lectura es válida según las reglas físicas y lógicas.

        Args:
            reading: Instancia de Reading a validar.

        Returns:
            Tuple[bool, Optional[str]]: (True, None) si es válida; (False, motivo) si no lo es.
        """
        if reading is None:
            return False, "La lectura recibida es nula (None)."

        # 1. Comprobación de atributos obligatorios no nulos
        required_fields = ["circuit_id", "timestamp", "voltage", "current", "power_w", "energy_kwh"]
        for field in required_fields:
            if not hasattr(reading, field):
                return False, f"Falta el atributo obligatorio '{field}' en la lectura."
            val = getattr(reading, field)
            if val is None:
                return False, f"El campo '{field}' contiene un valor nulo (None)."

        # Comprobación de tipo y longitud de circuit_id
        if not isinstance(reading.circuit_id, str) or not reading.circuit_id.strip():
            return False, f"El identificador de circuito es inválido o vacío: {reading.circuit_id!r}"

        # 2. Comprobación de tipos numéricos y valores finitos (sin NaN ni Infinito)
        try:
            ts = float(reading.timestamp)
            v = float(reading.voltage)
            i = float(reading.current)
            p = float(reading.power_w)
            e = float(reading.energy_kwh)
        except (ValueError, TypeError) as exc:
            return False, f"Error al convertir valores a numéricos flotantes: {exc}"

        for name, num in [("timestamp", ts), ("voltage", v), ("current", i), ("power_w", p), ("energy_kwh", e)]:
            if math.isnan(num) or math.isinf(num):
                return False, f"El campo '{name}' tiene un valor numérico no finito (NaN o Infinito): {num}"

        # 3. Validación de Timestamp
        if ts <= 0:
            return False, f"Timestamp inválido (menor o igual a cero): {ts}"

        # 4. Rango de Voltaje (80V a 260V)
        if not (MIN_VOLTAGE_V <= v <= MAX_VOLTAGE_V):
            return False, f"Voltaje fuera del rango físico aceptable [{MIN_VOLTAGE_V}V - {MAX_VOLTAGE_V}V]: {v:.2f}V"

        # 5. Rango de Corriente (0A a 100A)
        if not (MIN_CURRENT_A <= i <= MAX_CURRENT_A):
            return False, f"Corriente negativa o excesiva fuera del rango [{MIN_CURRENT_A}A - {MAX_CURRENT_A}A]: {i:.3f}A"

        # 6. Rango de Energía Acumulada
        if e < MIN_ENERGY_KWH:
            return False, f"Energía acumulada negativa: {e:.6f} kWh"

        # 7. Rango y Consistencia Física de Potencia
        if p < MIN_POWER_W:
            return False, f"Potencia activa negativa: {p:.2f} W"

        if p > MAX_POWER_W:
            return False, f"Potencia activa superior al límite de seguridad ({MAX_POWER_W} W): {p:.2f} W"

        # Consistencia entre P, V e I:
        # En corriente alterna, la potencia activa P = V * I * cos(phi) <= V * I (potencia aparente S).
        # Permitimos un margen de tolerancia del 25% + 15W para absorber ruidos y transitorios breves.
        apparent_power = v * i
        allowed_max_power = apparent_power * 1.25 + 15.0

        if i <= 0.05 and p > 25.0:
            return False, (
                f"Potencia inconsistente con corriente nula: "
                f"P={p:.2f}W pero I={i:.3f}A (máx permitido sin corriente: 25W)"
            )

        if p > allowed_max_power:
            return False, (
                f"Potencia activa ({p:.2f}W) significativamente superior a la potencia aparente "
                f"S = V * I ({v:.1f}V * {i:.2f}A = {apparent_power:.2f}VA)"
            )

        # 8. Detección de duplicados (mismo circuit_id y mismo timestamp redondeado a 3 decimales)
        signature = (reading.circuit_id, round(ts, 3))
        if signature in self._seen_signatures:
            return False, (
                f"Lectura duplicada detectada para circuito '{reading.circuit_id}' "
                f"en timestamp {ts:.3f}."
            )

        return True, None

    def validate(self, reading: Any) -> bool:
        """Valida una lectura individual.

        Si es válida, registra su firma en la memoria de duplicados y retorna True.
        Si es inválida, registra un log de advertencia (WARNING) y retorna False.

        Args:
            reading: Objeto lectura a evaluar.

        Returns:
            bool: True si la lectura es válida; False si fue descartada.
        """
        is_valid, reason = self.check_reading(reading)
        if not is_valid:
            logger.warning("Lectura descartada: %s | Objeto: %s", reason, reading)
            return False

        # Registrar en cache de firmas para control de duplicados
        sig = (reading.circuit_id, round(float(reading.timestamp), 3))
        self._seen_signatures[sig] = None

        # Mantener tamaño acotado
        if len(self._seen_signatures) > self._max_cache:
            self._seen_signatures.popitem(last=False)

        return True

    def validate_batch(self, readings: List[Reading]) -> List[Reading]:
        """Filtra una lista de lecturas retornando únicamente las válidas.

        Las lecturas no válidas se descartan y se registran en los logs.
        """
        return [r for r in readings if self.validate(r)]
