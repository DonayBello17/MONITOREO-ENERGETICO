"""Modelos de datos base para el Sistema de Monitoreo Energético.

Define las estructuras de datos (dataclasses) para Circuitos, Lecturas de Sensores,
Alertas y Agregaciones temporales con tipado estático y métodos de serialización.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(slots=True)
class Circuit:
    """Representa un circuito eléctrico monitoreado en la vivienda."""

    id: str
    name: str
    location: str
    nominal_power_w: float
    icon: str = "zap"
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el circuito a diccionario."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Circuit:
        """Crea una instancia de Circuit a partir de un diccionario."""
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            location=str(data.get("location", "Desconocido")),
            nominal_power_w=float(data.get("nominal_power_w", 0.0)),
            icon=str(data.get("icon", "zap")),
            is_active=bool(data.get("is_active", True)),
        )


@dataclass(slots=True)
class Reading:
    """Lectura instantánea de telemetría de un circuito.

    Atributos:
        timestamp: Tiempo en época Unix (segundos en punto flotante).
        circuit_id: Identificador del circuito asociado.
        voltage: Voltaje eficaz (V).
        current: Corriente eficaz (A).
        power_w: Potencia activa instantánea (W).
        energy_kwh: Energía acumulada o consumida en el intervalo (kWh).
    """

    timestamp: float
    circuit_id: str
    voltage: float
    current: float
    power_w: float
    energy_kwh: float

    @property
    def datetime_utc(self) -> datetime:
        """Retorna la fecha/hora en formato UTC."""
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la lectura a diccionario."""
        return asdict(self)

    def to_tuple(self) -> tuple[float, str, float, float, float, float]:
        """Retorna tupla para inserción rápida en base de datos SQLite."""
        return (
            self.timestamp,
            self.circuit_id,
            self.voltage,
            self.current,
            self.power_w,
            self.energy_kwh,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Reading:
        """Crea una instancia de Reading a partir de un diccionario."""
        return cls(
            timestamp=float(data.get("timestamp", time.time())),
            circuit_id=str(data["circuit_id"]),
            voltage=float(data.get("voltage", 0.0)),
            current=float(data.get("current", 0.0)),
            power_w=float(data.get("power_w", 0.0)),
            energy_kwh=float(data.get("energy_kwh", 0.0)),
        )


@dataclass(slots=True)
class Alert:
    """Registro de evento o umbral superado en el sistema."""

    timestamp: float
    circuit_id: Optional[str]
    alert_type: str
    severity: str
    message: str
    value: float = 0.0
    threshold: float = 0.0
    id: Optional[int] = None
    is_acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la alerta a diccionario."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Alert:
        """Crea una instancia de Alert a partir de un diccionario."""
        return cls(
            id=data.get("id"),
            timestamp=float(data.get("timestamp", time.time())),
            circuit_id=data.get("circuit_id"),
            alert_type=str(data.get("alert_type", "GENERAL")),
            severity=str(data.get("severity", "WARNING")),
            message=str(data.get("message", "")),
            value=float(data.get("value", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
            is_acknowledged=bool(data.get("is_acknowledged", False)),
        )


@dataclass(slots=True)
class AggregateReading:
    """Agregado estadístico para análisis horario, diario o mensual."""

    period_start: float
    circuit_id: str
    avg_power_w: float
    min_power_w: float
    max_power_w: float
    total_energy_kwh: float
    reading_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convierte el agregado a diccionario."""
        return asdict(self)
