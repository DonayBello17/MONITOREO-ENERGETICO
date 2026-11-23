"""Pruebas unitarias para el Dashboard y componentes de PySide6."""

import os
import sys
import time
import pytest
from PySide6.QtWidgets import QApplication

from src.dashboard.theme import apply_theme
from src.dashboard.ui.main_window import MainWindow
from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager


@pytest.fixture(scope="session")
def qapp():
    """Garantiza la existencia de una instancia única de QApplication en modo offscreen."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_initialization(qapp, tmp_path):
    """Verifica que la ventana principal cargue todas sus pestañas y componentes sin errores."""
    db_file = tmp_path / "test_gui.db"
    db = DatabaseManager(db_path=db_file)
    cfg_file = tmp_path / "test_gui_cfg.json"
    cfg = ConfigManager(config_path=cfg_file)

    apply_theme(qapp, is_dark=True)
    window = MainWindow(config_manager=cfg, db_manager=db)

    # Verificar existencia de las 6 pestañas
    assert window.tab_widget.count() == 6
    assert "Tiempo Real" in window.tab_widget.tabText(0)
    assert "Histórico" in window.tab_widget.tabText(1)
    assert "Registro" in window.tab_widget.tabText(2)
    assert "Alertas" in window.tab_widget.tabText(3)
    assert "Configuración" in window.tab_widget.tabText(4)
    assert "Monitor" in window.tab_widget.tabText(5)

    # Probar cambio de tema
    window._toggle_theme()
    assert window.is_dark_theme is False
    assert "Oscuro" in window.btn_theme.text()

    window._toggle_theme()
    assert window.is_dark_theme is True
    assert "Claro" in window.btn_theme.text()

    # Simular recepción de una lectura
    sample_reading = {
        "timestamp": time.time(),
        "circuit_id": "circ_01",
        "voltage": 120.4,
        "current": 1.2,
        "power_w": 144.5,
        "energy_kwh": 0.05,
    }
    window._on_reading_received(sample_reading)
    assert "144.5 W" in window.realtime_tab.cards["circ_01"].power_label.text()

    # Cerrar ventana
    window.close()
    db.close()
