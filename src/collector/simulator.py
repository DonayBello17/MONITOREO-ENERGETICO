"""Simulador de telemetría energética para circuitos residenciales.

Genera lecturas realistas de voltaje (~120V con fluctuación natural), corriente,
potencia y energía acumulada según perfiles horarios de consumo para cada circuito.
Soporta inyección de fallos simulados para pruebas de resiliencia y reintento.
"""

from __future__ import annotations

import logging
import math
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.models import Circuit, Reading
from src.common.profiles import calculate_circuit_power

logger = logging.getLogger(__name__)


class DataSourceError(Exception):
    """Excepción lanzada cuando la fuente de datos (sensores/hardware) falla."""


# Circuitos predeterminados si no se provee configuración
DEFAULT_SIMULATED_CIRCUITS = [
    Circuit(id="circ_01", name="Nevera", location="Cocina", nominal_power_w=350.0, icon="refrigerator"),
    Circuit(id="circ_02", name="Iluminación", location="General", nominal_power_w=400.0, icon="lightbulb"),
    Circuit(id="circ_03", name="Aire Acondicionado", location="Sala", nominal_power_w=2200.0, icon="air-conditioner"),
    Circuit(id="circ_04", name="Lavadora", location="Lavandería", nominal_power_w=1800.0, icon="washing-machine"),
    Circuit(id="circ_05", name="Toma General", location="Dormitorios", nominal_power_w=1500.0, icon="power-socket"),
]


class EnergySimulator:
    """Generador de telemetría eléctrica realista con perfiles de carga domiciliarios."""

    def __init__(
        self,
        circuits: Optional[List[Circuit]] = None,
        base_voltage: float = 120.0,
        seed: Optional[int] = None,
    ) -> None:
        """Inicializa el simulador de energía.

        Args:
            circuits: Lista de circuitos a simular. Si es None o vacía, usa los 5 por defecto.
            base_voltage: Voltaje nominal base de la red (120V típicamente).
            seed: Semilla opcional para reproducibilidad en pruebas.
        """
        self.circuits = circuits if circuits else list(DEFAULT_SIMULATED_CIRCUITS)
        self.base_voltage = base_voltage
        self._rng = random.Random(seed)

        # Estado interno de acumulación de energía y tiempo previo por circuito
        self._accumulated_energy_kwh: Dict[str, float] = {c.id: 0.0 for c in self.circuits}
        self._last_timestamp: Dict[str, float] = {}

        # Simulación de fallos
        self._fault_injected = False
        self._fault_message = "Fallo simulado en sensor de hardware"

    @property
    def failure_injected(self) -> bool:
        """Indica si la inyección de fallos está activa."""
        return self._fault_injected

    def inject_fault(self, enabled: bool = True, message: Optional[str] = None) -> None:
        """Activa o desactiva la inyección de fallos en la lectura de la fuente.

        Args:
            enabled: True para activar el fallo, False para restaurar operación normal.
            message: Mensaje de error a incluir en la excepción.
        """
        self._fault_injected = enabled
        if message:
            self._fault_message = message

    def set_failure(self, enabled: bool, message: str = "Fallo simulado en la fuente de datos") -> None:
        """Alias compatible para la inyección de fallos."""
        self.inject_fault(enabled=enabled, message=message)

    def reset_accumulated_energy(self, circuit_id: Optional[str] = None, initial_kwh: float = 0.0) -> None:
        """Reinicia el contador de energía acumulada."""
        if circuit_id:
            if circuit_id in self._accumulated_energy_kwh:
                self._accumulated_energy_kwh[circuit_id] = initial_kwh
        else:
            for cid in self._accumulated_energy_kwh:
                self._accumulated_energy_kwh[cid] = initial_kwh

    def _generate_mains_voltage(self, timestamp: float) -> float:
        """Genera voltaje de red con fluctuación natural alrededor de base_voltage.

        Combina una oscilación lenta de baja frecuencia con ruido gaussiano leve.
        """
        # Variación armónica lenta (+/- 3V en periodos de 10 min)
        slow_drift = 2.5 * math.sin(timestamp / 300.0)
        # Ruido instantáneo (+/- 1.5V)
        noise = self._rng.gauss(0.0, 0.7)
        v = self.base_voltage + slow_drift + noise
        # Asegurar dentro de rango estándar seguro
        return max(105.0, min(135.0, round(v, 2)))

    def _get_refrigerator_power(self, timestamp: float) -> tuple[float, float]:
        """Perfil Nevera: Ciclo de compresor encendido/apagado periódico.

        Ciclo típico de 30 min (1800 s): 12 min encendido (~140W-180W), 18 min apagado (~3W).
        Retorna (potencia_w, factor_de_potencia).
        """
        cycle_period = 1800.0
        duty_seconds = 720.0  # 12 minutos
        pos_in_cycle = timestamp % cycle_period

        if pos_in_cycle < duty_seconds:
            # Compresor activo
            base_power = 150.0 + self._rng.uniform(-15.0, 25.0)
            pf = 0.86  # Motor inductivo
            return round(base_power, 2), pf
        else:
            # Standby / descanso
            base_power = 3.5 + self._rng.uniform(-0.5, 1.0)
            pf = 0.95
            return round(base_power, 2), pf

    def _get_lighting_power(self, dt: datetime) -> tuple[float, float]:
        """Perfil Iluminación: Picos matutino (6:00-8:00) y nocturno (18:00-23:00).

        Retorna (potencia_w, factor_de_potencia).
        """
        hour = dt.hour + dt.minute / 60.0

        if 6.0 <= hour < 8.0:
            # Pico de la mañana
            power = self._rng.uniform(160.0, 320.0)
        elif 18.0 <= hour < 23.0:
            # Pico principal de la noche
            power = self._rng.uniform(220.0, 390.0)
        elif 8.0 <= hour < 18.0:
            # Diurno (luces mínimas según necesidad puntual)
            power = self._rng.uniform(15.0, 60.0)
        else:
            # Madrugada / descanso (casi apagado total)
            power = self._rng.uniform(0.0, 15.0)

        pf = 0.95  # Lámparas LED modernas
        return round(power, 2), pf

    def _get_ac_power(self, dt: datetime, timestamp: float) -> tuple[float, float]:
        """Perfil Aire Acondicionado: Mayor consumo en horas calurosas y noche.

        Retorna (potencia_w, factor_de_potencia).
        """
        hour = dt.hour + dt.minute / 60.0
        # Subciclo de termostato de 15 minutos (900s)
        cycle_pos = (timestamp % 900.0) / 900.0

        # Determinación de probabilidad/fracción de ciclo según hora
        if 12.0 <= hour < 17.0:
            # Horas calurosas de la tarde: alta demanda (80% ciclo activo)
            is_compressor_on = cycle_pos < 0.80
            power_active = self._rng.uniform(1500.0, 2150.0)
        elif 21.0 <= hour or hour < 6.0:
            # Noche / dormitorio: demanda media-alta (55% ciclo activo)
            is_compressor_on = cycle_pos < 0.55
            power_active = self._rng.uniform(1100.0, 1600.0)
        else:
            # Mañanas frescas: demanda baja (15% ciclo activo)
            is_compressor_on = cycle_pos < 0.15
            power_active = self._rng.uniform(1000.0, 1400.0)

        if is_compressor_on:
            power = power_active
            pf = 0.92
        else:
            power = 4.0 + self._rng.uniform(-0.5, 1.0)  # Ventilador en reposo/standby
            pf = 0.98

        return round(power, 2), pf

    def _get_washing_machine_power(self, timestamp: float) -> tuple[float, float]:
        """Perfil Lavadora: Ciclos intermitentes de alta potencia.

        Simula sesiones periódicas con fases de agitación (300-450W) y centrifugado/calentamiento (1200-1750W).
        Retorna (potencia_w, factor_de_potencia).
        """
        # Ciclo repetitivo cada 2 horas (7200 s) para propósitos de simulación
        # Primeros 45 minutos (2700 s) activos, resto en standby
        cycle_period = 7200.0
        session_duration = 2700.0
        pos = timestamp % cycle_period

        if pos < session_duration:
            # Dentro de un programa de lavado activo
            # Sub-fases: 0-20 min agitación, 20-30 min centrifugado, 30-45 min aclarado/centrifugado final
            phase_min = pos / 60.0
            if (18.0 <= phase_min < 26.0) or (38.0 <= phase_min < 45.0):
                # Centrifugado / alta potencia
                power = self._rng.uniform(1100.0, 1750.0)
                pf = 0.89
            else:
                # Agitación suave del tambor
                power = self._rng.uniform(280.0, 480.0)
                pf = 0.85
        else:
            # Standby fuera de ciclo
            power = 2.0 + self._rng.uniform(-0.3, 0.8)
            pf = 0.95

        return round(power, 2), pf

    def _get_general_sockets_power(self) -> tuple[float, float]:
        """Perfil Toma General: Consumo fantasma constante (standby) + picos aleatorios.

        Retorna (potencia_w, factor_de_potencia).
        """
        # Carga fantasma / standby constante (routers, TV en espera, cargadores)
        base_phantom = self._rng.uniform(35.0, 65.0)

        # Probabilidad de artefactos encendidos puntuales (TV, ordenador, microondas, etc.)
        roll = self._rng.random()
        spike = 0.0
        if roll > 0.85:
            # Dispositivo de alta potencia ocasional (ej. tostador, microondas, hervidor)
            spike = self._rng.uniform(500.0, 1200.0)
        elif roll > 0.50:
            # Dispositivo mediano (ej. TV, PC, consola)
            spike = self._rng.uniform(100.0, 300.0)

        power = base_phantom + spike
        pf = 0.94
        return round(power, 2), pf

    def update_circuits(self, circuits: List[Circuit]) -> None:
        """Actualiza la lista de circuitos simulados dinámicamente."""
        self.circuits = list(circuits)
        for c in circuits:
            if c.id not in self._accumulated_energy_kwh:
                self._accumulated_energy_kwh[c.id] = 0.0

    def _calculate_circuit_power(
        self, circuit: Circuit, timestamp: float, dt: datetime
    ) -> tuple[float, float]:
        """Calcula potencia y factor de potencia para un circuito específico según su perfil centralizado."""
        return calculate_circuit_power(
            circuit_id_or_name=circuit.id or circuit.name,
            timestamp=timestamp,
            dt=dt,
            rng=self._rng,
            is_interval_average=False,
            allow_occasional_spike=True,
            circuit=circuit,
        )

    def generate_readings(self, timestamp: Optional[float] = None) -> List[Reading]:
        """Genera una lectura instantánea para cada circuito configurado.

        Args:
            timestamp: Marca de tiempo Unix opcional. Si es None, usa time.time().

        Returns:
            List[Reading]: Lista de lecturas generadas para todos los circuitos activos.

        Raises:
            DataSourceError: Si la inyección de fallos está habilitada.
        """
        if self._fault_injected:
            raise DataSourceError(self._fault_message)

        now = timestamp if timestamp is not None else time.time()
        dt = datetime.fromtimestamp(now)
        voltage = self._generate_mains_voltage(now)

        readings: List[Reading] = []

        for circuit in self.circuits:
            if not circuit.is_active:
                continue

            power_w, pf = self._calculate_circuit_power(circuit, now, dt)

            # Cálculo físicamente consistente de corriente: I = P / (V * PF)
            if power_w > 0.05:
                current = power_w / (voltage * pf)
            else:
                current = 0.0
            current = round(current, 3)

            # Acumulación de energía (kWh) desde la última lectura
            last_ts = self._last_timestamp.get(circuit.id)
            if last_ts is not None and now > last_ts:
                elapsed_hours = (now - last_ts) / 3600.0
                delta_kwh = (power_w * elapsed_hours) / 1000.0
            else:
                delta_kwh = 0.0

            self._accumulated_energy_kwh[circuit.id] = round(
                self._accumulated_energy_kwh.get(circuit.id, 0.0) + delta_kwh, 6
            )
            self._last_timestamp[circuit.id] = now

            reading = Reading(
                timestamp=now,
                circuit_id=circuit.id,
                voltage=voltage,
                current=current,
                power_w=power_w,
                energy_kwh=self._accumulated_energy_kwh[circuit.id],
            )
            readings.append(reading)

        return readings
