"""Pruebas unitarias para el generador realista de consumo (seeder) y la pestaña de Registro de Datos."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from scripts.seed_realistic_data import seed_data
from src.common.database import DatabaseManager
from src.common.profiles import CIRCUIT_PROFILES
from src.dashboard.ui.data_records_tab import DataRecordsTab


@pytest.fixture(scope="session")
def qapp():
    """Instancia de QApplication en modo offscreen para pruebas gráficas."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_seed_realistic_daily_ranges(tmp_path: Path):
    """Verifica que el generador produzca consumos coherentes con los rangos diarios en kWh requeridos."""
    db_file = tmp_path / "test_seeder.db"
    db = DatabaseManager(db_path=db_file)

    days = 15
    interval = 15
    result = seed_data(
        db_manager=db,
        days=days,
        interval_minutes=interval,
        clear=True,
        rng_seed=42,
    )

    expected_steps_per_day = (24 * 60) // interval  # 96
    expected_readings = days * expected_steps_per_day * 5  # 7200
    assert result["total_inserted"] == expected_readings

    daily_averages = result["daily_averages_kwh"]
    assert len(daily_averages) == 5

    # 1. Nevera: 1.2 - 1.8 kWh/día
    nevera_avg = daily_averages["circ_01"]
    assert 1.2 <= nevera_avg <= 1.8, f"Nevera fuera de rango: {nevera_avg} kWh/día"

    # 2. Iluminación: 0.6 - 1.2 kWh/día
    luz_avg = daily_averages["circ_02"]
    assert 0.6 <= luz_avg <= 1.2, f"Iluminación fuera de rango: {luz_avg} kWh/día"

    # 3. Aire Acondicionado: 4.0 - 8.0 kWh/día
    ac_avg = daily_averages["circ_03"]
    assert 4.0 <= ac_avg <= 8.0, f"Aire Acondicionado fuera de rango: {ac_avg} kWh/día"

    # 4. Lavadora: 0.5 - 1.5 kWh/día
    lav_avg = daily_averages["circ_04"]
    assert 0.5 <= lav_avg <= 1.5, f"Lavadora fuera de rango: {lav_avg} kWh/día"

    # 5. Toma General: 1.0 - 2.2 kWh/día
    toma_avg = daily_averages["circ_05"]
    assert 1.0 <= toma_avg <= 2.2, f"Toma General fuera de rango: {toma_avg} kWh/día"

    # Verificar que el total de registros en BD coincida
    total_in_db = db.get_total_readings_count()
    assert total_in_db == expected_readings

    # Verificar consistencia física de las lecturas almacenadas
    sample_rows = db.get_readings_paginated(limit=100)
    for row in sample_rows:
        assert 118.0 <= row["voltage"] <= 123.0
        assert row["current"] >= 0.0
        assert row["power_w"] >= 0.0
        assert row["energy_kwh"] >= 0.0

    db.close()


def test_data_records_tab_pagination_and_filter(qapp, tmp_path: Path):
    """Verifica el funcionamiento de la pestaña de Registro de Datos: paginación y filtros."""
    db_file = tmp_path / "test_tab.db"
    db = DatabaseManager(db_path=db_file)

    # Poblar 2 días de datos
    seed_data(db_manager=db, days=2, interval_minutes=15, clear=True, rng_seed=123)

    tab = DataRecordsTab(db_manager=db)

    # Total de registros: 2 días * 96 pasos * 5 circuitos = 960 registros
    assert tab.total_records == 960
    assert tab.page_size == 50
    assert tab.total_pages == (960 + 49) // 50  # 20 páginas
    assert tab.table.rowCount() == 50

    # Avanzar a página 2
    tab._next_page()
    assert tab.current_page == 2
    assert tab.btn_prev.isEnabled() is True

    # Retroceder a página 1
    tab._prev_page()
    assert tab.current_page == 1
    assert tab.btn_prev.isEnabled() is False

    # Filtrar por Nevera ('circ_01')
    idx_nevera = tab.combo_circuit.findData("circ_01")
    tab.combo_circuit.setCurrentIndex(idx_nevera)
    # 2 días * 96 pasos = 192 registros de Nevera
    assert tab.total_records == 192
    assert tab.current_page == 1

    tab.close()
    db.close()
