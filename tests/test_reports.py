"""Pruebas unitarias para exportación, importación de datos y generación de reportes PDF."""

import json
import os
import time
from pathlib import Path
import pytest

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Circuit, Reading
from src.dashboard.reports.exporter import (
    export_aggregates_to_csv,
    export_readings_to_csv,
    import_readings_from_csv,
    import_readings_from_json,
    save_screenshot,
)
from src.dashboard.reports.pdf_report import generate_monthly_pdf_report


@pytest.fixture
def report_env(tmp_path):
    """Entorno de prueba con base de datos y configuración limpias."""
    db_file = tmp_path / "test_reports.db"
    db = DatabaseManager(db_path=db_file)

    cfg_file = tmp_path / "test_config.json"
    cfg = ConfigManager(config_path=cfg_file)

    # Circuitos de prueba
    c1 = Circuit(id="circ_01", name="Nevera", location="Cocina", nominal_power_w=300.0)
    c2 = Circuit(id="circ_02", name="Iluminación", location="General", nominal_power_w=200.0)
    db.upsert_circuits([c1, c2])

    yield db, cfg, tmp_path
    db.close()


def test_export_readings_and_aggregates_to_csv(report_env):
    """Verifica la exportación correcta de lecturas y agregados a formato CSV."""
    db, cfg, tmp_path = report_env

    # Insertar lecturas
    ts = 1700000000.0
    readings = [
        Reading(timestamp=ts + i, circuit_id="circ_01", voltage=120.0, current=1.0, power_w=120.0, energy_kwh=0.01 * i)
        for i in range(5)
    ]
    db.insert_readings_batch(readings)
    db.calculate_hourly_aggregates(ts, ts + 3600.0)

    # 1. Exportar lecturas crudas
    csv_file = tmp_path / "export_lecturas.csv"
    count = export_readings_to_csv(readings, {"circ_01": "Nevera"}, csv_file)
    assert count == 5
    assert csv_file.exists()

    with open(csv_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 6  # Encabezado + 5 filas
        assert "timestamp,datetime_utc,circuit_id" in lines[0]
        assert "circ_01,Nevera" in lines[1]

    # 2. Exportar agregados
    aggs = db.get_aggregates("hourly")
    agg_csv = tmp_path / "export_agregados.csv"
    agg_count = export_aggregates_to_csv(aggs, {"circ_01": "Nevera"}, agg_csv)
    assert agg_count >= 1
    assert agg_csv.exists()


def test_import_from_csv_and_json(report_env):
    """Verifica la importación y validación de archivos CSV y JSON hacia la base de datos."""
    db, cfg, tmp_path = report_env

    # 1. Crear archivo CSV de prueba con 2 filas válidas y 1 inválida (voltaje negativo)
    csv_path = tmp_path / "import_test.csv"
    csv_content = """timestamp,circuit_id,voltage,current,power_w,energy_kwh
1700000100.0,circ_01,120.5,1.2,144.6,0.05
1700000102.0,circ_01,120.2,1.1,132.2,0.06
1700000104.0,circ_01,-50.0,1.0,50.0,0.07
"""
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    valid_c, invalid_c = import_readings_from_csv(csv_path, db)
    assert valid_c == 2
    assert invalid_c == 1

    # 2. Crear archivo JSON de prueba
    json_path = tmp_path / "import_test.json"
    json_data = [
        {"timestamp": 1700000200.0, "circuit_id": "circ_02", "voltage": 120.0, "current": 0.5, "power_w": 60.0, "energy_kwh": 0.02},
        {"timestamp": 1700000202.0, "circuit_id": "circ_02", "voltage": 120.0, "current": -2.0, "power_w": 60.0, "energy_kwh": 0.02},  # Inválido
    ]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f)

    valid_j, invalid_j = import_readings_from_json(json_path, db)
    assert valid_j == 1
    assert invalid_j == 1


def test_import_sample_files(report_env):
    """Verifica la importación exitosa de los archivos de ejemplo provistos en samples/."""
    db, cfg, tmp_path = report_env

    # Asegurar que los circuitos del sample existan
    all_circuits = [
        Circuit(id=f"circ_0{i}", name=f"Circuito {i}", location="General", nominal_power_w=1000.0)
        for i in range(1, 6)
    ]
    db.upsert_circuits(all_circuits)

    # 1. Probar samples/lecturas_ejemplo.csv
    csv_sample = Path("samples/lecturas_ejemplo.csv")
    assert csv_sample.exists()
    valid_csv, invalid_csv = import_readings_from_csv(csv_sample, db)
    assert valid_csv > 0
    assert invalid_csv == 0

    # 2. Probar samples/lecturas_ejemplo.json
    json_sample = Path("samples/lecturas_ejemplo.json")
    assert json_sample.exists()
    valid_json, invalid_json = import_readings_from_json(json_sample, db)
    assert valid_json > 0
    assert invalid_json == 0


def test_generate_monthly_pdf_report(report_env):
    """Verifica la generación completa del reporte mensual en PDF con tablas y gráficos embebidos."""
    db, cfg, tmp_path = report_env

    # Población de datos agregados en el mes
    from datetime import datetime
    year = 2026
    month = 11

    # Insertar lecturas para simular el mes
    base_ts = datetime(year, month, 5, 12, 0, 0).timestamp()
    sample_readings = [
        Reading(timestamp=base_ts + i * 3600, circuit_id="circ_01", voltage=120.0, current=1.5, power_w=180.0, energy_kwh=0.5 * (i + 1))
        for i in range(20)
    ]
    db.insert_readings_batch(sample_readings)
    db.calculate_daily_aggregates(base_ts, base_ts + 86400 * 20)

    pdf_out = tmp_path / "reporte_mensual_test.pdf"
    res_path = generate_monthly_pdf_report(
        db=db,
        config=cfg,
        year=year,
        month=month,
        output_path=pdf_out,
    )

    assert Path(res_path).exists()
    assert os.path.getsize(res_path) > 1024  # Al menos 1 KB de PDF generado

    # Verificar encabezado estándar PDF (%PDF-)
    with open(res_path, "rb") as f:
        magic = f.read(5)
        assert magic == b"%PDF-"
