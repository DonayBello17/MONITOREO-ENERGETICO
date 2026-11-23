"""Servidor IPC dual multiplataforma (AF_UNIX en Linux, TCP en Windows).

Permite que una o múltiples instancias de interfaces gráficas (Dashboard)
se conecten concurrentemente mediante socket Unix local (POSIX) o TCP 127.0.0.1 (Windows)
para recibir flujo de datos y estados en formato JSON delimitado por salto de línea (NDJSON).
Maneja desconexiones abruptas sin interrumpir el proceso recolector.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from src.common.models import Reading
from src.common.paths import apply_secure_permissions, get_socket_path

logger = logging.getLogger(__name__)


class IPCServer:
    """Servidor IPC dual local para difusión de telemetría y estado vía NDJSON."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 50555,
        socket_path: Optional[Union[str, Path]] = None,
        use_unix_socket: Optional[bool] = None,
    ) -> None:
        """Inicializa el servidor IPC.

        Args:
            host: Dirección IP de escucha TCP (127.0.0.1 por defecto).
            port: Puerto TCP a enlazar (por defecto 50555; 0 para asignación dinámica).
            socket_path: Ruta al archivo .sock para AF_UNIX. Si es None, usa get_socket_path().
            use_unix_socket: Si es True, fuerza AF_UNIX. Si es False, fuerza TCP.
                             Por defecto (None), usa AF_UNIX en Linux/POSIX y TCP en Windows.
        """
        self.host = host
        self.requested_port = port
        self.actual_port = port

        # Determinación de transporte: AF_UNIX en POSIX (Linux), TCP en Windows
        if use_unix_socket is None:
            self.use_unix_socket = (sys.platform != "win32") and hasattr(socket, "AF_UNIX")
        else:
            self.use_unix_socket = bool(use_unix_socket) and hasattr(socket, "AF_UNIX")

        if self.use_unix_socket:
            self.socket_path = Path(socket_path or get_socket_path())
        else:
            self.socket_path = Path(socket_path) if socket_path else None

        self._server_sock: Optional[socket.socket] = None
        self._is_running = False
        self._stop_event = threading.Event()

        self._clients: Set[socket.socket] = set()
        self._clients_lock = threading.Lock()

        self._accept_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        """Indica si el servidor está en ejecución."""
        return self._is_running

    @property
    def port(self) -> int:
        """Retorna el puerto TCP real en el que está escuchando el servidor."""
        return self.actual_port

    @property
    def client_count(self) -> int:
        """Retorna la cantidad de clientes actualmente conectados."""
        with self._clients_lock:
            return len(self._clients)

    def start(self) -> None:
        """Inicia el servidor IPC (AF_UNIX o TCP) y el hilo de aceptación de conexiones."""
        if self._is_running:
            return

        self._stop_event.clear()
        try:
            if self.use_unix_socket:
                logger.info("Transporte IPC activado: AF_UNIX (ruta: %s)", self.socket_path)
                # Limpiar socket anterior si existe
                if self.socket_path.exists():
                    try:
                        self.socket_path.unlink()
                        logger.debug("Socket IPC anterior eliminado: %s", self.socket_path)
                    except OSError as exc:
                        logger.warning("No se pudo eliminar socket previo %s: %s", self.socket_path, exc)

                # Asegurar directorio contenedor con permisos restrictivos
                self.socket_path.parent.mkdir(parents=True, exist_ok=True)
                apply_secure_permissions(self.socket_path.parent, is_directory=True)

                self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._server_sock.bind(str(self.socket_path))

                # Asignar permisos restrictivos 0o600 al socket en POSIX
                try:
                    os.chmod(str(self.socket_path), 0o600)
                except OSError as exc:
                    logger.warning("No se pudieron asignar permisos 0o600 al socket %s: %s", self.socket_path, exc)

                self._server_sock.listen(10)
                self._server_sock.settimeout(0.5)
                self._is_running = True
                logger.info("Servidor IPC iniciado en socket Unix: %s (permisos 0o600)", self.socket_path)
            else:
                logger.info("Transporte IPC activado: TCP (%s:%d)", self.host, self.requested_port)
                self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Reutilización de dirección para evitar demoras por TIME_WAIT al reiniciar
                self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_sock.bind((self.host, self.requested_port))
                self.actual_port = self._server_sock.getsockname()[1]
                self._server_sock.listen(10)
                self._server_sock.settimeout(0.5)
                self._is_running = True
                logger.info("Servidor IPC iniciado en %s:%d", self.host, self.actual_port)

            self._accept_thread = threading.Thread(
                target=self._accept_loop,
                name="IPCServer-AcceptThread",
                daemon=True,
            )
            self._accept_thread.start()
        except OSError as exc:
            dest = str(self.socket_path) if self.use_unix_socket else f"{self.host}:{self.requested_port}"
            logger.critical("No se pudo iniciar el servidor IPC en %s: %s", dest, exc)
            self._cleanup_sockets()
            raise

    def stop(self) -> None:
        """Detiene el servidor y cierra todas las conexiones de forma limpia."""
        if not self._is_running:
            return

        logger.info("Deteniendo servidor IPC...")
        self._is_running = False
        self._stop_event.set()

        self._cleanup_sockets()

        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None

        logger.info("Servidor IPC detenido con éxito.")

    def _cleanup_sockets(self) -> None:
        """Cierra el socket principal del servidor y todos los sockets de clientes."""
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

        # Limpiar archivo de socket Unix al detener
        if self.use_unix_socket and self.socket_path and self.socket_path.exists():
            try:
                self.socket_path.unlink()
                logger.debug("Archivo de socket Unix eliminado: %s", self.socket_path)
            except OSError as exc:
                logger.debug("Error al eliminar socket Unix al detener: %s", exc)

        with self._clients_lock:
            for client in list(self._clients):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

    def _accept_loop(self) -> None:
        """Bucle principal de escucha y admisión de conexiones de clientes."""
        while not self._stop_event.is_set():
            if not self._server_sock:
                break
            try:
                client_sock, client_addr = self._server_sock.accept()
                if isinstance(client_addr, tuple) and len(client_addr) >= 2:
                    addr_desc = f"{client_addr[0]}:{client_addr[1]}"
                    thread_name = f"IPCClientMonitor-{client_addr[1]}"
                else:
                    addr_desc = f"unix:{id(client_sock)}"
                    thread_name = f"IPCClientMonitor-{id(client_sock)}"

                logger.info("Nuevo cliente IPC conectado desde %s", addr_desc)
                client_sock.settimeout(None)

                with self._clients_lock:
                    self._clients.add(client_sock)

                # Hilo ligero para detectar desconexión rápida por parte del cliente
                reader_thread = threading.Thread(
                    target=self._client_monitor_loop,
                    args=(client_sock, addr_desc),
                    name=thread_name,
                    daemon=True,
                )
                reader_thread.start()

            except socket.timeout:
                continue
            except OSError:
                # Ocurre cuando el socket del servidor se cierra durante stop()
                break
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.error("Error inesperado en accept loop de IPC: %s", exc)

    def _client_monitor_loop(self, client: socket.socket, addr_desc: str) -> None:
        """Monitorea el socket del cliente para detectar cierre de conexión (EOF)."""
        try:
            while not self._stop_event.is_set():
                data = client.recv(1024)
                if not data:
                    # Conexión cerrada normalmente por el cliente
                    break
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass
        finally:
            self._remove_client(client, addr_desc)

    def _remove_client(self, client: socket.socket, addr_desc: Optional[str] = None) -> None:
        """Elimina de forma segura un cliente de la lista activa y cierra su socket."""
        with self._clients_lock:
            if client in self._clients:
                self._clients.remove(client)
                try:
                    client.close()
                except Exception:
                    pass
                if addr_desc:
                    logger.info("Cliente IPC desconectado: %s", addr_desc)

    def broadcast(self, event: Dict[str, Any]) -> int:
        """Transmite un evento a todos los clientes conectados en formato NDJSON.

        Maneja desconexiones abruptas sin lanzar excepciones no controladas.

        Args:
            event: Diccionario representativo del evento (debe ser serializable a JSON).

        Returns:
            int: Cantidad de clientes a los que se envió el mensaje con éxito.
        """
        if not self._is_running:
            return 0

        try:
            raw_payload = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            logger.error("Error al serializar evento IPC a JSON: %s", exc)
            return 0

        success_count = 0
        dead_clients: List[socket.socket] = []

        with self._clients_lock:
            current_clients = list(self._clients)

        for client in current_clients:
            try:
                client.sendall(raw_payload)
                success_count += 1
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as exc:
                logger.debug("Cliente IPC desconectado durante broadcast: %s", exc)
                dead_clients.append(client)

        for dead in dead_clients:
            self._remove_client(dead)

        return success_count

    def broadcast_reading(self, reading: Reading) -> int:
        """Transmite una lectura individual validada a todos los clientes conectados."""
        event = {
            "type": "reading",
            "data": reading.to_dict(),
        }
        return self.broadcast(event)

    def broadcast_status(self, status_data: Dict[str, Any]) -> int:
        """Transmite el estado general del recolector a todos los clientes conectados."""
        event = {
            "type": "status",
            "data": status_data,
        }
        return self.broadcast(event)
