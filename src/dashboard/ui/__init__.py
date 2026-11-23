"""Componentes visuales y pestañas de la interfaz gráfica de usuario."""

from src.dashboard.ui.alerts_tab import AlertsTab
from src.dashboard.ui.config_tab import ConfigTab
from src.dashboard.ui.history_tab import HistoryTab
from src.dashboard.ui.main_window import MainWindow
from src.dashboard.ui.monitor_tab import MonitorTab
from src.dashboard.ui.realtime_tab import RealtimeTab

__all__ = [
    "MainWindow",
    "RealtimeTab",
    "HistoryTab",
    "AlertsTab",
    "ConfigTab",
    "MonitorTab",
]
