"""Pruebas unitarias y de integración para CollectorService (main.py)."""

import os
import time
import pytest

from src.collector.main import CollectorService, get_pid_file_path
from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Circuit


@pytest.fixture
def test_env(tmp_path):
    """Crea una base de datos temporal y configuración para pruebas del recolector."""
    db_file = tmp_path / "test_energy.db"
    db = DatabaseManager(db_path=db_file)

    config_file = tmp_path / "test_config.json"
    cfg = ConfigManager(config_path=config_file)
    cfg.sampling_interval = 1  # 1 segundo para pruebas rápidas
    # Configurar puerto efímero para evitar choques
    cfg.update_section("ipc", {"host": "127.0.0.1", "port": 0})

    yield db, cfg, tmp_path
    db.close()


def test_collector_service_lifecycle_and_drain(test_env):
    """Verifica que el servicio recolector genere, encole, persista lecturas y vacíe la cola al detenerse."""
    db, cfg, tmp_path = test_env

    service = CollectorService(config_manager=cfg, db_manager=db)
    service.start()
    assert service.is_running is True

    # Verificar que el archivo PID exista y contenga el PID del proceso
    pid_file = get_pid_file_path()
    assert pid_file.exists()
    with open(pid_file, "r", encoding="utf-8") as f:
        stored_pid = int(f.read().strip())
    assert stored_pid == os.getpid()

    # Dejar operar al servicio unos instantes (1.5 segundos para capturar y persistir lecturas)
    time.sleep(1.5)

    # Detener servicio (debe vaciar la cola sin perder datos)
    service.stop()
    assert service.is_running is False

    # El archivo PID debe haber sido removido
    assert not pid_file.exists()

    # Verificar que las lecturas se hayan guardado en la base de datos
    readings = db.get_readings()
    assert len(readings) > 0
    assert service.total_readings_persisted == len(readings)
    assert service.queue.empty()


def test_collector_backoff_and_recovery(test_env):
    """Verifica que el recolector maneje fallos de la fuente con espera progresiva y se recupere."""
    db, cfg, tmp_path = test_env

    service = CollectorService(config_manager=cfg, db_manager=db, initial_backoff=0.3)
    # Inyectar fallo antes de iniciar
    service.simulator.inject_fault(enabled=True, message="Sensor I2C colgado")

    service.start()
    time.sleep(0.8)

    status_error = service.get_status_dict()
    # Durante el fallo no se generan lecturas válidas
    assert service.total_readings_persisted == 0

    # Desactivar fallo para permitir la recuperación
    service.simulator.inject_fault(enabled=False)
    time.sleep(1.2)

    # El servicio debió recuperarse y comenzar a persistir lecturas
    service.stop()
    assert service.total_readings_persisted > 0
