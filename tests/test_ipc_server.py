"""Pruebas unitarias para el servidor y cliente de comunicación entre procesos (IPC dual)."""

import json
import logging
import os
import socket
import sys
import time
from unittest.mock import MagicMock, patch
import pytest

from src.collector.ipc_server import IPCServer
from src.dashboard.ipc_client import IPCClientThread
from src.common.models import Reading
from src.common.paths import get_socket_path


@pytest.fixture
def ipc_server():
    """Inicia un servidor IPC en TCP (puerto aleatorio disponible) y asegura su detención."""
    server = IPCServer(host="127.0.0.1", port=0, use_unix_socket=False)
    server.start()
    yield server
    server.stop()


def test_ipc_transport_selection():
    """Verifica que el transporte predeterminado sea TCP en Windows y AF_UNIX en Linux."""
    # En Windows debe seleccionar TCP
    with patch("sys.platform", "win32"):
        server_win = IPCServer(host="127.0.0.1", port=50555)
        assert server_win.use_unix_socket is False

        client_win = IPCClientThread(host="127.0.0.1", port=50555)
        assert client_win.use_unix_socket is False

    # En Linux debe seleccionar AF_UNIX si el socket lo soporta
    with patch("sys.platform", "linux"):
        with patch.object(socket, "AF_UNIX", 1, create=True):
            server_linux = IPCServer(host="127.0.0.1", port=50555)
            assert server_linux.use_unix_socket is True
            assert server_linux.socket_path is not None

            client_linux = IPCClientThread(host="127.0.0.1", port=50555)
            assert client_linux.use_unix_socket is True
            assert client_linux.socket_path is not None


def test_ipc_logging_transport(caplog):
    """Verifica que se registre en el log qué transporte IPC se activó."""
    caplog.set_level(logging.INFO)

    # Prueba con TCP
    server_tcp = IPCServer(host="127.0.0.1", port=0, use_unix_socket=False)
    server_tcp.start()
    server_tcp.stop()

    assert any("Transporte IPC activado: TCP" in record.message or "Servidor IPC iniciado en" in record.message for record in caplog.records)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Requiere soporte socket.AF_UNIX nativo (Linux/POSIX)")
def test_ipc_server_unix_socket_end_to_end(tmp_path):
    """Verifica el funcionamiento completo de AF_UNIX: creación, permisos 0o600, transmisión NDJSON y limpieza."""
    sock_path = tmp_path / "test_collector.sock"

    # 1. Crear archivo previo para comprobar que se limpia al iniciar
    sock_path.write_text("antiguo_socket", encoding="utf-8")
    assert sock_path.exists()

    server = IPCServer(socket_path=sock_path, use_unix_socket=True)
    server.start()
    assert server.is_running is True
    assert sock_path.exists()

    # Verificar permisos 0o600 en POSIX
    if os.name == "posix":
        mode = oct(os.stat(sock_path).st_mode & 0o777)
        assert mode == "0o600"

    # Conectar cliente mediante socket UNIX
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock_path))
    time.sleep(0.1)
    assert server.client_count == 1

    # Transmitir lectura
    sample = Reading(
        timestamp=1700000000.0,
        circuit_id="circ_01",
        voltage=120.0,
        current=2.0,
        power_w=240.0,
        energy_kwh=0.5,
    )
    sent = server.broadcast_reading(sample)
    assert sent == 1

    # Leer mensaje NDJSON
    raw = client.recv(1024).decode("utf-8")
    assert raw.endswith("\n")
    data = json.loads(raw.strip())
    assert data["type"] == "reading"
    assert data["data"]["circuit_id"] == "circ_01"

    client.close()
    server.stop()
    assert server.is_running is False
    # El archivo de socket debe ser eliminado al detener
    assert not sock_path.exists()


def test_ipc_server_broadcast_reading(ipc_server):
    """Verifica que las lecturas se transmitan en formato NDJSON a múltiples clientes."""
    port = ipc_server.port
    assert port > 0

    # Conectar dos clientes
    client1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client1.connect(("127.0.0.1", port))
    client2.connect(("127.0.0.1", port))

    # Breve pausa para que el accept_loop los registre
    time.sleep(0.1)
    assert ipc_server.client_count == 2

    # Transmitir lectura
    sample_reading = Reading(
        timestamp=1700000000.0,
        circuit_id="circ_01",
        voltage=120.2,
        current=1.5,
        power_w=180.3,
        energy_kwh=10.5,
    )
    sent_count = ipc_server.broadcast_reading(sample_reading)
    assert sent_count == 2

    # Leer mensaje en cliente 1
    raw1 = client1.recv(1024).decode("utf-8")
    assert raw1.endswith("\n")
    data1 = json.loads(raw1.strip())
    assert data1["type"] == "reading"
    assert data1["data"]["circuit_id"] == "circ_01"
    assert data1["data"]["voltage"] == 120.2

    # Leer mensaje en cliente 2
    raw2 = client2.recv(1024).decode("utf-8")
    data2 = json.loads(raw2.strip())
    assert data2["type"] == "reading"
    assert data2["data"]["circuit_id"] == "circ_01"

    client1.close()
    client2.close()


def test_ipc_server_broadcast_status(ipc_server):
    """Verifica la transmisión de estados del recolector en formato NDJSON."""
    port = ipc_server.port
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    time.sleep(0.1)

    status_data = {
        "active": True,
        "pid": 1234,
        "source_status": "OK",
        "total_readings": 150,
        "last_timestamp": 1700000000.0,
    }
    ipc_server.broadcast_status(status_data)

    raw = client.recv(1024).decode("utf-8")
    data = json.loads(raw.strip())
    assert data["type"] == "status"
    assert data["data"]["pid"] == 1234
    assert data["data"]["total_readings"] == 150

    client.close()


def test_ipc_server_handles_abrupt_disconnect(ipc_server):
    """Verifica que desconexiones abruptas de clientes no rompan el servidor."""
    port = ipc_server.port

    # Conectar cliente 1 y 2
    c1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c1.connect(("127.0.0.1", port))
    c2.connect(("127.0.0.1", port))
    time.sleep(0.1)
    assert ipc_server.client_count == 2

    # Desconexión abrupta de c1 (cierre forzado sin lectura previa)
    c1.close()
    time.sleep(0.1)

    # El servidor debe continuar funcionando y transmitir a c2
    status = {"active": True, "source_status": "OK"}
    sent = ipc_server.broadcast_status(status)
    assert sent >= 1  # Al menos c2 recibe el mensaje

    raw = c2.recv(1024).decode("utf-8")
    data = json.loads(raw.strip())
    assert data["type"] == "status"

    c2.close()
