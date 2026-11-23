"""Punto de entrada ejecutable y servicio principal del recolector en segundo plano.

Implementa el patrón Productor-Consumidor con cola acotada (queue.Queue):
- Hilo Productor: Genera lecturas, valida con ReadingValidator, encola y difunde por IPCServer.
  Maneja reintentos con backoff exponencial ante fallos de la fuente.
- Hilo Consumidor: Consume lotes de lecturas de la cola y las persiste en SQLite vía DatabaseManager.
- Servidor IPC: Transmite NDJSON en tiempo real a clientes (Dashboards).
- Trabajador de Agregaciones: Agregación periódica y política de retención.
- Manejo multiplataforma de señales (SIGINT, SIGTERM, SIGHUP, SIGUSR1) y archivo PID.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.collector.aggregator import AggregatorWorker
from src.collector.ipc_server import IPCServer
from src.collector.simulator import DataSourceError, EnergySimulator
from src.collector.validator import ReadingValidator
from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.logger import setup_logger
from src.common.models import Reading
from src.common.paths import apply_secure_permissions, get_data_dir

logger = logging.getLogger("collector")


def get_pid_file_path() -> Path:
    """Ruta al archivo que almacena el PID del proceso recolector activo."""
    return get_data_dir() / "collector.pid"


class CollectorService:
    """Servicio orquestador del recolector de telemetría energética."""

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        queue_maxsize: int = 1000,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        """Inicializa el servicio recolector.

        Args:
            config_manager: Instancia opcional de ConfigManager.
            db_manager: Instancia opcional de DatabaseManager.
            queue_maxsize: Tamaño máximo de la cola acotada de lecturas (1000 por defecto).
            initial_backoff: Tiempo inicial de espera en segundos ante fallos de la fuente.
            max_backoff: Tiempo máximo de espera en segundos ante fallos reiterados.
        """
        self.config_manager = config_manager or ConfigManager()
        self.db_manager = db_manager or DatabaseManager()
        self.initial_backoff = max(0.1, float(initial_backoff))
        self.max_backoff = max(self.initial_backoff, float(max_backoff))

        # Componentes del sistema
        circuits = self.config_manager.get_circuits()
        self.simulator = EnergySimulator(circuits=circuits)
        self.validator = ReadingValidator()
        self.ipc_server = IPCServer(
            host=self.config_manager.ipc_host,
            port=self.config_manager.ipc_port,
        )

        retention = self.config_manager.retention_policy
        self.aggregator = AggregatorWorker(
            db_manager=self.db_manager,
            interval_seconds=300.0,
            raw_retention_days=retention.get("raw_readings_days", 30),
            aggregates_retention_days=retention.get("aggregates_days", 730),
        )

        # Cola acotada para el patrón Productor-Consumidor
        self.queue: queue.Queue[Reading] = queue.Queue(maxsize=queue_maxsize)

        # Sincronización y control de ciclo de vida
        self._stop_event = threading.Event()
        self._producer_thread: Optional[threading.Thread] = None
        self._consumer_thread: Optional[threading.Thread] = None

        # Métricas de ejecución
        self._total_readings_produced = 0
        self._total_readings_persisted = 0
        self._last_reading_timestamp: Optional[float] = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Indica si el servicio recolector está en ejecución activa."""
        return self._is_running

    @property
    def total_readings_persisted(self) -> int:
        """Cantidad acumulada de lecturas guardadas exitosamente en la base de datos."""
        return self._total_readings_persisted

    def _write_pid_file(self) -> None:
        """Escribe el PID del proceso en un archivo temporal protegido en la carpeta de datos."""
        pid_file = get_pid_file_path()
        try:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            apply_secure_permissions(pid_file.parent, is_directory=True)

            with open(pid_file, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))

            apply_secure_permissions(pid_file, is_directory=False)
            logger.info("Archivo PID registrado en %s (PID=%d)", pid_file, os.getpid())
        except Exception as exc:
            logger.warning("No se pudo escribir el archivo PID '%s': %s", pid_file, exc)

    def _remove_pid_file(self) -> None:
        """Elimina el archivo PID al cerrar el proceso."""
        pid_file = get_pid_file_path()
        try:
            if pid_file.exists():
                pid_file.unlink()
                logger.info("Archivo PID removido exitosamente.")
        except Exception as exc:
            logger.warning("Error al eliminar archivo PID '%s': %s", pid_file, exc)

    def reload_config(self) -> None:
        """Recarga la configuración en caliente (ejecutado por señal SIGHUP en POSIX)."""
        logger.info("Recargando configuración en caliente...")
        self.config_manager.reload()

        # Actualizar circuitos en el simulador
        new_circuits = self.config_manager.get_circuits()
        if new_circuits:
            self.simulator.circuits = new_circuits
            self.db_manager.upsert_circuits(new_circuits)

        # Actualizar política de retención en el agregador
        retention = self.config_manager.retention_policy
        self.aggregator.raw_retention_days = retention.get("raw_readings_days", 30)
        self.aggregator.aggregates_retention_days = retention.get("aggregates_days", 730)

        logger.info(
            "Configuración recargada. Intervalo muestreo: %ds, Circuitos: %d",
            self.config_manager.sampling_interval,
            len(new_circuits),
        )

    def get_status_dict(
        self,
        source_status: str = "OK",
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construye el diccionario de estado del recolector para difusión IPC."""
        return {
            "active": self._is_running and not self._stop_event.is_set(),
            "pid": os.getpid(),
            "source_status": source_status,
            "total_readings": self._total_readings_persisted,
            "last_timestamp": self._last_reading_timestamp,
            "queue_size": self.queue.qsize(),
            "error_message": error_message,
        }

    def _producer_loop(self) -> None:
        """Bucle del hilo productor: captura, valida, encola y difunde lecturas.

        Implementa retroceso exponencial (backoff) ante fallos de la fuente.
        """
        logger.info("Hilo Productor iniciado.")
        backoff_delay = self.initial_backoff
        max_backoff = self.max_backoff
        in_error_state = False

        while not self._stop_event.is_set():
            try:
                # 1. Obtención de lecturas del simulador/sensores
                readings = self.simulator.generate_readings()

                # Si salimos de un estado de error previo, notificar recuperación
                if in_error_state:
                    logger.info("Fuente de datos restablecida. Reanudando captura normal.")
                    in_error_state = False
                    backoff_delay = self.initial_backoff
                    self.ipc_server.broadcast_status(self.get_status_dict(source_status="OK"))

                valid_count = 0
                for r in readings:
                    # 2. Validación de integridad
                    if self.validator.validate(r):
                        # 3. Encolado acotado
                        try:
                            self.queue.put(r, timeout=0.5)
                            valid_count += 1
                        except queue.Full:
                            logger.warning(
                                "Cola acotada llena (%d items). Descartando lectura de circuito %s.",
                                self.queue.maxsize,
                                r.circuit_id,
                            )
                        # 4. Difusión inmediata por IPC al Dashboard
                        self.ipc_server.broadcast_reading(r)

                if valid_count > 0:
                    self._total_readings_produced += valid_count
                    self._last_reading_timestamp = readings[-1].timestamp

                # Difusión periódica de estado general
                self.ipc_server.broadcast_status(self.get_status_dict(source_status="OK"))

                # Espera según el intervalo de muestreo configurado (interrumpible)
                sampling_interval = float(self.config_manager.sampling_interval)
                self._stop_event.wait(timeout=sampling_interval)

            except DataSourceError as exc:
                in_error_state = True
                err_msg = str(exc)
                logger.error(
                    "Fallo en la fuente de datos: %s. Reintentando con espera progresiva en %.1fs...",
                    err_msg,
                    backoff_delay,
                )
                self.ipc_server.broadcast_status(
                    self.get_status_dict(source_status="ERROR", error_message=err_msg)
                )

                # Espera progresiva antes del siguiente reintento
                self._stop_event.wait(timeout=backoff_delay)
                backoff_delay = min(max_backoff, backoff_delay * 2.0)

            except Exception as exc:
                logger.error("Excepción inesperada en hilo Productor: %s", exc, exc_info=True)
                self._stop_event.wait(timeout=1.0)

        logger.info("Hilo Productor finalizado.")

    def _consumer_loop(self) -> None:
        """Bucle del hilo consumidor: toma lotes de la cola y los persiste en SQLite."""
        logger.info("Hilo Consumidor iniciado.")

        # Continúa mientras no se detenga el servicio O mientras existan items pendientes en la cola
        while not self._stop_event.is_set() or not self.queue.empty():
            batch: List[Reading] = []
            try:
                # Espera bloqueante con timeout para procesar al menos 1 lectura
                item = self.queue.get(timeout=0.5)
                batch.append(item)
                self.queue.task_done()

                # Vaciado voraz (batch) de hasta 50 lecturas disponibles
                while len(batch) < 50:
                    try:
                        extra_item = self.queue.get_nowait()
                        batch.append(extra_item)
                        self.queue.task_done()
                    except queue.Empty:
                        break

            except queue.Empty:
                continue

            if batch:
                try:
                    inserted = self.db_manager.insert_readings_batch(batch)
                    self._total_readings_persisted += inserted
                    logger.debug(
                        "Lote de %d lecturas persistido en SQLite (total acumulado: %d)",
                        inserted,
                        self._total_readings_persisted,
                    )
                except Exception as exc:
                    logger.error("Error al persistir lote de %d lecturas en SQLite: %s", len(batch), exc)

        logger.info("Hilo Consumidor finalizado con cola vacía.")

    def _drain_remaining_queue(self) -> None:
        """Asegura el vaciado total de cualquier lectura restante en la cola hacia la base de datos."""
        pending: List[Reading] = []
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                pending.append(item)
                self.queue.task_done()
            except queue.Empty:
                break

        if pending:
            logger.info("Guardando %d lecturas pendientes antes del cierre final...", len(pending))
            try:
                self.db_manager.insert_readings_batch(pending)
                self._total_readings_persisted += len(pending)
            except Exception as exc:
                logger.error("Error al persistir lecturas finales de cola: %s", exc)

    def start(self) -> None:
        """Inicia todos los componentes y los hilos productor y consumidor."""
        if self._is_running:
            return

        logger.info("Iniciando servicio recolector...")
        self._stop_event.clear()
        self._is_running = True

        # 1. Registrar circuitos iniciales en SQLite para integridad referencial
        circuits = self.config_manager.get_circuits()
        self.db_manager.upsert_circuits(circuits)

        # 2. Registrar archivo PID
        self._write_pid_file()

        # 3. Iniciar Servidor IPC
        try:
            self.ipc_server.start()
        except Exception as exc:
            logger.error("No se pudo iniciar el servidor IPC (se continuará sin difusión remota): %s", exc)

        # 4. Iniciar hilo consumidor
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop,
            name="Collector-Consumer",
            daemon=False,  # No daemon para garantizar vaciado seguro
        )
        self._consumer_thread.start()

        # 5. Iniciar hilo productor
        self._producer_thread = threading.Thread(
            target=self._producer_loop,
            name="Collector-Producer",
            daemon=True,
        )
        self._producer_thread.start()

        # 6. Iniciar hilo de agregaciones periódicas
        self.aggregator.start()

        logger.info("Servicio recolector en funcionamiento con éxito.")

    def stop(self) -> None:
        """Cierre ordenado: detiene productor, vacía cola a SQLite, detiene IPC y finaliza."""
        if not self._is_running:
            return

        logger.info("Iniciando proceso de apagado ordenado del recolector...")
        self._is_running = False
        self._stop_event.set()

        # 1. Esperar al hilo productor
        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=3.0)
            self._producer_thread = None

        # 2. Esperar al hilo consumidor para vaciar la cola
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5.0)
            self._consumer_thread = None

        # 3. Vaciado final de seguridad por si quedaron elementos
        self._drain_remaining_queue()

        # 4. Detener hilo de agregaciones
        self.aggregator.stop(timeout=3.0)

        # 5. Detener servidor IPC
        self.ipc_server.stop()

        # 6. Checkpoint de base de datos y cierre
        try:
            self.db_manager.checkpoint_wal()
            self.db_manager.close()
        except Exception as exc:
            logger.warning("Aviso al cerrar base de datos: %s", exc)

        # 7. Eliminar archivo PID
        self._remove_pid_file()

        logger.info(
            "Apagado ordenado finalizado. Total lecturas persistidas: %d.",
            self._total_readings_persisted,
        )


def _setup_signal_handlers(service: CollectorService) -> None:
    """Registra manejadores de señales compatibles con el sistema operativo actual."""

    def _sig_handler(signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Señal de terminación recibida: %s. Procediendo al apagado ordenado.", sig_name)
        service.stop()

    # SIGINT (Ctrl+C) y SIGTERM funcionan tanto en Windows como en POSIX
    try:
        signal.signal(signal.SIGINT, _sig_handler)
    except Exception as exc:
        logger.debug("No se pudo enlazar SIGINT: %s", exc)

    try:
        signal.signal(signal.SIGTERM, _sig_handler)
    except Exception as exc:
        logger.debug("No se pudo enlazar SIGTERM: %s", exc)

    # En Windows, CTRL_BREAK_EVENT se mapea a SIGBREAK
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _sig_handler)
        except Exception as exc:
            logger.debug("No se pudo enlazar SIGBREAK: %s", exc)

    # Señales específicas de sistemas POSIX (Linux / macOS)
    if sys.platform != "win32":  # pragma: no cover
        if hasattr(signal, "SIGHUP"):

            def _sighup_handler(signum: int, frame: Any) -> None:
                logger.info("Señal SIGHUP recibida. Recargando configuración...")
                service.reload_config()

            try:
                signal.signal(signal.SIGHUP, _sighup_handler)
            except Exception as exc:
                logger.debug("No se pudo enlazar SIGHUP: %s", exc)

        if hasattr(signal, "SIGUSR1"):

            def _sigusr1_handler(signum: int, frame: Any) -> None:
                logger.info("Señal SIGUSR1 recibida. Disparando agregación inmediata...")
                service.aggregator.trigger_immediate()

            try:
                signal.signal(signal.SIGUSR1, _sigusr1_handler)
            except Exception as exc:
                logger.debug("No se pudo enlazar SIGUSR1: %s", exc)


def main() -> int:
    """Función principal para ejecución directa del módulo."""
    setup_logger("collector")
    logger.info("=== Iniciando Sistema de Monitoreo Energético (Collector) ===")
    logger.info("Plataforma: %s | Python: %s", sys.platform, sys.version.split()[0])

    service = CollectorService()
    _setup_signal_handlers(service)

    try:
        service.start()
        # Bucle principal pasivo a la espera de señales de terminación
        while service.is_running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupción por teclado detectada.")
    finally:
        service.stop()

    logger.info("=== Proceso Collector cerrado exitosamente ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
