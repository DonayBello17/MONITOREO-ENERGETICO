"""Módulo de exportación e importación de datos en formatos CSV, JSON e imágenes PNG.

Permite:
- Exportar lecturas crudas y agregados temporales a CSV.
- Capturar y guardar pantallas del dashboard en formato PNG (QWidget.grab).
- Importar lecturas masivas desde CSV y JSON validando con ReadingValidator,
  persistiéndolas en SQLite y recalculando agregados estadísticos.
- Ejecución asíncrona mediante hilos de trabajo QThread para evitar congelamiento de la UI.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import QWidget
except ImportError:
    class QThread:  # type: ignore
        pass

    def Signal(*args, **kwargs):  # type: ignore
        return None

    class QWidget:  # type: ignore
        pass

from src.collector.validator import ReadingValidator
from src.common.database import DatabaseManager
from src.common.models import AggregateReading, Reading

logger = logging.getLogger(__name__)


def export_readings_to_csv_spanish(
    readings: List[Any],
    circuits_map: Dict[str, str],
    file_path: Union[Path, str],
) -> int:
    """Exporta lecturas a un archivo CSV profesional optimizado para Excel en español.

    Características:
    - Codificación UTF-8 con BOM (utf-8-sig) para visualización correcta de tildes (ej. Iluminación).
    - Delimitador punto y coma (;) estándar de Excel en español/Latinoamérica.
    - Encabezados claros en español: ID;Fecha y Hora;ID Circuito;Circuito;Voltaje (V);Corriente (A);Potencia (W);Energía (kWh).
    - Formato numérico estandarizado (Voltaje y Potencia 2 decimales, Corriente 3, Energía 6) y fecha legible.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "ID",
        "Fecha y Hora",
        "ID Circuito",
        "Circuito",
        "Voltaje (V)",
        "Corriente (A)",
        "Potencia (W)",
        "Energía (kWh)",
    ]

    count = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)

        for idx, r in enumerate(readings, start=1):
            if isinstance(r, dict):
                r_id = r.get("id", idx)
                ts = float(r.get("timestamp", 0.0))
                cid = str(r.get("circuit_id", ""))
                v = float(r.get("voltage", 0.0))
                curr = float(r.get("current", 0.0))
                p = float(r.get("power_w", 0.0))
                e = float(r.get("energy_kwh", 0.0))
            else:
                r_id = getattr(r, "id", None) or idx
                ts = float(getattr(r, "timestamp", 0.0))
                cid = str(getattr(r, "circuit_id", ""))
                v = float(getattr(r, "voltage", 0.0))
                curr = float(getattr(r, "current", 0.0))
                p = float(getattr(r, "power_w", 0.0))
                e = float(getattr(r, "energy_kwh", 0.0))

            dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            cname = circuits_map.get(cid, cid)
            writer.writerow([
                r_id,
                dt_str,
                cid,
                cname,
                f"{v:.2f}",
                f"{curr:.3f}",
                f"{p:.2f}",
                f"{e:.6f}",
            ])
            count += 1

    logger.info("Exportadas %d lecturas a CSV profesional (español): %s", count, path)
    return count


def export_readings_to_csv(
    readings: List[Any],
    circuits_map: Dict[str, str],
    file_path: Union[Path, str],
    format_spanish: bool = False,
) -> int:
    """Exporta una lista de lecturas crudas a un archivo CSV.

    Args:
        readings: Lista de instancias Reading o diccionarios.
        circuits_map: Mapeo de circuit_id a nombre descriptivo del circuito.
        file_path: Ruta de destino del archivo CSV.
        format_spanish: Si es True, genera formato profesional para Excel en español (; y utf-8-sig).

    Returns:
        int: Cantidad de registros exportados.
    """
    if format_spanish:
        return export_readings_to_csv_spanish(readings, circuits_map, file_path)

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "timestamp",
        "datetime_utc",
        "circuit_id",
        "circuit_name",
        "voltage",
        "current",
        "power_w",
        "energy_kwh",
    ]

    count = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for r in readings:
            if isinstance(r, dict):
                ts = float(r.get("timestamp", 0.0))
                cid = str(r.get("circuit_id", ""))
                v = float(r.get("voltage", 0.0))
                curr = float(r.get("current", 0.0))
                p = float(r.get("power_w", 0.0))
                e = float(r.get("energy_kwh", 0.0))
            else:
                ts = float(r.timestamp)
                cid = str(r.circuit_id)
                v = float(r.voltage)
                curr = float(r.current)
                p = float(r.power_w)
                e = float(r.energy_kwh)

            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            cname = circuits_map.get(cid, cid)
            writer.writerow([
                f"{ts:.3f}",
                dt_str,
                cid,
                cname,
                f"{v:.2f}",
                f"{curr:.3f}",
                f"{p:.2f}",
                f"{e:.6f}",
            ])
            count += 1

    logger.info("Exportadas %d lecturas a CSV: %s", count, path)
    return count


def export_aggregates_to_csv(
    aggregates: List[AggregateReading],
    circuits_map: Dict[str, str],
    file_path: Union[Path, str],
) -> int:
    """Exporta una lista de agregados estadísticos a un archivo CSV."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "period_start",
        "datetime_utc",
        "circuit_id",
        "circuit_name",
        "avg_power_w",
        "min_power_w",
        "max_power_w",
        "total_energy_kwh",
        "reading_count",
    ]

    count = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for agg in aggregates:
            dt_str = datetime.fromtimestamp(agg.period_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            cname = circuits_map.get(agg.circuit_id, agg.circuit_id)
            writer.writerow([
                f"{agg.period_start:.1f}",
                dt_str,
                agg.circuit_id,
                cname,
                f"{agg.avg_power_w:.2f}",
                f"{agg.min_power_w:.2f}",
                f"{agg.max_power_w:.2f}",
                f"{agg.total_energy_kwh:.6f}",
                agg.reading_count,
            ])
            count += 1

    return count


def save_screenshot(widget: QWidget, file_path: Union[Path, str]) -> bool:
    """Captura el widget actual y lo guarda en formato PNG.

    Args:
        widget: Componente Qt a capturar.
        file_path: Ruta de destino (extensión .png).

    Returns:
        bool: True si la imagen se guardó correctamente.
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    success = pixmap.save(str(path), "PNG")
    if success:
        logger.info("Captura de pantalla guardada en: %s", path)
    else:
        logger.error("No se pudo guardar la captura de pantalla en: %s", path)
    return success


def import_readings_from_csv(
    file_path: Union[Path, str],
    db: DatabaseManager,
    validator: Optional[ReadingValidator] = None,
    batch_size: int = 5000,
) -> Tuple[int, int]:
    """Importa lecturas desde un archivo CSV con validación previa de integridad física.

    Soporta:
    - Codificaciones UTF-8 y UTF-8 con BOM (utf-8-sig).
    - Detección automática de delimitador (; o ,).
    - Encabezados estándar en inglés o profesionales en español.
    - Números con coma decimal o punto decimal.

    Args:
        file_path: Ruta al archivo CSV.
        db: Gestor de base de datos SQLite.
        validator: Instancia opcional de ReadingValidator. Si es None, crea una nueva.
        batch_size: Tamaño de lote para inserción atómica.

    Returns:
        Tuple[int, int]: (lecturas_válidas_insertadas, lecturas_descartadas)
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo CSV no encontrado: {path}")

    val = validator or ReadingValidator()
    valid_batch: List[Reading] = []
    total_valid = 0
    total_invalid = 0
    min_ts: Optional[float] = None
    max_ts: Optional[float] = None

    with open(path, "r", encoding="utf-8-sig") as f:
        # Detectar delimitador inspeccionando la primera línea
        first_line = f.readline()
        f.seek(0)
        delimiter = ";" if ";" in first_line else ","

        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            try:
                # 1. Identificar ID de circuito
                circuit_id = (
                    row.get("circuit_id")
                    or row.get("ID Circuito")
                    or row.get("circuito_id")
                    or row.get("circuit")
                )
                if not circuit_id:
                    total_invalid += 1
                    continue
                circuit_id = str(circuit_id).strip()

                # 2. Identificar voltaje
                v_raw = row.get("voltage") or row.get("Voltaje (V)") or row.get("Voltaje")
                if v_raw is None:
                    total_invalid += 1
                    continue
                voltage = float(str(v_raw).replace(",", ".").strip())

                # 3. Identificar corriente
                c_raw = row.get("current") or row.get("Corriente (A)") or row.get("Corriente")
                if c_raw is None:
                    total_invalid += 1
                    continue
                current = float(str(c_raw).replace(",", ".").strip())

                # 4. Identificar potencia
                p_raw = row.get("power_w") or row.get("Potencia (W)") or row.get("Potencia")
                if p_raw is None:
                    total_invalid += 1
                    continue
                power_w = float(str(p_raw).replace(",", ".").strip())

                # 5. Identificar energía
                e_raw = (
                    row.get("energy_kwh")
                    or row.get("Energía (kWh)")
                    or row.get("Energia (kWh)")
                    or row.get("Energía")
                    or 0.0
                )
                energy_kwh = float(str(e_raw).replace(",", ".").strip())

                # 6. Identificar marca de tiempo
                ts_raw = row.get("timestamp")
                if ts_raw is not None and str(ts_raw).strip() != "":
                    timestamp = float(str(ts_raw).strip())
                else:
                    dt_raw = (
                        row.get("Fecha y Hora")
                        or row.get("datetime_utc")
                        or row.get("datetime")
                        or row.get("Fecha")
                    )
                    if not dt_raw:
                        total_invalid += 1
                        continue
                    dt_clean = str(dt_raw).strip()
                    try:
                        timestamp = datetime.strptime(dt_clean, "%Y-%m-%d %H:%M:%S").timestamp()
                    except ValueError:
                        timestamp = datetime.fromisoformat(dt_clean).timestamp()

                reading = Reading(
                    timestamp=timestamp,
                    circuit_id=circuit_id,
                    voltage=voltage,
                    current=current,
                    power_w=power_w,
                    energy_kwh=energy_kwh,
                )

                if val.validate(reading):
                    valid_batch.append(reading)
                    min_ts = reading.timestamp if min_ts is None else min(min_ts, reading.timestamp)
                    max_ts = reading.timestamp if max_ts is None else max(max_ts, reading.timestamp)

                    if len(valid_batch) >= batch_size:
                        db.insert_readings_batch(valid_batch)
                        total_valid += len(valid_batch)
                        valid_batch.clear()
                else:
                    total_invalid += 1
            except Exception as exc:
                logger.warning("Fila CSV descartada por formato inválido (%s): %s", row, exc)
                total_invalid += 1

    if valid_batch:
        db.insert_readings_batch(valid_batch)
        total_valid += len(valid_batch)
        valid_batch.clear()

    # Recalcular agregados para el rango temporal importado
    if total_valid > 0 and min_ts is not None and max_ts is not None:
        db.calculate_hourly_aggregates(min_ts, max_ts + 3600.0)
        db.calculate_daily_aggregates(min_ts, max_ts + 86400.0)
        db.calculate_monthly_aggregates(min_ts, max_ts + 86400.0 * 30)

    logger.info("Importación CSV finalizada: %d válidas, %d descartadas", total_valid, total_invalid)
    return total_valid, total_invalid


def import_readings_from_json(
    file_path: Union[Path, str],
    db: DatabaseManager,
    validator: Optional[ReadingValidator] = None,
    batch_size: int = 5000,
) -> Tuple[int, int]:
    """Importa lecturas desde un archivo JSON (lista de diccionarios de lecturas)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Archivo JSON no encontrado: {path}")

    val = validator or ReadingValidator()
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        raise ValueError("El archivo JSON debe contener un arreglo de lecturas.")

    valid_batch: List[Reading] = []
    total_valid = 0
    total_invalid = 0
    min_ts: Optional[float] = None
    max_ts: Optional[float] = None

    for item in items:
        try:
            reading = Reading.from_dict(item)
            if val.validate(reading):
                valid_batch.append(reading)
                min_ts = reading.timestamp if min_ts is None else min(min_ts, reading.timestamp)
                max_ts = reading.timestamp if max_ts is None else max(max_ts, reading.timestamp)

                if len(valid_batch) >= batch_size:
                    db.insert_readings_batch(valid_batch)
                    total_valid += len(valid_batch)
                    valid_batch.clear()
            else:
                total_invalid += 1
        except Exception as exc:
            logger.warning("Elemento JSON descartado por formato inválido (%s): %s", item, exc)
            total_invalid += 1

    if valid_batch:
        db.insert_readings_batch(valid_batch)
        total_valid += len(valid_batch)
        valid_batch.clear()

    # Recalcular agregados
    if total_valid > 0 and min_ts is not None and max_ts is not None:
        db.calculate_hourly_aggregates(min_ts, max_ts + 3600.0)
        db.calculate_daily_aggregates(min_ts, max_ts + 86400.0)
        db.calculate_monthly_aggregates(min_ts, max_ts + 86400.0 * 30)

    logger.info("Importación JSON finalizada: %d válidas, %d descartadas", total_valid, total_invalid)
    return total_valid, total_invalid


# ==========================================================
# TRABAJADORES ASÍNCRONOS (QThread) PARA LA INTERFAZ
# ==========================================================


class ExportCsvWorker(QThread):
    """Hilo de trabajo para exportar lecturas a CSV sin congelar la UI."""

    finished = Signal(bool, str, int)  # success, message, count

    def __init__(
        self,
        db: DatabaseManager,
        circuits_map: Dict[str, str],
        start_ts: float,
        end_ts: float,
        file_path: str,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.circuits_map = circuits_map
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.file_path = file_path

    def run(self) -> None:
        try:
            readings = self.db.get_readings(start_time=self.start_ts, end_time=self.end_ts)
            count = export_readings_to_csv(readings, self.circuits_map, self.file_path)
            self.finished.emit(True, f"Se exportaron exitosamente {count} registros a CSV.", count)
        except Exception as exc:
            logger.error("Error al exportar lecturas a CSV: %s", exc)
            self.finished.emit(False, f"Error durante la exportación: {exc}", 0)


class ImportDataWorker(QThread):
    """Hilo de trabajo para importar archivos CSV o JSON de forma asíncrona."""

    finished = Signal(bool, str, int, int)  # success, message, valid_count, invalid_count

    def __init__(
        self,
        db: DatabaseManager,
        file_path: str,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.file_path = file_path

    def run(self) -> None:
        path = Path(self.file_path)
        try:
            suffix = path.suffix.lower()
            if suffix == ".csv":
                valid, invalid = import_readings_from_csv(path, self.db)
            elif suffix == ".json":
                valid, invalid = import_readings_from_json(path, self.db)
            else:
                self.finished.emit(False, f"Formato no soportado: '{suffix}'. Use .csv o .json.", 0, 0)
                return

            msg = f"Importación completada: {valid:,} lecturas válidas insertadas, {invalid:,} descartadas."
            self.finished.emit(True, msg, valid, invalid)
        except Exception as exc:
            logger.error("Error al importar datos desde %s: %s", path, exc)
            self.finished.emit(False, f"Error en la importación: {exc}", 0, 0)
