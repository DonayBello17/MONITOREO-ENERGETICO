"""Pestaña de análisis histórico, indicadores clave (KPIs) y desglose de costos.

Permite consultar agregaciones horarias, diarias, semanales y mensuales en un hilo
de trabajo en segundo plano (QThread), graficar consumo histórico y por circuito,
y calcular costos estimados según tarifas fijas, horarias o por escalones.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pyqtgraph as pg
from PySide6.QtCore import QDate, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.dashboard.cost_calculator import (
    calculate_fixed_cost,
    calculate_projected_monthly,
    calculate_time_of_use_cost,
)
from src.dashboard.reports.exporter import (
    ExportCsvWorker,
    ImportDataWorker,
    save_screenshot,
)
from src.dashboard.reports.pdf_report import GeneratePdfWorker
from src.dashboard.theme import CIRCUIT_COLORS


class HistoryDataWorker(QThread):
    """Hilo de trabajo asíncrono para consultar datos analíticos sin congelar la UI."""

    data_ready = Signal(dict)

    def __init__(
        self,
        db: DatabaseManager,
        cfg: ConfigManager,
        grouping: str,
        start_date: QDate,
        end_date: QDate,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.cfg = cfg
        self.grouping = grouping
        self.start_date = start_date
        self.end_date = end_date

    def run(self) -> None:
        """Ejecuta consultas agregadas y cálculos de KPIs y costos."""
        # Convertir fechas a timestamps Unix
        dt_start = datetime(self.start_date.year(), self.start_date.month(), self.start_date.day(), 0, 0, 0)
        dt_end = datetime(self.end_date.year(), self.end_date.month(), self.end_date.day(), 23, 59, 59)
        start_ts = dt_start.timestamp()
        end_ts = dt_end.timestamp()

        # Determinar tabla agregada según agrupación
        period_type_map = {
            "Hora": "hourly",
            "Día": "daily",
            "Semana": "daily",
            "Mes": "monthly",
        }
        table_period = period_type_map.get(self.grouping, "daily")

        # 1. Consulta de agregados del periodo seleccionado
        aggregates = self.db.get_aggregates(
            period_type=table_period,
            start_time=start_ts,
            end_time=end_ts,
        )

        # 2. Totalizar consumo por circuito y línea de tiempo
        total_kwh_selected = 0.0
        circuit_totals: Dict[str, float] = {}
        timeline_buckets: Dict[float, float] = {}
        peak_power_w = 0.0
        peak_timestamp = start_ts

        intervals_for_tou: List[tuple[float, float]] = []

        for agg in aggregates:
            total_kwh_selected += agg.total_energy_kwh
            cid = agg.circuit_id
            circuit_totals[cid] = circuit_totals.get(cid, 0.0) + agg.total_energy_kwh

            p_start = agg.period_start
            timeline_buckets[p_start] = timeline_buckets.get(p_start, 0.0) + agg.total_energy_kwh
            intervals_for_tou.append((p_start, agg.total_energy_kwh))

            if agg.max_power_w > peak_power_w:
                peak_power_w = agg.max_power_w
                peak_timestamp = agg.period_start

        # 3. Consumo de Hoy y del Mes actual
        now = time.time()
        dt_now = datetime.fromtimestamp(now)
        today_start = datetime(dt_now.year, dt_now.month, dt_now.day).timestamp()
        today_aggs = self.db.get_aggregates("hourly", start_time=today_start, end_time=now)
        today_kwh = sum(a.total_energy_kwh for a in today_aggs)

        month_start = datetime(dt_now.year, dt_now.month, 1).timestamp()
        month_aggs = self.db.get_aggregates("daily", start_time=month_start, end_time=now)
        month_kwh = sum(a.total_energy_kwh for a in month_aggs)

        # 4. Proyección a fin de mes
        tariff_data = self.cfg.tariff
        base_rate = float(tariff_data.get("base_rate_per_kwh", 0.15))
        currency = tariff_data.get("currency", "USD")

        proj_kwh, proj_cost = calculate_projected_monthly(
            current_kwh=month_kwh,
            day_of_month=dt_now.day,
            days_in_month=30,
            rate_per_kwh=base_rate,
        )

        # 5. Cálculo de costo del periodo seleccionado
        tou_enabled = tariff_data.get("time_of_use_enabled", False)
        tou_rates = tariff_data.get("time_of_use_rates", [])

        if tou_enabled and tou_rates and intervals_for_tou:
            total_cost = calculate_time_of_use_cost(intervals_for_tou, tou_rates, base_rate)
        else:
            total_cost = calculate_fixed_cost(total_kwh_selected, base_rate)

        # 6. Comparación contra periodo anterior de igual duración
        period_duration = max(86400.0, end_ts - start_ts)
        prev_start_ts = start_ts - period_duration
        prev_end_ts = start_ts - 1.0

        prev_aggs = self.db.get_aggregates(table_period, start_time=prev_start_ts, end_time=prev_end_ts)
        prev_kwh = sum(a.total_energy_kwh for a in prev_aggs)

        if prev_kwh > 0.0:
            diff_pct = ((total_kwh_selected - prev_kwh) / prev_kwh) * 100.0
        else:
            diff_pct = 0.0

        # Preparar datos ordenados para graficación
        sorted_timeline = sorted(timeline_buckets.items(), key=lambda x: x[0])

        result = {
            "total_kwh": total_kwh_selected,
            "total_cost": total_cost,
            "currency": currency,
            "today_kwh": today_kwh,
            "month_kwh": month_kwh,
            "proj_kwh": proj_kwh,
            "proj_cost": proj_cost,
            "peak_power_w": peak_power_w,
            "peak_timestamp": peak_timestamp,
            "diff_pct": diff_pct,
            "timeline": sorted_timeline,
            "circuit_totals": circuit_totals,
        }
        self.data_ready.emit(result)


class HistoryTab(QWidget):
    """Pestaña de estadísticas históricas, KPIs y desglose de costos."""

    def __init__(self, db_manager: DatabaseManager, config_manager: ConfigManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db_manager
        self.cfg = config_manager
        self._worker: Optional[HistoryDataWorker] = None

        self._init_ui()
        self.reload_data()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # 1. Barra de Controles y Filtros
        controls_frame = QFrame()
        controls_frame.setProperty("class", "card")
        ctrl_layout = QHBoxLayout(controls_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(10)

        # Selector de rango de fechas
        ctrl_layout.addWidget(QLabel("<b>Desde:</b>"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addDays(-7))
        ctrl_layout.addWidget(self.start_date_edit)

        ctrl_layout.addWidget(QLabel("<b>Hasta:</b>"))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        ctrl_layout.addWidget(self.end_date_edit)

        # Selector de agrupación temporal
        ctrl_layout.addWidget(QLabel("<b>Agrupar por:</b>"))
        self.grouping_combo = QComboBox()
        self.grouping_combo.addItems(["Hora", "Día", "Semana", "Mes"])
        self.grouping_combo.setCurrentText("Día")
        ctrl_layout.addWidget(self.grouping_combo)

        # Botón de consulta / actualizar
        self.btn_refresh = QPushButton("🔍 Actualizar")
        self.btn_refresh.clicked.connect(self.reload_data)
        ctrl_layout.addWidget(self.btn_refresh)

        # Botones de exportación, captura e importación
        self.btn_export_csv = QPushButton("📊 Exportar CSV")
        self.btn_export_csv.setProperty("class", "secondary")
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        ctrl_layout.addWidget(self.btn_export_csv)

        self.btn_export_pdf = QPushButton("📄 Reporte PDF")
        self.btn_export_pdf.setProperty("class", "secondary")
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        ctrl_layout.addWidget(self.btn_export_pdf)

        self.btn_screenshot = QPushButton("📷 Captura PNG")
        self.btn_screenshot.setProperty("class", "secondary")
        self.btn_screenshot.clicked.connect(self._on_screenshot)
        ctrl_layout.addWidget(self.btn_screenshot)

        self.btn_import = QPushButton("📥 Importar Datos")
        self.btn_import.setProperty("class", "secondary")
        self.btn_import.clicked.connect(self._on_import_data)
        ctrl_layout.addWidget(self.btn_import)

        ctrl_layout.addStretch()

        main_layout.addWidget(controls_frame)

        # 2. Panel de Indicadores Clave (KPIs)
        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(10)

        self.kpi_today = self._create_kpi_card("CONSUMO HOY", "0.0 kWh", "Día en curso")
        self.kpi_month = self._create_kpi_card("CONSUMO MES", "0.0 kWh", "Acumulado mes")
        self.kpi_proj = self._create_kpi_card("PROYECCIÓN MES", "0.0 kWh / $0.0", "Estimado fin de mes")
        self.kpi_peak = self._create_kpi_card("PICO MÁXIMO", "0 W", "Hora del pico: --:--")
        self.kpi_cost = self._create_kpi_card("COSTO PERIODO", "$0.00 USD", "Vs periodo anterior: 0.0%")

        kpi_grid.addWidget(self.kpi_today["frame"], 0, 0)
        kpi_grid.addWidget(self.kpi_month["frame"], 0, 1)
        kpi_grid.addWidget(self.kpi_proj["frame"], 0, 2)
        kpi_grid.addWidget(self.kpi_peak["frame"], 0, 3)
        kpi_grid.addWidget(self.kpi_cost["frame"], 0, 4)

        main_layout.addLayout(kpi_grid)

        # 3. Gráficos Analíticos
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(12)

        # Gráfico de Consumo Histórico (Barras / Líneas)
        self.timeline_plot = pg.PlotWidget(title="<b>Consumo Histórico de Energía (kWh)</b>")
        self.timeline_plot.showGrid(x=True, y=True, alpha=0.3)
        self.timeline_plot.setLabel("left", "Energía", units="kWh")
        self.timeline_plot.setLabel("bottom", "Periodo")
        charts_layout.addWidget(self.timeline_plot, stretch=3)

        # Gráfico de Distribución por Circuito
        self.distribution_plot = pg.PlotWidget(title="<b>Distribución de Consumo por Circuito (kWh)</b>")
        self.distribution_plot.showGrid(x=True, y=True, alpha=0.3)
        self.distribution_plot.setLabel("left", "Energía", units="kWh")
        charts_layout.addWidget(self.distribution_plot, stretch=2)

        main_layout.addLayout(charts_layout, stretch=1)

    def _create_kpi_card(self, title: str, initial_value: str, subtitle: str) -> Dict[str, Any]:
        """Crea una tarjeta estilizada para un indicador KPI."""
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        lbl_val = QLabel(initial_value)
        lbl_val.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
        lbl_sub = QLabel(subtitle)
        lbl_sub.setStyleSheet("color: #64748b; font-size: 11px;")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_sub)

        return {"frame": frame, "value": lbl_val, "subtitle": lbl_sub}

    def reload_data(self) -> None:
        """Lanza la consulta en segundo plano."""
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("Cargando...")

        self._worker = HistoryDataWorker(
            db=self.db,
            cfg=self.cfg,
            grouping=self.grouping_combo.currentText(),
            start_date=self.start_date_edit.date(),
            end_date=self.end_date_edit.date(),
        )
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.start()

    def _on_data_ready(self, data: dict) -> None:
        """Actualiza los widgets de la interfaz con los resultados analíticos."""
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔍 Actualizar")

        # 1. Actualizar KPIs
        self.kpi_today["value"].setText(f"{data['today_kwh']:.2f} kWh")
        self.kpi_month["value"].setText(f"{data['month_kwh']:.2f} kWh")

        currency = data["currency"]
        self.kpi_proj["value"].setText(f"{data['proj_kwh']:.1f} kWh / ${data['proj_cost']:.2f}")

        peak_dt = datetime.fromtimestamp(data["peak_timestamp"])
        self.kpi_peak["value"].setText(f"{data['peak_power_w']:.1f} W")
        self.kpi_peak["subtitle"].setText(f"Hora del pico: {peak_dt.strftime('%d/%m %H:%M')}")

        diff = data["diff_pct"]
        diff_str = f"+{diff:.1f}%" if diff > 0 else f"{diff:.1f}%"
        self.kpi_cost["value"].setText(f"${data['total_cost']:.2f} {currency}")
        self.kpi_cost["subtitle"].setText(f"Vs periodo previo: {diff_str}")

        # 2. Dibujar Gráfico Histórico
        self.timeline_plot.clear()
        timeline = data["timeline"]
        if timeline:
            x_vals = list(range(len(timeline)))
            y_vals = [pt[1] for pt in timeline]

            # Gráfico de barras de consumo
            bar_item = pg.BarGraphItem(x=x_vals, height=y_vals, width=0.6, brush="#38bdf8")
            self.timeline_plot.addItem(bar_item)

            # Eje inferior formateado
            ticks = []
            step = max(1, len(timeline) // 8)
            for idx in range(0, len(timeline), step):
                ts = timeline[idx][0]
                dt = datetime.fromtimestamp(ts)
                fmt = "%H:%M" if self.grouping_combo.currentText() == "Hora" else "%d/%m"
                ticks.append((idx, dt.strftime(fmt)))

            ax = self.timeline_plot.getAxis("bottom")
            ax.setTicks([ticks])

        # 3. Dibujar Gráfico de Distribución por Circuito
        self.distribution_plot.clear()
        circuit_totals = data["circuit_totals"]
        if circuit_totals:
            circuits_dict = {c.id: c.name for c in self.db.get_circuits()}
            names = [circuits_dict.get(cid, cid) for cid in circuit_totals.keys()]
            y_energy = list(circuit_totals.values())
            x_pos = list(range(len(y_energy)))

            bar_dist = pg.BarGraphItem(x=x_pos, height=y_energy, width=0.5, brush="#a855f7")
            self.distribution_plot.addItem(bar_dist)

            ticks_dist = [(i, names[i]) for i in range(len(names))]
            ax_dist = self.distribution_plot.getAxis("bottom")
            ax_dist.setTicks([ticks_dist])

    def _on_export_csv(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Lecturas a CSV", "lecturas_energia.csv", "Archivos CSV (*.csv)"
        )
        if not file_path:
            return

        dt_start = datetime(
            self.start_date_edit.date().year(),
            self.start_date_edit.date().month(),
            self.start_date_edit.date().day(),
            0,
            0,
            0,
        )
        dt_end = datetime(
            self.end_date_edit.date().year(),
            self.end_date_edit.date().month(),
            self.end_date_edit.date().day(),
            23,
            59,
            59,
        )
        circuits_map = {c.id: c.name for c in self.db.get_circuits()}

        self._export_worker = ExportCsvWorker(
            db=self.db,
            circuits_map=circuits_map,
            start_ts=dt_start.timestamp(),
            end_ts=dt_end.timestamp(),
            file_path=file_path,
            parent=self,
        )
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.start()

    def _on_export_finished(self, success: bool, message: str, count: int) -> None:
        if success:
            QMessageBox.information(self, "Exportación Exitosa", message)
        else:
            QMessageBox.critical(self, "Error en Exportación", message)

    def _on_export_pdf(self) -> None:
        target_date = self.end_date_edit.date()
        year = target_date.year()
        month = target_date.month()
        default_name = f"reporte_energia_{year}_{month:02d}.pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar Reporte Mensual PDF", default_name, "Archivos PDF (*.pdf)"
        )
        if not file_path:
            return

        self._pdf_worker = GeneratePdfWorker(
            db=self.db,
            config=self.cfg,
            year=year,
            month=month,
            output_path=file_path,
            parent=self,
        )
        self._pdf_worker.finished.connect(self._on_pdf_finished)
        self._pdf_worker.start()

    def _on_pdf_finished(self, success: bool, message: str) -> None:
        if success:
            QMessageBox.information(self, "Reporte PDF Generado", message)
        else:
            QMessageBox.critical(self, "Error en Reporte PDF", message)

    def _on_screenshot(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Captura de Pantalla", "captura_dashboard.png", "Imágenes PNG (*.png)"
        )
        if not file_path:
            return

        target_widget = self.window() or self
        if save_screenshot(target_widget, file_path):
            QMessageBox.information(self, "Captura Guardada", f"Captura de pantalla guardada con éxito en:\n{file_path}")
        else:
            QMessageBox.critical(self, "Error", "No se pudo guardar la captura de pantalla.")

    def _on_import_data(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar Datos de Lecturas",
            "",
            "Archivos de Datos (*.csv *.json);;Archivos CSV (*.csv);;Archivos JSON (*.json)",
        )
        if not file_path:
            return

        self._import_worker = ImportDataWorker(db=self.db, file_path=file_path, parent=self)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.start()

    def _on_import_finished(self, success: bool, message: str, valid: int, invalid: int) -> None:
        if success:
            QMessageBox.information(self, "Importación Finalizada", message)
            self.reload_data()
        else:
            QMessageBox.critical(self, "Error en Importación", message)

