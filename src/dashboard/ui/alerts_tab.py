"""Pestaña de gestión y monitoreo de alertas y anomalías de consumo.

Permite configurar los umbrales de alerta (potencia instantánea, consumo diario y presupuesto),
visualizar el historial de alertas almacenadas en SQLite, atenderlas y evaluar
anomalías estadísticas (> 2 desviaciones estándar) emitiendo notificaciones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Alert, Reading
from src.dashboard.anomaly_detector import AnomalyDetector


class AlertsTab(QWidget):
    """Pestaña de supervisión de alertas y control de umbrales."""

    # Señal emitida cuando se dispara una nueva alerta o anomalía
    alert_triggered = Signal(object)  # Alert

    def __init__(
        self,
        db_manager: DatabaseManager,
        config_manager: ConfigManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db_manager
        self.cfg = config_manager
        self.anomaly_detector = AnomalyDetector(db_manager)

        self._init_ui()
        self.reload_alerts_history()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # 1. Configuración de Umbrales de Seguridad
        thresholds_frame = QFrame()
        thresholds_frame.setProperty("class", "card")
        th_layout = QVBoxLayout(thresholds_frame)
        th_layout.setContentsMargins(14, 12, 14, 12)

        th_title = QLabel("<b>Configuración de Umbrales de Alerta</b>")
        th_title.setStyleSheet("font-size: 15px; color: #38bdf8;")
        th_layout.addWidget(th_title)

        grid = QGridLayout()
        grid.setSpacing(10)

        # Umbral 1: Potencia instantánea máxima
        grid.addWidget(QLabel("Potencia Máxima Instantánea (W):"), 0, 0)
        self.spin_max_power = QDoubleSpinBox()
        self.spin_max_power.setRange(500.0, 30000.0)
        self.spin_max_power.setSingleStep(100.0)
        self.spin_max_power.setValue(self.cfg.alert_thresholds.get("max_instant_power_w", 5500.0))
        grid.addWidget(self.spin_max_power, 0, 1)

        # Umbral 2: Consumo diario máximo
        grid.addWidget(QLabel("Consumo Diario Máximo (kWh):"), 0, 2)
        self.spin_max_daily = QDoubleSpinBox()
        self.spin_max_daily.setRange(1.0, 200.0)
        self.spin_max_daily.setSingleStep(1.0)
        self.spin_max_daily.setValue(self.cfg.alert_thresholds.get("max_daily_energy_kwh", 35.0))
        grid.addWidget(self.spin_max_daily, 0, 3)

        # Umbral 3: Presupuesto mensual
        grid.addWidget(QLabel("Presupuesto Mensual Estimado ($):"), 1, 0)
        self.spin_budget = QDoubleSpinBox()
        self.spin_budget.setRange(10.0, 5000.0)
        self.spin_budget.setSingleStep(10.0)
        self.spin_budget.setValue(self.cfg.alert_thresholds.get("monthly_budget", 120.0))
        grid.addWidget(self.spin_budget, 1, 1)

        # Botón Guardar Umbrales
        self.btn_save_thresholds = QPushButton("💾 Guardar Umbrales")
        self.btn_save_thresholds.clicked.connect(self._save_thresholds)
        grid.addWidget(self.btn_save_thresholds, 1, 3)

        th_layout.addLayout(grid)
        main_layout.addWidget(thresholds_frame)

        # 2. Historial de Alertas Registradas
        history_header = QHBoxLayout()
        hist_title = QLabel("<b>Historial de Alertas y Anomalías Registradas</b>")
        hist_title.setStyleSheet("font-size: 15px;")
        history_header.addWidget(hist_title)
        history_header.addStretch()

        self.btn_ack_selected = QPushButton("✓ Marcar como Atendida")
        self.btn_ack_selected.clicked.connect(self._acknowledge_selected)
        history_header.addWidget(self.btn_ack_selected)

        self.btn_refresh_alerts = QPushButton("🔄 Actualizar")
        self.btn_refresh_alerts.clicked.connect(self.reload_alerts_history)
        history_header.addWidget(self.btn_refresh_alerts)

        main_layout.addLayout(history_header)

        # Tabla de alertas
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID",
            "Fecha / Hora",
            "Severidad",
            "Tipo",
            "Circuito",
            "Detalle del Evento",
            "Estado",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        main_layout.addWidget(self.table, stretch=1)

    def _save_thresholds(self) -> None:
        """Guarda los umbrales modificados en la configuración."""
        new_th = {
            "max_instant_power_w": float(self.spin_max_power.value()),
            "max_daily_energy_kwh": float(self.spin_max_daily.value()),
            "monthly_budget": float(self.spin_budget.value()),
        }
        self.cfg.update_section("alert_thresholds", new_th)
        self.cfg.save()
        self.btn_save_thresholds.setText("✓ Guardado")
        self.btn_save_thresholds.setEnabled(False)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self._reset_save_btn())

    def _reset_save_btn(self) -> None:
        self.btn_save_thresholds.setText("💾 Guardar Umbrales")
        self.btn_save_thresholds.setEnabled(True)

    def reload_alerts_history(self) -> None:
        """Recarga la lista de alertas desde la base de datos SQLite."""
        alerts = self.db.get_alerts(limit=200, unacknowledged_only=False)
        self.table.setRowCount(len(alerts))

        for row, alert in enumerate(alerts):
            dt = datetime.fromtimestamp(alert.timestamp).strftime("%d/%m/%Y %H:%M:%S")

            # Formato de celda
            id_item = QTableWidgetItem(str(alert.id))
            dt_item = QTableWidgetItem(dt)

            # Severidad estilizada
            sev_item = QTableWidgetItem(alert.severity)
            if alert.severity == "CRITICAL":
                sev_item.setForeground(Qt.red)
            elif alert.severity == "WARNING":
                sev_item.setForeground(Qt.yellow)

            type_item = QTableWidgetItem(alert.alert_type)
            circuit_item = QTableWidgetItem(alert.circuit_id or "General")
            msg_item = QTableWidgetItem(alert.message)

            status_text = "Atendida" if alert.is_acknowledged else "Activa"
            status_item = QTableWidgetItem(status_text)
            if not alert.is_acknowledged:
                status_item.setForeground(Qt.red)
            else:
                status_item.setForeground(Qt.gray)

            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, dt_item)
            self.table.setItem(row, 2, sev_item)
            self.table.setItem(row, 3, type_item)
            self.table.setItem(row, 4, circuit_item)
            self.table.setItem(row, 5, msg_item)
            self.table.setItem(row, 6, status_item)

    def _acknowledge_selected(self) -> None:
        """Marca la alerta seleccionada como atendida."""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return

        id_item = self.table.item(selected_row, 0)
        if not id_item:
            return

        alert_id = int(id_item.text())
        if self.db.acknowledge_alert(alert_id):
            self.reload_alerts_history()

    def evaluate_new_reading(self, reading_dict: dict) -> None:
        """Evalúa lecturas entrantes para detectar umbrales superados o anomalías estadísticas."""
        reading = Reading.from_dict(reading_dict)

        # 1. Comprobación de umbral de potencia instantánea
        max_p = float(self.spin_max_power.value())
        if reading.power_w > max_p:
            alert = Alert(
                timestamp=reading.timestamp,
                circuit_id=reading.circuit_id,
                alert_type="SOBREPOTENCIA",
                severity="CRITICAL",
                message=f"Potencia ({reading.power_w:.1f} W) excedió el límite seguro de {max_p:.1f} W en {reading.circuit_id}",
                value=reading.power_w,
                threshold=max_p,
            )
            try:
                alert.id = self.db.insert_alert(alert)
                self.reload_alerts_history()
                self.alert_triggered.emit(alert)
            except Exception:
                pass
            return

        # 2. Comprobación de anomalía estadística (> 2 desviaciones estándar)
        anomaly_alert = self.anomaly_detector.evaluate_reading(reading)
        if anomaly_alert:
            self.reload_alerts_history()
            self.alert_triggered.emit(anomaly_alert)
