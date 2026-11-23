"""Gestión centralizada de temas visuales (Claro y Oscuro) para la interfaz y gráficos.

Aplica estilos CSS modernos a widgets de PySide6 y configura los colores de fondo,
ejes y cuadrículas en PyQtGraph para garantizar legibilidad óptima y accesibilidad.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

# Paleta de colores para gráficos por circuito
CIRCUIT_COLORS = [
    "#3b82f6",  # Azul (Nevera)
    "#eab308",  # Amarillo (Iluminación)
    "#06b6d4",  # Cian (Aire Acondicionado)
    "#a855f7",  # Púrpura (Lavadora)
    "#10b981",  # Esmeralda (Toma General)
    "#f97316",  # Naranja
    "#ec4899",  # Rosa
    "#84cc16",  # Lima
]

DARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

QWidget {
    color: #f8fafc;
    font-size: 13px;
}

/* Pestañas */
QTabWidget::pane {
    border: 1px solid #334155;
    background-color: #0f172a;
    border-radius: 8px;
    padding: 6px;
}

QTabBar::tab {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 10px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: bold;
}

QTabBar::tab:selected {
    background-color: #3b82f6;
    color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background-color: #334155;
    color: #f8fafc;
}

/* Tarjetas y Marcos */
QFrame.card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 12px;
}

QGroupBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 14px;
    font-weight: bold;
    padding-top: 18px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    color: #38bdf8;
    background-color: transparent;
}

/* Botones */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton.secondary {
    background-color: #334155;
    color: #f8fafc;
}

QPushButton.secondary:hover {
    background-color: #475569;
}

QPushButton.danger {
    background-color: #dc2626;
}

QPushButton.danger:hover {
    background-color: #b91c1c;
}

/* Entradas de texto y selectores */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {
    background-color: #0f172a;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #38bdf8;
}

/* Tablas */
QTableWidget {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #334155;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #0f172a;
    color: #94a3b8;
    padding: 8px;
    font-weight: bold;
    border: 1px solid #334155;
}

/* Barra de estado */
QStatusBar {
    background-color: #1e293b;
    color: #cbd5e1;
    border-top: 1px solid #334155;
}

QProgressBar {
    border: 1px solid #475569;
    border-radius: 6px;
    text-align: center;
    background-color: #0f172a;
    color: #ffffff;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 5px;
}
"""

LIGHT_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

QWidget {
    color: #0f172a;
    font-size: 13px;
}

/* Pestañas */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background-color: #f8fafc;
    border-radius: 8px;
    padding: 6px;
}

QTabBar::tab {
    background-color: #e2e8f0;
    color: #475569;
    padding: 10px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: bold;
}

QTabBar::tab:selected {
    background-color: #2563eb;
    color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background-color: #cbd5e1;
    color: #0f172a;
}

/* Tarjetas y Marcos */
QFrame.card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    margin-top: 14px;
    font-weight: bold;
    padding-top: 18px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    color: #1d4ed8;
    background-color: transparent;
}

/* Botones */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton.secondary {
    background-color: #e2e8f0;
    color: #1e293b;
}

QPushButton.secondary:hover {
    background-color: #cbd5e1;
}

QPushButton.danger {
    background-color: #dc2626;
}

QPushButton.danger:hover {
    background-color: #b91c1c;
}

/* Entradas de texto y selectores */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 10px;
    color: #0f172a;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}

/* Tablas */
QTableWidget {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    gridline-color: #e2e8f0;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #f1f5f9;
    color: #475569;
    padding: 8px;
    font-weight: bold;
    border: 1px solid #cbd5e1;
}

/* Barra de estado */
QStatusBar {
    background-color: #ffffff;
    color: #475569;
    border-top: 1px solid #e2e8f0;
}

QProgressBar {
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    text-align: center;
    background-color: #ffffff;
    color: #0f172a;
    font-weight: bold;
}

QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 5px;
}
"""


def apply_theme(app: QApplication, is_dark: bool = True) -> None:
    """Aplica el tema visual (Claro u Oscuro) a los widgets Qt y a PyQtGraph."""
    if is_dark:
        app.setStyleSheet(DARK_STYLESHEET)
        pg.setConfigOption("background", "#0f172a")
        pg.setConfigOption("foreground", "#f8fafc")
    else:
        app.setStyleSheet(LIGHT_STYLESHEET)
        pg.setConfigOption("background", "#ffffff")
        pg.setConfigOption("foreground", "#0f172a")
