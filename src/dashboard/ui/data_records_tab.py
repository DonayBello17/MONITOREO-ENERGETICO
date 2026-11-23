"""Pestaña de Registro de Datos para visualización directa de lecturas en SQLite.

Permite consultar, filtrar por circuito, paginar y visualizar las lecturas de telemetría
almacenadas en la base de datos SQLite en tiempo real, así como disparar el poblador
realista en segundo plano sin bloquear la interfaz.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager

logger = logging.getLogger(__name__)


class SeedWorker(QThread):
    """Hilo trabajador para poblar la base de datos en segundo plano sin congelar la UI."""

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        db_manager: DatabaseManager,
        days: int = 15,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.db_manager = db_manager
        self.days = days

    def run(self) -> None:
        try:
            from scripts.seed_realistic_data import seed_data

            result = seed_data(
                db_manager=self.db_manager,
                days=self.days,
                interval_minutes=15,
                clear=False,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.error("Error al poblar base de datos en segundo plano: %s", exc)
            self.failed.emit(str(exc))


class DataRecordsTab(QWidget):
    """Pestaña de Registro de Datos del Dashboard."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        config_manager: Optional[ConfigManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db_manager or DatabaseManager()
        self.cfg = config_manager or ConfigManager()

        self.current_page = 1
        self.page_size = 50
        self.total_records = 0
        self.total_pages = 1
        self._seed_worker: Optional[SeedWorker] = None

        self._init_ui()
        self.reload_data()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Barra superior de Controles
        control_frame = QFrame()
        control_frame.setProperty("class", "card")
        control_layout = QHBoxLayout(control_frame)
        control_layout.setContentsMargins(10, 8, 10, 8)
        control_layout.setSpacing(12)

        # Selector de Circuito
        lbl_circuit = QLabel("<b>Circuito:</b>")
        self.combo_circuit = QComboBox()
        self.combo_circuit.setMinimumWidth(180)
        self.combo_circuit.addItem("Todos los Circuitos", None)
        self.combo_circuit.addItem("Nevera (circ_01)", "circ_01")
        self.combo_circuit.addItem("Iluminación (circ_02)", "circ_02")
        self.combo_circuit.addItem("Aire Acondicionado (circ_03)", "circ_03")
        self.combo_circuit.addItem("Lavadora (circ_04)", "circ_04")
        self.combo_circuit.addItem("Toma General (circ_05)", "circ_05")
        self.combo_circuit.currentIndexChanged.connect(self._on_filter_changed)

        control_layout.addWidget(lbl_circuit)
        control_layout.addWidget(self.combo_circuit)

        # Selector de Cantidad por Página
        lbl_page_size = QLabel("<b>Mostrar:</b>")
        self.combo_page_size = QComboBox()
        self.combo_page_size.addItem("50 por pág.", 50)
        self.combo_page_size.addItem("100 por pág.", 100)
        self.combo_page_size.addItem("500 por pág.", 500)
        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)

        control_layout.addWidget(lbl_page_size)
        control_layout.addWidget(self.combo_page_size)

        # Botones de Paginación
        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.setProperty("class", "secondary")
        self.btn_prev.setFixedWidth(90)
        self.btn_prev.clicked.connect(self._prev_page)

        self.lbl_page_info = QLabel("Pág. 1 de 1")
        self.lbl_page_info.setStyleSheet("font-weight: bold; color: #38bdf8;")

        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.setProperty("class", "secondary")
        self.btn_next.setFixedWidth(90)
        self.btn_next.clicked.connect(self._next_page)

        control_layout.addWidget(self.btn_prev)
        control_layout.addWidget(self.lbl_page_info)
        control_layout.addWidget(self.btn_next)

        # Total de registros en SQLite
        self.lbl_total_records = QLabel("Total: 0 lecturas")
        self.lbl_total_records.setStyleSheet("color: #94a3b8; font-weight: bold; margin-left: 10px;")
        control_layout.addWidget(self.lbl_total_records)

        control_layout.addStretch()

        # Botón Actualizar
        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.setProperty("class", "secondary")
        self.btn_refresh.clicked.connect(self.reload_data)
        control_layout.addWidget(self.btn_refresh)

        # Botón Poblar BD (15 días)
        self.btn_seed = QPushButton("⚡ Poblar BD (15 días)")
        self.btn_seed.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold;")
        self.btn_seed.setToolTip("Genera consumos aleatorios realistas de 15 días para los 5 circuitos en SQLite")
        self.btn_seed.clicked.connect(self._start_seed_data)
        control_layout.addWidget(self.btn_seed)

        layout.addWidget(control_frame)

        # 2. Tabla de Registros
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "Fecha y Hora",
            "Circuito",
            "Voltaje (V)",
            "Corriente (A)",
            "Potencia (W)",
            "Energía (kWh)",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

    def _get_selected_circuit_id(self) -> Optional[str]:
        return self.combo_circuit.currentData()

    def _on_filter_changed(self) -> None:
        self.current_page = 1
        self.reload_data()

    def _on_page_size_changed(self) -> None:
        self.page_size = int(self.combo_page_size.currentData() or 50)
        self.current_page = 1
        self.reload_data()

    def _prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self.reload_data()

    def _next_page(self) -> None:
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.reload_data()

    def reload_data(self) -> None:
        """Consulta SQLite y recarga la tabla respetando los filtros y paginación activa."""
        circuit_id = self._get_selected_circuit_id()

        # Obtener total de registros
        self.total_records = self.db.get_total_readings_count(circuit_id=circuit_id)
        self.total_pages = max(1, (self.total_records + self.page_size - 1) // self.page_size)

        if self.current_page > self.total_pages:
            self.current_page = self.total_pages

        # Actualizar etiquetas de estado de paginación
        self.lbl_page_info.setText(f"Pág. {self.current_page} de {self.total_pages}")
        self.lbl_total_records.setText(f"Total: {self.total_records:,} lecturas")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < self.total_pages)

        # Consultar página desde SQLite
        offset = (self.current_page - 1) * self.page_size
        rows = self.db.get_readings_paginated(
            circuit_id=circuit_id,
            limit=self.page_size,
            offset=offset,
            order_desc=True,
        )

        circuit_names = {
            "circ_01": "Nevera",
            "circ_02": "Iluminación",
            "circ_03": "Aire Acondicionado",
            "circ_04": "Lavadora",
            "circ_05": "Toma General",
        }

        self.table.setRowCount(len(rows))
        for row_idx, r in enumerate(rows):
            dt_str = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            c_name = circuit_names.get(r["circuit_id"], r["circuit_id"])
            c_display = f"{c_name} ({r['circuit_id']})"

            item_id = QTableWidgetItem(str(r["id"]))
            item_id.setTextAlignment(Qt.AlignCenter)

            item_dt = QTableWidgetItem(dt_str)
            item_dt.setTextAlignment(Qt.AlignCenter)

            item_circ = QTableWidgetItem(c_display)

            item_v = QTableWidgetItem(f"{r['voltage']:.1f}")
            item_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            item_i = QTableWidgetItem(f"{r['current']:.3f}")
            item_i.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            item_p = QTableWidgetItem(f"{r['power_w']:.1f}")
            item_p.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            item_e = QTableWidgetItem(f"{r['energy_kwh']:.6f}")
            item_e.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            # Destacar potencia visualmente
            if r["power_w"] > 1000.0:
                item_p.setForeground(Qt.yellow)
            elif r["power_w"] > 2000.0:
                item_p.setForeground(Qt.red)

            self.table.setItem(row_idx, 0, item_id)
            self.table.setItem(row_idx, 1, item_dt)
            self.table.setItem(row_idx, 2, item_circ)
            self.table.setItem(row_idx, 3, item_v)
            self.table.setItem(row_idx, 4, item_i)
            self.table.setItem(row_idx, 5, item_p)
            self.table.setItem(row_idx, 6, item_e)

    def _start_seed_data(self) -> None:
        """Inicia el proceso de poblado de base de datos en un hilo en segundo plano."""
        if self._seed_worker and self._seed_worker.isRunning():
            return

        self.btn_seed.setEnabled(False)
        self.btn_seed.setText("⏳ Generando 15 días...")

        self._seed_worker = SeedWorker(db_manager=self.db, days=15, parent=self)
        self._seed_worker.finished.connect(self._on_seed_finished)
        self._seed_worker.failed.connect(self._on_seed_failed)
        self._seed_worker.start()

    def _on_seed_finished(self, result: Dict[str, Any]) -> None:
        self.btn_seed.setEnabled(True)
        self.btn_seed.setText("⚡ Poblar BD (15 días)")
        self.current_page = 1
        self.reload_data()

        inserted = result.get("total_inserted", 0)
        daily_kwh = result.get("daily_averages_kwh", {})
        summary_lines = [f"Se insertaron {inserted:,} lecturas históricas (15 días a 15 min).\n", "Consumos promedio diarios:"]
        names = {
            "circ_01": "Nevera",
            "circ_02": "Iluminación",
            "circ_03": "Aire Acondicionado",
            "circ_04": "Lavadora",
            "circ_05": "Toma General",
        }
        for cid, kwh in daily_kwh.items():
            cname = names.get(cid, cid)
            summary_lines.append(f"  • {cname}: {kwh:.2f} kWh/día")

        QMessageBox.information(
            self,
            "Base de Datos Poblada con Éxito",
            "\n".join(summary_lines),
        )

    def _on_seed_failed(self, error_msg: str) -> None:
        self.btn_seed.setEnabled(True)
        self.btn_seed.setText("⚡ Poblar BD (15 días)")
        QMessageBox.critical(
            self,
            "Error al Poblar Base de Datos",
            f"Ocurrió un error durante la generación de datos:\n{error_msg}",
        )
