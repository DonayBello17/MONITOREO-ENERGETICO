"""Módulo de agregación periódica y aplicación de políticas de retención.

Ejecuta en segundo plano el cálculo de agregados temporales (horario, diario, mensual)
y purga lecturas históricas según los periodos de retención configurados.
Permite el disparo manual e inmediato de la agregación de forma segura para hilos.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from src.common.database import DatabaseManager

logger = logging.getLogger(__name__)


class AggregatorWorker:
    """Hilo programado para el procesamiento de agregados estadísticos y retención."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        interval_seconds: float = 300.0,
        raw_retention_days: int = 30,
        aggregates_retention_days: int = 730,
    ) -> None:
        """Inicializa el trabajador de agregaciones.

        Args:
            db_manager: Administrador de base de datos para operaciones analíticas.
            interval_seconds: Intervalo periódico entre agregaciones automáticas (en segundos).
            raw_retention_days: Días de retención para lecturas crudas.
            aggregates_retention_days: Días de retención para tablas agregadas.
        """
        self.db_manager = db_manager
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.raw_retention_days = raw_retention_days
        self.aggregates_retention_days = aggregates_retention_days

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._run_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

        self._last_run_timestamp: Optional[float] = None
        self._last_run_stats: Dict[str, Any] = {}

    @property
    def is_alive(self) -> bool:
        """Indica si el hilo de agregación está activo."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_run_timestamp(self) -> Optional[float]:
        """Timestamp de la última agregación completada."""
        return self._last_run_timestamp

    @property
    def last_run_stats(self) -> Dict[str, Any]:
        """Estadísticas resultantes de la última agregación."""
        return dict(self._last_run_stats)

    def start(self) -> None:
        """Inicia el hilo programado de agregaciones."""
        if self.is_alive:
            return

        self._stop_event.clear()
        self._wake_event.clear()

        self._thread = threading.Thread(
            target=self._worker_loop,
            name="AggregatorWorker-Thread",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "AggregatorWorker iniciado con intervalo de %.1f segundos.",
            self.interval_seconds,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Detiene el hilo de agregación de forma limpia."""
        if not self.is_alive:
            return

        logger.info("Deteniendo AggregatorWorker...")
        self._stop_event.set()
        self._wake_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("AggregatorWorker detenido.")

    def trigger_immediate(self) -> bool:
        """Fuerza una ejecución inmediata de las agregaciones y retención.

        Despierta al hilo de trabajo si está esperando su intervalo regular.
        Es seguro para ser invocado desde múltiples hilos o manejadores de señales.

        Returns:
            bool: True si la señal de disparo inmediato fue enviada con éxito.
        """
        if not self.is_alive:
            logger.warning("Intento de disparar agregación pero el hilo AggregatorWorker no está corriendo.")
            return False

        logger.info("Disparo manual de agregación solicitado.")
        self._wake_event.set()
        return True

    def run_aggregation(self) -> Dict[str, Any]:
        """Ejecuta un ciclo completo de cálculo de agregados y política de retención.

        Retorna un resumen de las operaciones realizadas.
        """
        with self._run_lock:
            start_time = time.time()
            logger.info("Iniciando ciclo de agregación y retención...")

            stats: Dict[str, Any] = {
                "timestamp": start_time,
                "hourly_updated": 0,
                "daily_updated": 0,
                "monthly_updated": 0,
                "retention": {},
                "duration_seconds": 0.0,
                "status": "OK",
            }

            try:
                # 1. Agregados horarios, diarios y mensuales
                stats["hourly_updated"] = self.db_manager.calculate_hourly_aggregates()
                stats["daily_updated"] = self.db_manager.calculate_daily_aggregates()
                stats["monthly_updated"] = self.db_manager.calculate_monthly_aggregates()

                # 2. Aplicación de política de retención
                stats["retention"] = self.db_manager.apply_retention_policy(
                    raw_days=self.raw_retention_days,
                    aggregates_days=self.aggregates_retention_days,
                )

                # 3. Checkpoint WAL
                self.db_manager.checkpoint_wal()

                elapsed = time.time() - start_time
                stats["duration_seconds"] = round(elapsed, 3)
                self._last_run_timestamp = start_time
                self._last_run_stats = stats

                logger.info(
                    "Ciclo de agregación completado en %.3fs: Horario=%d, Diario=%d, Mensual=%d, Retención=%s",
                    elapsed,
                    stats["hourly_updated"],
                    stats["daily_updated"],
                    stats["monthly_updated"],
                    stats["retention"],
                )
            except Exception as exc:
                stats["status"] = "ERROR"
                stats["error"] = str(exc)
                logger.error("Error durante el ciclo de agregación: %s", exc)

            return stats

    def _worker_loop(self) -> None:
        """Bucle en segundo plano que espera el intervalo o la señal de disparo manual."""
        while not self._stop_event.is_set():
            # Espera interruptible por wake_event o timeout de intervalo
            woken = self._wake_event.wait(timeout=self.interval_seconds)

            if self._stop_event.is_set():
                break

            if woken:
                self._wake_event.clear()

            self.run_aggregation()
