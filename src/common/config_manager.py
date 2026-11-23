"""Gestor de configuración centralizado y seguro para entornos multihilo.

Gestiona la lectura, validación, actualización y guardado de las opciones
de configuración del sistema, con soporte de recarga en caliente y fallback a valores por defecto.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.models import Circuit
from src.common.paths import (
    apply_secure_permissions,
    get_config_file_path,
    get_default_config_template_path,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """Administrador de configuración con sincronización por hilos."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        default_template_path: Optional[Path] = None,
    ) -> None:
        """Inicializa el gestor de configuración.

        Args:
            config_path: Ruta al archivo config.json del usuario. Si es None, usa paths.get_config_file_path().
            default_template_path: Ruta a la plantilla por defecto. Si es None, usa paths.get_default_config_template_path().
        """
        self._config_path = config_path or get_config_file_path()
        self._default_template_path = (
            default_template_path or get_default_config_template_path()
        )
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}

        self.reload()

    @property
    def config_path(self) -> Path:
        """Ruta física del archivo de configuración."""
        return self._config_path

    def _load_default_template(self) -> Dict[str, Any]:
        """Carga la plantilla predeterminada del proyecto."""
        if self._default_template_path.exists():
            try:
                with open(self._default_template_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error(
                    "Error al leer plantilla default_config.json (%s): %s",
                    self._default_template_path,
                    exc,
                )

        # Fallback mínimo codificado en caso de ausencia del archivo físico
        return {
            "sampling": {
                "interval_seconds": 2,
                "min_interval_seconds": 1,
                "max_interval_seconds": 60,
            },
            "ipc": {"host": "127.0.0.1", "port": 50555},
            "tariff": {
                "base_rate_per_kwh": 0.15,
                "currency": "USD",
                "time_of_use_enabled": False,
                "time_of_use_rates": [],
            },
            "retention": {"raw_readings_days": 30, "aggregates_days": 730},
            "alert_thresholds": {
                "max_instant_power_w": 5000.0,
                "max_daily_energy_kwh": 30.0,
                "monthly_budget": 100.0,
            },
            "circuits": [],
        }

    def reload(self) -> None:
        """Recarga la configuración desde el disco de forma segura para hilos.

        Si el archivo del usuario no existe, copia la plantilla predeterminada.
        Si está corrupto o hay errores de sistema de archivos, restaura la plantilla sin abortar el proceso.
        """
        with self._lock:
            file_exists = False
            try:
                file_exists = self._config_path.exists()
            except (OSError, PermissionError) as exc:
                logger.warning(
                    "No se pudo verificar la existencia del archivo de configuración '%s': %s",
                    self._config_path,
                    exc,
                )
                self._data = self._load_default_template()
                return

            # Si no existe, crear directorio padre y copiar plantilla
            if not file_exists:
                logger.info(
                    "Archivo de configuración no encontrado en %s. Creando desde plantilla.",
                    self._config_path,
                )
                try:
                    self._config_path.parent.mkdir(parents=True, exist_ok=True)
                    apply_secure_permissions(self._config_path.parent, is_directory=True)

                    if self._default_template_path.exists():
                        shutil.copyfile(self._default_template_path, self._config_path)
                    else:
                        with open(self._config_path, "w", encoding="utf-8") as f:
                            json.dump(self._load_default_template(), f, indent=2)

                    apply_secure_permissions(self._config_path, is_directory=False)
                except (OSError, PermissionError) as exc:
                    logger.error(
                        "No se pudo crear el archivo de configuración en disco: %s. Usando memoria.",
                        exc,
                    )
                    self._data = self._load_default_template()
                    return

            # Leer archivo existente
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    self._data = content
                    logger.info("Configuración cargada exitosamente desde %s", self._config_path)
            except Exception as exc:
                logger.error(
                    "Error al leer/parsear archivo de configuración '%s': %s. Usando configuración por defecto.",
                    self._config_path,
                    exc,
                )
                self._data = self._load_default_template()

    def get_all(self) -> Dict[str, Any]:
        """Obtiene una copia profunda de todos los datos de configuración."""
        with self._lock:
            return deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        """Obtiene el valor de una clave de primer nivel o devuelve el valor por defecto."""
        with self._lock:
            return deepcopy(self._data.get(key, default))

    def update_section(self, section: str, values: Dict[str, Any]) -> None:
        """Actualiza una sección de configuración fusionando sus valores."""
        with self._lock:
            if section not in self._data or not isinstance(self._data[section], dict):
                self._data[section] = {}
            self._data[section].update(values)

    def save(self) -> bool:
        """Persiste la configuración actual a disco de forma atómica y segura.

        Returns:
            bool: True si se guardó con éxito, False en caso de error.
        """
        with self._lock:
            temp_path = self._config_path.with_suffix(".tmp")
            try:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                apply_secure_permissions(self._config_path.parent, is_directory=True)

                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)

                apply_secure_permissions(temp_path, is_directory=False)
                temp_path.replace(self._config_path)
                apply_secure_permissions(self._config_path, is_directory=False)
                logger.info("Configuración guardada exitosamente en %s", self._config_path)
                return True
            except (OSError, PermissionError) as exc:
                logger.error("Error al guardar la configuración en %s: %s", self._config_path, exc)
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except OSError:
                    pass
                return False
            except Exception as exc:
                logger.error("Error inesperado al guardar la configuración en %s: %s", self._config_path, exc)
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except OSError:
                    pass
                return False

    # Propiedades y métodos utilitarios tipados

    @property
    def sampling_interval(self) -> int:
        """Intervalo de muestreo en segundos, acotado entre los límites configurados."""
        with self._lock:
            sampling = self._data.get("sampling", {})
            val = sampling.get("interval_seconds", 2)
            min_val = sampling.get("min_interval_seconds", 1)
            max_val = sampling.get("max_interval_seconds", 60)
            return max(min_val, min(max_val, int(val)))

    @sampling_interval.setter
    def sampling_interval(self, value: int) -> None:
        with self._lock:
            if "sampling" not in self._data:
                self._data["sampling"] = {}
            min_val = self._data["sampling"].get("min_interval_seconds", 1)
            max_val = self._data["sampling"].get("max_interval_seconds", 60)
            clamped = max(min_val, min(max_val, int(value)))
            self._data["sampling"]["interval_seconds"] = clamped

    @property
    def ipc_host(self) -> str:
        with self._lock:
            return str(self._data.get("ipc", {}).get("host", "127.0.0.1"))

    @property
    def ipc_port(self) -> int:
        with self._lock:
            return int(self._data.get("ipc", {}).get("port", 50555))

    @property
    def retention_policy(self) -> Dict[str, int]:
        with self._lock:
            retention = self._data.get("retention", {})
            return {
                "raw_readings_days": int(retention.get("raw_readings_days", 30)),
                "aggregates_days": int(retention.get("aggregates_days", 730)),
            }

    @property
    def alert_thresholds(self) -> Dict[str, float]:
        with self._lock:
            thresholds = self._data.get("alert_thresholds", {})
            return {
                "max_instant_power_w": float(thresholds.get("max_instant_power_w", 5500.0)),
                "max_daily_energy_kwh": float(thresholds.get("max_daily_energy_kwh", 35.0)),
                "monthly_budget": float(thresholds.get("monthly_budget", 120.0)),
            }

    @property
    def tariff(self) -> Dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("tariff", {}))

    def get_circuits(self) -> List[Circuit]:
        """Obtiene la lista de circuitos configurados convertidos a objetos Circuit."""
        with self._lock:
            circuits_data = self._data.get("circuits", [])
            circuits: List[Circuit] = []
            for item in circuits_data:
                try:
                    circuits.append(Circuit.from_dict(item))
                except Exception as exc:
                    logger.warning("Error al deserializar circuito %s: %s", item, exc)
            return circuits

    def set_circuits(self, circuits: List[Circuit]) -> None:
        """Actualiza la lista de circuitos en la configuración."""
        with self._lock:
            self._data["circuits"] = [c.to_dict() for c in circuits]
