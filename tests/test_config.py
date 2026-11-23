"""Pruebas unitarias para ConfigManager, Paths y Modelos."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.common.config_manager import ConfigManager
from src.common.models import Alert, Circuit, Reading
from src.common.paths import (
    apply_secure_permissions,
    ensure_directory,
    get_config_dir,
    get_data_dir,
)


def test_models_serialization() -> None:
    """Verifica que los modelos serialicen y deserialicen correctamente."""
    circuit = Circuit(id="c1", name="Nevera", location="Cocina", nominal_power_w=350.0)
    c_dict = circuit.to_dict()
    assert Circuit.from_dict(c_dict) == circuit

    reading = Reading(
        timestamp=1700000000.0,
        circuit_id="c1",
        voltage=120.5,
        current=2.1,
        power_w=253.05,
        energy_kwh=0.015,
    )
    r_dict = reading.to_dict()
    assert Reading.from_dict(r_dict) == reading
    assert reading.to_tuple() == (1700000000.0, "c1", 120.5, 2.1, 253.05, 0.015)

    alert = Alert(
        timestamp=1700000000.0,
        circuit_id="c1",
        alert_type="OVERPOWER",
        severity="WARNING",
        message="Potencia excesiva",
        value=3000.0,
        threshold=2500.0,
    )
    a_dict = alert.to_dict()
    assert Alert.from_dict(a_dict).message == alert.message


def test_config_manager_creation_and_reload(tmp_path: Path) -> None:
    """Verifica que ConfigManager copie la plantilla por defecto y maneje recargas."""
    template_file = tmp_path / "default_config.json"
    template_data = {
        "sampling": {"interval_seconds": 3, "min_interval_seconds": 1, "max_interval_seconds": 60},
        "ipc": {"host": "127.0.0.1", "port": 50555},
        "tariff": {"base_rate_per_kwh": 0.20},
        "retention": {"raw_readings_days": 30, "aggregates_days": 730},
        "alert_thresholds": {
            "max_instant_power_w": 5000.0,
            "max_daily_energy_kwh": 35.0,
            "monthly_budget": 120.0,
        },
        "circuits": [
            {"id": "c1", "name": "Nevera", "location": "Cocina", "nominal_power_w": 350.0}
        ],
    }
    with open(template_file, "w", encoding="utf-8") as f:
        json.dump(template_data, f)

    user_config_file = tmp_path / "user_config.json"
    cfg = ConfigManager(config_path=user_config_file, default_template_path=template_file)

    assert user_config_file.exists()
    assert cfg.sampling_interval == 3
    assert cfg.ipc_port == 50555
    assert len(cfg.get_circuits()) == 1

    # Modificar y guardar
    cfg.sampling_interval = 10
    saved = cfg.save()
    assert saved is True

    # Recargar desde disco en otra instancia
    cfg2 = ConfigManager(config_path=user_config_file, default_template_path=template_file)
    assert cfg2.sampling_interval == 10


def test_paths_and_permissions(tmp_path: Path) -> None:
    """Verifica la creación segura de carpetas y permisos."""
    test_dir = tmp_path / "secure_dir"
    res_dir = ensure_directory(test_dir)
    assert res_dir.exists()

    test_file = test_dir / "test.txt"
    test_file.write_text("ok", encoding="utf-8")
    assert apply_secure_permissions(test_file, is_directory=False) is True


def test_paths_error_handling(tmp_path: Path, monkeypatch) -> None:
    """Verifica que paths.py maneje errores de permisos y disco sin cierres abruptos (SO-10)."""
    from src.common.paths import get_socket_path

    # 1. Archivo inexistente en apply_secure_permissions
    non_existent = tmp_path / "inexistente.txt"
    assert apply_secure_permissions(non_existent) is False or sys.platform == "win32"

    # 2. Simulación de error de permisos en apply_secure_permissions bajo POSIX
    with monkeypatch.context() as m:
        m.setattr("src.common.paths._is_posix", lambda: True)
        m.setattr("os.chmod", lambda p, m: (_ for _ in ()).throw(PermissionError("Acceso denegado")))
        assert apply_secure_permissions(tmp_path, is_directory=True) is False

    # 3. Simulación de fallo en directorio principal con recuperación en fallback
    def mock_mkdir_fail(self, *args, **kwargs):
        raise PermissionError("Permiso denegado al crear directorio")

    with monkeypatch.context() as m:
        m.setattr(Path, "mkdir", mock_mkdir_fail)
        # ensure_directory no debe abortar, debe retornar un Path
        res = ensure_directory(tmp_path / "uncreatable")
        assert isinstance(res, Path)

    # 4. Prueba de get_socket_path con y sin XDG_RUNTIME_DIR
    runtime_mock = tmp_path / "runtime"
    runtime_mock.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_mock))
    sock = get_socket_path()
    assert sock.parent == runtime_mock

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    sock_default = get_socket_path()
    assert sock_default.name == "collector.sock"


def test_config_manager_filesystem_resilience(tmp_path: Path, monkeypatch) -> None:
    """Verifica que ConfigManager sea resiliente a archivos corruptos, disco lleno y permisos (SO-10)."""
    # 1. Archivo corrupto (JSON malformado): debe restaurar plantilla sin abortar
    corrupt_file = tmp_path / "corrupt_config.json"
    corrupt_file.write_text("{ esto no es un json valido", encoding="utf-8")

    cfg_corrupt = ConfigManager(config_path=corrupt_file)
    assert cfg_corrupt.sampling_interval >= 1
    assert "sampling" in cfg_corrupt.get_all()

    # 2. Plantilla y archivo inexistente: usa fallback en memoria
    non_existent_cfg = tmp_path / "sub" / "inexistente.json"
    non_existent_tpl = tmp_path / "no_tpl.json"
    cfg_memory = ConfigManager(config_path=non_existent_cfg, default_template_path=non_existent_tpl)
    assert cfg_memory.sampling_interval >= 1

    # 3. Simulación de error al guardar (e.g. disco lleno / OSError)
    cfg_save_fail = ConfigManager(config_path=tmp_path / "valid.json")
    with monkeypatch.context() as m:
        def mock_open_fail(*args, **kwargs):
            raise OSError("No space left on device (disco lleno)")
        m.setattr("builtins.open", mock_open_fail)
        success = cfg_save_fail.save()
        assert success is False
