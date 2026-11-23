"""Ventana principal del Dashboard de Monitoreo Energético.

Integra las 5 pestañas temáticas, la barra de estado permanente, el selector de
tema claro/oscuro, notificaciones nativas en bandeja de sistema (QSystemTrayIcon)
y la coordinación de eventos del cliente IPC en tiempo real.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Alert
from src.dashboard.ipc_client import IPCClientThread
from src.dashboard.theme import apply_theme
from src.dashboard.ui.alerts_tab import AlertsTab
from src.dashboard.ui.config_tab import ConfigTab
from src.dashboard.ui.data_records_tab import DataRecordsTab
from src.dashboard.ui.history_tab import HistoryTab
from src.dashboard.ui.monitor_tab import MonitorTab
from src.dashboard.ui.realtime_tab import RealtimeTab

logger = logging.getLogger(__name__)


def create_app_icon() -> QIcon:
    """Genera un icono programático de alta resolución para la ventana y bandeja."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Fondo circular azul
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)

    # Rayo de energía amarillo
    painter.setBrush(QColor("#facc15"))
    from PySide6.QtGui import QPolygon
    from PySide6.QtCore import QPoint
    points = [
        QPoint(34, 12),
        QPoint(20, 34),
        QPoint(32, 34),
        QPoint(28, 52),
        QPoint(46, 28),
        QPoint(34, 28),
    ]
    painter.drawPolygon(QPolygon(points))
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    """Ventana principal de la interfaz gráfica de usuario."""

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        db_manager: Optional[DatabaseManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sistema de Monitoreo Energético para Vivienda")
        self.setWindowFlags(Qt.Window)
        self.resize(1180, 780)
        self.setMinimumSize(950, 650)
        self.setAttribute(Qt.WA_QuitOnClose, True)

        # Centrar la ventana en la pantalla principal activa
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = max(0, (screen_geo.width() - 1180) // 2 + screen_geo.x())
            y = max(0, (screen_geo.height() - 780) // 2 + screen_geo.y())
            self.move(x, y)

        # Gestores de núcleo
        self.cfg = config_manager or ConfigManager()
        self.db = db_manager or DatabaseManager()

        self.is_dark_theme = True
        self.app_icon = create_app_icon()
        self.setWindowIcon(self.app_icon)

        # 1. Configuración de Pestañas
        self._init_tabs()

        # 2. Barra de Estado
        self._init_status_bar()

        # 3. Notificaciones e Icono de Bandeja del Sistema
        self._init_system_tray()

        # 4. Hilo Cliente IPC
        self._init_ipc_client()

    def _init_tabs(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # Barra superior con Selector de Tema
        top_bar = QHBoxLayout()
        title_lbl = QLabel("<b>⚡ Monitor Energético Residencial</b>")
        title_lbl.setStyleSheet("font-size: 16px; color: #38bdf8;")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()

        self.btn_theme = QPushButton("☀️ Tema Claro")
        self.btn_theme.setFixedWidth(120)
        self.btn_theme.setProperty("class", "secondary")
        self.btn_theme.clicked.connect(self._toggle_theme)
        top_bar.addWidget(self.btn_theme)
        main_layout.addLayout(top_bar)

        # TabWidget Principal
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)

        circuits = self.cfg.get_circuits()
        max_power = self.cfg.alert_thresholds.get("max_instant_power_w", 5500.0)

        # Pestaña 1: Tiempo Real
        self.realtime_tab = RealtimeTab(circuits=circuits, max_threshold_w=max_power)
        self.tab_widget.addTab(self.realtime_tab, "⏱️ Tiempo Real")

        # Pestaña 2: Histórico y Costos
        self.history_tab = HistoryTab(db_manager=self.db, config_manager=self.cfg)
        self.tab_widget.addTab(self.history_tab, "📊 Histórico y Costos")

        # Pestaña 3: Registro de Datos
        self.data_records_tab = DataRecordsTab(db_manager=self.db, config_manager=self.cfg)
        self.tab_widget.addTab(self.data_records_tab, "📋 Registro de Datos")

        # Pestaña 4: Alertas y Anomalías
        self.alerts_tab = AlertsTab(db_manager=self.db, config_manager=self.cfg)
        self.alerts_tab.alert_triggered.connect(self._on_alert_triggered)
        self.tab_widget.addTab(self.alerts_tab, "🔔 Alertas")

        # Pestaña 5: Configuración
        self.config_tab = ConfigTab(config_manager=self.cfg, db_manager=self.db)
        self.config_tab.circuits_changed.connect(self._on_circuits_changed)
        self.tab_widget.addTab(self.config_tab, "⚙️ Configuración")

        # Pestaña 6: Monitor del Sistema
        self.monitor_tab = MonitorTab()
        self.tab_widget.addTab(self.monitor_tab, "🖥️ Monitor del Sistema")

        main_layout.addWidget(self.tab_widget)

    def _init_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Indicador de estado del recolector
        self.lbl_collector_status = QLabel("● Recolector: Desconectado")
        self.lbl_collector_status.setStyleSheet("color: #f97316; font-weight: bold; margin-left: 8px;")
        self.status_bar.addWidget(self.lbl_collector_status)

        # Última lectura
        self.lbl_last_reading = QLabel("Última lectura: --")
        self.lbl_last_reading.setStyleSheet("margin-left: 16px; color: #cbd5e1;")
        self.status_bar.addWidget(self.lbl_last_reading)

        # Total de lecturas
        self.lbl_total_readings = QLabel("Lecturas en BD: --")
        self.lbl_total_readings.setStyleSheet("margin-left: 16px; color: #cbd5e1;")
        self.status_bar.addWidget(self.lbl_total_readings)

    def _init_system_tray(self) -> None:
        """Configura el icono en la bandeja del sistema para notificaciones de escritorio."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        tray_menu = QMenu()

        action_show = tray_menu.addAction("Mostrar Monitor Energético")
        action_show.triggered.connect(self.present_to_front)

        action_quit = tray_menu.addAction("Salir")
        action_quit.triggered.connect(QApplication.instance().quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def present_to_front(self) -> None:
        """Restaura, desenfoca si está minimizada y trae la ventana al frente."""
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.present_to_front()

    def _init_ipc_client(self) -> None:
        """Inicia el cliente IPC en segundo plano conectado al recolector."""
        host = self.cfg.ipc_host
        port = self.cfg.ipc_port

        self.ipc_client = IPCClientThread(host=host, port=port, reconnect_interval_seconds=2.0)
        self.ipc_client.connection_changed.connect(self._on_connection_changed)
        self.ipc_client.reading_received.connect(self._on_reading_received)
        self.ipc_client.status_received.connect(self._on_status_received)
        self.ipc_client.start()

    def _on_connection_changed(self, connected: bool) -> None:
        if connected:
            self.lbl_collector_status.setText("● Recolector: Activo")
            self.lbl_collector_status.setStyleSheet("color: #22c55e; font-weight: bold; margin-left: 8px;")
        else:
            self.lbl_collector_status.setText("● Recolector: Desconectado / Detenido")
            self.lbl_collector_status.setStyleSheet("color: #ef4444; font-weight: bold; margin-left: 8px;")

    def _on_reading_received(self, reading_dict: dict) -> None:
        # Enviar lectura a pestaña de tiempo real
        self.realtime_tab.handle_new_reading(reading_dict)

        # Evaluar para alertas y anomalías
        self.alerts_tab.evaluate_new_reading(reading_dict)

        # Actualizar barra de estado
        ts = reading_dict.get("timestamp")
        if ts:
            dt_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
            self.lbl_last_reading.setText(f"Última lectura: {dt_str}")

    def _on_status_received(self, status_dict: dict) -> None:
        total = status_dict.get("total_readings")
        if total is not None:
            self.lbl_total_readings.setText(f"Lecturas en BD: {total:,}")

        pid = status_dict.get("pid")
        if pid:
            self.monitor_tab.set_pid_from_ipc(pid)

        source = status_dict.get("source_status", "OK")
        if source == "ERROR":
            self.lbl_collector_status.setText("● Fuente de datos: Error de hardware")
            self.lbl_collector_status.setStyleSheet("color: #f97316; font-weight: bold; margin-left: 8px;")
        elif self.ipc_client.is_connected:
            self.lbl_collector_status.setText("● Recolector: Activo")
            self.lbl_collector_status.setStyleSheet("color: #22c55e; font-weight: bold; margin-left: 8px;")

    def _on_alert_triggered(self, alert: Alert) -> None:
        """Lanza notificación nativa de escritorio."""
        if self.tray_icon and self.tray_icon.isVisible():
            title = f"⚠️ Alerta: {alert.alert_type}"
            msg = alert.message
            icon_type = (
                QSystemTrayIcon.Critical
                if alert.severity == "CRITICAL"
                else QSystemTrayIcon.Warning
            )
            self.tray_icon.showMessage(title, msg, icon_type, 5000)

    def _on_circuits_changed(self, new_circuits: list) -> None:
        self.realtime_tab.update_circuits(new_circuits)

    def _toggle_theme(self) -> None:
        """Alterna entre Tema Oscuro y Tema Claro."""
        app = QApplication.instance()
        if not app:
            return

        self.is_dark_theme = not self.is_dark_theme
        apply_theme(app, is_dark=self.is_dark_theme)

        if self.is_dark_theme:
            self.btn_theme.setText("☀️ Tema Claro")
        else:
            self.btn_theme.setText("🌙 Tema Oscuro")

    def closeEvent(self, event) -> None:
        """Detiene el cliente IPC limpiamente antes de cerrar la ventana."""
        if hasattr(self, "ipc_client"):
            self.ipc_client.stop()
        event.accept()
