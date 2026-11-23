"""Cliente IPC dual en segundo plano con reconexión automática continua.

Ejecuta un hilo dedicado QThread de PySide6 para mantener una conexión por socket Unix (Linux/POSIX)
o TCP (Windows) con el recolector, parsear eventos en formato NDJSON y emitir señales Qt
hacia la interfaz de usuario de forma asíncrona sin bloquear el hilo principal.
"""

from __future__ import annotations

import json
import logging
import socket
import sys
import time
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import QThread, Signal

from src.common.paths import get_socket_path

logger = logging.getLogger(__name__)


class IPCClientThread(QThread):
    """Hilo cliente IPC dual (AF_UNIX / TCP) que recibe telemetría NDJSON del recolector."""

    # Señales Qt emitidas al recibir datos
    reading_received = Signal(dict)
    status_received = Signal(dict)
    connection_changed = Signal(bool)

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 50555,
        socket_path: Optional[Union[str, Path]] = None,
        use_unix_socket: Optional[bool] = None,
        reconnect_interval_seconds: float = 2.0,
        parent: Optional[object] = None,
    ) -> None:
        """Inicializa el cliente IPC.

        Args:
            host: Dirección IP del servidor recolector (para transporte TCP).
            port: Puerto TCP del servidor recolector.
            socket_path: Ruta al archivo .sock para AF_UNIX. Si es None, usa get_socket_path().
            use_unix_socket: Si es True, fuerza AF_UNIX. Si es False, fuerza TCP.
                             Por defecto (None), usa AF_UNIX en Linux/POSIX y TCP en Windows.
            reconnect_interval_seconds: Intervalo de reintento ante desconexión (2.0s por defecto).
            parent: Objeto QObject padre opcional.
        """
        super().__init__(parent)
        self.host = host
        self.port = port
        self.reconnect_interval = reconnect_interval_seconds

        # Selección de transporte según plataforma
        if use_unix_socket is None:
            self.use_unix_socket = (sys.platform != "win32") and hasattr(socket, "AF_UNIX")
        else:
            self.use_unix_socket = bool(use_unix_socket) and hasattr(socket, "AF_UNIX")

        if self.use_unix_socket:
            self.socket_path = Path(socket_path or get_socket_path())
        else:
            self.socket_path = Path(socket_path) if socket_path else None

        self._is_running = True
        self._is_connected = False
        self._sock: Optional[socket.socket] = None

    @property
    def is_connected(self) -> bool:
        """Indica si existe una conexión IPC activa con el recolector."""
        return self._is_connected

    def stop(self) -> None:
        """Solicita la detención limpia del hilo y cierra el socket."""
        self._is_running = False
        self._close_socket()
        self.wait(3000)

    def _close_socket(self) -> None:
        """Cierra el socket actual de forma segura."""
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

        if self._is_connected:
            self._is_connected = False
            self.connection_changed.emit(False)

    def run(self) -> None:
        """Bucle principal de conexión y lectura continua con reconexión automática."""
        if self.use_unix_socket:
            logger.info("Cliente IPC iniciado hacia socket Unix: %s (Transporte: AF_UNIX)", self.socket_path)
        else:
            logger.info("Cliente IPC iniciado hacia %s:%d (Transporte: TCP)", self.host, self.port)

        while self._is_running:
            # 1. Intentar conexión (AF_UNIX o TCP)
            try:
                if self.use_unix_socket:
                    self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._sock.settimeout(3.0)
                    self._sock.connect(str(self.socket_path))
                else:
                    self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._sock.settimeout(3.0)
                    self._sock.connect((self.host, self.port))

                self._sock.settimeout(1.0)  # Timeout para lecturas periódicas

                self._is_connected = True
                self.connection_changed.emit(True)
                logger.info("Conexión IPC establecida exitosamente con el recolector.")

                # 2. Bucle de lectura NDJSON
                buffer = ""
                while self._is_running and self._is_connected:
                    try:
                        chunk = self._sock.recv(4096).decode("utf-8")
                        if not chunk:
                            # Servidor cerró la conexión
                            logger.warning("El servidor recolector cerró la conexión IPC.")
                            break

                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            self._process_message(line)

                    except socket.timeout:
                        # Timeout normal para chequear self._is_running
                        continue
                    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
                        logger.warning("Conexión perdida con el recolector: %s", exc)
                        break
                    except Exception as exc:
                        logger.error("Error al leer datos del socket IPC: %s", exc)
                        break

            except (ConnectionRefusedError, FileNotFoundError, socket.timeout, OSError):
                # Recolector no está corriendo o puerto/socket no disponible aún
                pass
            finally:
                self._close_socket()

            # Esperar antes de intentar reconectar si aún estamos corriendo
            if self._is_running:
                time.sleep(self.reconnect_interval)

        logger.info("Hilo de cliente IPC finalizado.")

    def _process_message(self, line: str) -> None:
        """Parsea un mensaje JSON y emite la señal correspondiente."""
        try:
            msg = json.loads(line)
            msg_type = msg.get("type")
            data = msg.get("data", {})

            if msg_type == "reading":
                self.reading_received.emit(data)
            elif msg_type == "status":
                self.status_received.emit(data)
        except json.JSONDecodeError as exc:
            logger.debug("Mensaje NDJSON inválido descartado: %s (%s)", line, exc)
