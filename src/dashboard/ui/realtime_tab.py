"""Pestaña de monitoreo en tiempo real con gráficos en vivo e indicadores de potencia.

Muestra la potencia instantánea total, un gráfico con ventana móvil de bajo consumo
de CPU en PyQtGraph y tarjetas dinámicas para cada uno de los circuitos monitoreados.
"""

from __future__ import annotations

import collections
import time
from typing import Dict, List, Optional

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.common.models import Circuit
from src.dashboard.theme import CIRCUIT_COLORS


class CircuitCard(QFrame):
    """Tarjeta visual individual representativa del estado de un circuito."""

    def __init__(self, circuit: Circuit, color: str = "#3b82f6", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.circuit_id = circuit.id
        self.setObjectName("circuitCard")
        self.setProperty("class", "card")
        self.setStyleSheet(f"""
            QFrame#circuitCard {{
                border-left: 5px solid {color};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Encabezado: Nombre y Ubicación
        header_layout = QHBoxLayout()
        self.name_label = QLabel(f"<b>{circuit.name}</b>")
        self.name_label.setStyleSheet("font-size: 15px;")
        self.location_label = QLabel(f"📍 {circuit.location}")
        self.location_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header_layout.addWidget(self.name_label)
        header_layout.addStretch()
        header_layout.addWidget(self.location_label)
        layout.addLayout(header_layout)

        # Potencia principal destacada
        self.power_label = QLabel("0.0 W")
        self.power_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #38bdf8;")
        layout.addWidget(self.power_label)

        # Detalles secundarios (V, A, kWh)
        details_layout = QHBoxLayout()
        self.voltage_label = QLabel("V: -- V")
        self.voltage_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self.current_label = QLabel("I: -- A")
        self.current_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self.energy_label = QLabel("E: -- kWh")
        self.energy_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")

        details_layout.addWidget(self.voltage_label)
        details_layout.addWidget(self.current_label)
        details_layout.addWidget(self.energy_label)
        layout.addLayout(details_layout)

        # Estado del circuito
        self.status_label = QLabel("● En espera")
        self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.status_label)

    def update_data(self, power_w: float, voltage: float, current: float, energy_kwh: float) -> None:
        """Actualiza los valores mostrados en la tarjeta."""
        self.power_label.setText(f"{power_w:.1f} W")
        self.voltage_label.setText(f"V: {voltage:.1f} V")
        self.current_label.setText(f"I: {current:.2f} A")
        self.energy_label.setText(f"E: {energy_kwh:.3f} kWh")

        if power_w > 10.0:
            self.status_label.setText("● Activo en carga")
            self.status_label.setStyleSheet("color: #22c55e; font-size: 11px; font-weight: bold;")
        elif power_w > 0.5:
            self.status_label.setText("● Standby / Reposo")
            self.status_label.setStyleSheet("color: #eab308; font-size: 11px;")
        else:
            self.status_label.setText("● Apagado")
            self.status_label.setStyleSheet("color: #64748b; font-size: 11px;")


class RealtimeTab(QWidget):
    """Pestaña de visualización en tiempo real de telemetría energética."""

    def __init__(
        self,
        circuits: List[Circuit],
        max_threshold_w: float = 5500.0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.circuits = {c.id: c for c in circuits}
        self.max_threshold_w = max_threshold_w

        # Buffers circulares para el gráfico en vivo (últimos 120 puntos)
        self.max_points = 120
        self.x_data: collections.deque[float] = collections.deque(maxlen=self.max_points)
        self.y_total_power: collections.deque[float] = collections.deque(maxlen=self.max_points)
        self.start_time = time.time()

        # Almacén de última potencia por circuito
        self.latest_circuit_power: Dict[str, float] = {c.id: 0.0 for c in circuits}
        self.latest_voltage = 120.0

        # Tarjetas de circuitos
        self.cards: Dict[str, CircuitCard] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # 1. Panel Superior: Medidor de Potencia Total Instantánea
        top_panel = QFrame()
        top_panel.setProperty("class", "card")
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(16, 14, 16, 14)

        # Indicador numérico principal
        val_box = QVBoxLayout()
        val_title = QLabel("POTENCIA INSTANTÁNEA TOTAL")
        val_title.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 600;")
        self.total_power_label = QLabel("0.0 W")
        self.total_power_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #38bdf8;")
        val_box.addWidget(val_title)
        val_box.addWidget(self.total_power_label)
        top_layout.addLayout(val_box, stretch=1)

        # Barra / Medidor visual de potencia respecto al umbral máximo
        gauge_box = QVBoxLayout()
        self.gauge_bar = QProgressBar()
        self.gauge_bar.setRange(0, int(self.max_threshold_w))
        self.gauge_bar.setValue(0)
        self.gauge_bar.setTextVisible(True)
        self.gauge_bar.setFormat(f"%v W / {int(self.max_threshold_w)} W (%p%)")
        self.gauge_bar.setFixedHeight(24)

        self.threshold_info = QLabel(f"Límite de alerta instantánea: {int(self.max_threshold_w)} W")
        self.threshold_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        gauge_box.addWidget(self.gauge_bar)
        gauge_box.addWidget(self.threshold_info)
        top_layout.addLayout(gauge_box, stretch=2)

        main_layout.addWidget(top_panel)

        # 2. Gráfico en Vivo (PyQtGraph)
        self.plot_widget = pg.PlotWidget(title="<b>Demanda de Potencia en Tiempo Real</b>")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("left", "Potencia", units="W")
        self.plot_widget.setLabel("bottom", "Tiempo transcurrido", units="s")
        self.plot_widget.setYRange(0, self.max_threshold_w * 0.8)
        self.plot_curve = self.plot_widget.plot(
            pen=pg.mkPen(color="#38bdf8", width=2.5),
            name="Potencia Total",
        )
        self.plot_widget.setMinimumHeight(240)
        main_layout.addWidget(self.plot_widget, stretch=3)

        # 3. Sección Inferior: Tarjetas de Circuitos con Scroll
        cards_title = QLabel("<b>Circuitos Monitoreados</b>")
        cards_title.setStyleSheet("font-size: 16px; margin-top: 6px;")
        main_layout.addWidget(cards_title)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        self.cards_grid = QGridLayout(scroll_content)
        self.cards_grid.setContentsMargins(4, 4, 4, 4)
        self.cards_grid.setSpacing(12)

        col = 0
        row = 0
        for i, (cid, circuit) in enumerate(self.circuits.items()):
            color = CIRCUIT_COLORS[i % len(CIRCUIT_COLORS)]
            card = CircuitCard(circuit=circuit, color=color)
            self.cards[cid] = card
            self.cards_grid.addWidget(card, row, col)
            col += 1
            if col >= 3:  # 3 columnas por fila
                col = 0
                row += 1

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=4)

    def set_max_threshold(self, threshold_w: float) -> None:
        """Actualiza el umbral máximo de potencia en el medidor."""
        self.max_threshold_w = max(500.0, threshold_w)
        self.gauge_bar.setRange(0, int(self.max_threshold_w))
        self.gauge_bar.setFormat(f"%v W / {int(self.max_threshold_w)} W (%p%)")
        self.threshold_info.setText(f"Límite de alerta instantánea: {int(self.max_threshold_w)} W")

    def handle_new_reading(self, reading_dict: dict) -> None:
        """Manejador disparado cuando llega una nueva lectura validada desde IPC."""
        cid = reading_dict.get("circuit_id")
        power = float(reading_dict.get("power_w", 0.0))
        voltage = float(reading_dict.get("voltage", 120.0))
        current = float(reading_dict.get("current", 0.0))
        energy = float(reading_dict.get("energy_kwh", 0.0))

        # Actualizar tarjeta del circuito
        if cid in self.cards:
            self.cards[cid].update_data(power, voltage, current, energy)
            self.latest_circuit_power[cid] = power
            self.latest_voltage = voltage

        # Calcular potencia total instantánea
        total_p = sum(self.latest_circuit_power.values())
        self.total_power_label.setText(f"{total_p:.1f} W")
        self.gauge_bar.setValue(int(total_p))

        # Color de advertencia en la barra si se supera el umbral
        if total_p > self.max_threshold_w:
            self.gauge_bar.setStyleSheet("QProgressBar::chunk { background-color: #dc2626; }")
        elif total_p > self.max_threshold_w * 0.8:
            self.gauge_bar.setStyleSheet("QProgressBar::chunk { background-color: #f97316; }")
        else:
            self.gauge_bar.setStyleSheet("")

        # Actualizar buffer de gráfico
        t_elapsed = time.time() - self.start_time
        self.x_data.append(t_elapsed)
        self.y_total_power.append(total_p)

        # Redibujar gráfico con bajo costo de CPU
        if len(self.x_data) > 1:
            self.plot_curve.setData(list(self.x_data), list(self.y_total_power))

    def update_circuits(self, circuits: List[Circuit]) -> None:
        """Reconstruye las tarjetas de circuitos cuando se modifiquen en configuración."""
        # Limpiar tarjetas previas
        for card in self.cards.values():
            card.deleteLater()
        self.cards.clear()
        self.circuits = {c.id: c for c in circuits}
        self.latest_circuit_power = {c.id: 0.0 for c in circuits}

        col = 0
        row = 0
        for i, (cid, circuit) in enumerate(self.circuits.items()):
            color = CIRCUIT_COLORS[i % len(CIRCUIT_COLORS)]
            card = CircuitCard(circuit=circuit, color=color)
            self.cards[cid] = card
            self.cards_grid.addWidget(card, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1
