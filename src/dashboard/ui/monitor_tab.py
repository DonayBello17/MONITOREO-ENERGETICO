"""Pestaña de monitoreo del sistema y salud del proceso recolector.

Supervisa en vivo el uso de recursos (CPU % y Memoria RAM en MB) del proceso
recolector en segundo plano usando psutil, mostrando métricas numéricas y
gráficos temporales, alertando si el proceso se encuentra caído o inactivo.
"""

from __future__ import annotations

import collections
import time
from pathlib import Path
from typing import Optional

import psutil
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.collector.main import get_pid_file_path


class MonitorTab(QWidget):
    """Pestaña de supervisión de recursos del proceso recolector."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.collector_pid: Optional[int] = None
        self._proc: Optional[psutil.Process] = None

        # Buffers temporales para gráficos (últimos 60 puntos)
        self.max_points = 60
        self.x_data: collections.deque[float] = collections.deque(maxlen=self.max_points)
        self.y_cpu: collections.deque[float] = collections.deque(maxlen=self.max_points)
        self.y_ram: collections.deque[float] = collections.deque(maxlen=self.max_points)
        self.start_time = time.time()

        self._init_ui()

        # Temporizador para actualizar métricas de recursos cada 1.5s
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_metrics)
        self.timer.start(1500)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(14)

        # 1. Panel Superior de Estado y KPIs
        top_cards = QHBoxLayout()
        top_cards.setSpacing(12)

        # Tarjeta 1: Estado y PID
        self.card_status = self._create_card("PROCESO RECOLECTOR", "Buscando...", "PID: --")
        top_cards.addWidget(self.card_status["frame"])

        # Tarjeta 2: Uso de CPU
        self.card_cpu = self._create_card("USO DE CPU", "0.0 %", "Recolector")
        top_cards.addWidget(self.card_cpu["frame"])

        # Tarjeta 3: Memoria RAM
        self.card_ram = self._create_card("MEMORIA RAM", "0.0 MB", "Memoria Residente (RSS)")
        top_cards.addWidget(self.card_ram["frame"])

        # Tarjeta 4: Tiempo de Actividad / Hilos
        self.card_threads = self._create_card("HILOS ACTIVOS", "--", "Estado: Normal")
        top_cards.addWidget(self.card_threads["frame"])

        main_layout.addLayout(top_cards)

        # 2. Gráficos de Recursos en Vivo
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(12)

        # Gráfico CPU
        self.cpu_plot = pg.PlotWidget(title="<b>Uso de CPU del Recolector (%)</b>")
        self.cpu_plot.showGrid(x=True, y=True, alpha=0.3)
        self.cpu_plot.setLabel("left", "CPU", units="%")
        self.cpu_plot.setLabel("bottom", "Tiempo", units="s")
        self.cpu_plot.setYRange(0, 100)
        self.cpu_curve = self.cpu_plot.plot(pen=pg.mkPen(color="#38bdf8", width=2))
        charts_layout.addWidget(self.cpu_plot)

        # Gráfico Memoria RAM
        self.ram_plot = pg.PlotWidget(title="<b>Memoria RAM del Recolector (MB)</b>")
        self.ram_plot.showGrid(x=True, y=True, alpha=0.3)
        self.ram_plot.setLabel("left", "RAM", units="MB")
        self.ram_plot.setLabel("bottom", "Tiempo", units="s")
        self.ram_curve = self.ram_plot.plot(pen=pg.mkPen(color="#a855f7", width=2))
        charts_layout.addWidget(self.ram_plot)

        main_layout.addLayout(charts_layout, stretch=1)

    def _create_card(self, title: str, val: str, sub: str) -> dict:
        frame = QFrame()
        frame.setProperty("class", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        lbl_val = QLabel(val)
        lbl_val.setStyleSheet("font-size: 20px; font-weight: bold; color: #38bdf8;")
        lbl_sub = QLabel(sub)
        lbl_sub.setStyleSheet("color: #64748b; font-size: 11px;")

        layout.addWidget(lbl_title)
        layout.addWidget(lbl_val)
        layout.addWidget(lbl_sub)
        return {"frame": frame, "val": lbl_val, "sub": lbl_sub}

    def set_pid_from_ipc(self, pid: int) -> None:
        """Permite fijar o actualizar el PID directamente desde el mensaje de estado IPC."""
        if pid > 0 and pid != self.collector_pid:
            self.collector_pid = pid
            self._proc = None

    def _discover_collector_pid(self) -> Optional[int]:
        """Lee el PID desde el archivo collector.pid."""
        pid_file = get_pid_file_path()
        if pid_file.exists():
            try:
                with open(pid_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.isdigit():
                        return int(content)
            except Exception:
                pass
        return None

    def _update_metrics(self) -> None:
        """Consulta métricas de psutil y actualiza la interfaz y gráficos."""
        # Si no tenemos PID aún, intentar leerlo del archivo PID
        if not self.collector_pid:
            self.collector_pid = self._discover_collector_pid()

        if not self.collector_pid:
            self.card_status["val"].setText("Detenido / No iniciado")
            self.card_status["val"].setStyleSheet("font-size: 18px; font-weight: bold; color: #f97316;")
            self.card_status["sub"].setText("Archivo PID no encontrado")
            self.card_cpu["val"].setText("0.0 %")
            self.card_ram["val"].setText("0.0 MB")
            self.card_threads["val"].setText("--")
            return

        # Verificar o crear instancia psutil.Process
        if self._proc is None or self._proc.pid != self.collector_pid:
            try:
                self._proc = psutil.Process(self.collector_pid)
                # Primera llamada a cpu_percent devuelve 0.0 para inicializar contador
                self._proc.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._proc = None
                self.collector_pid = None
                self.card_status["val"].setText("Proceso Caído")
                self.card_status["val"].setStyleSheet("font-size: 18px; font-weight: bold; color: #dc2626;")
                self.card_status["sub"].setText("El PID ya no existe en el sistema")
                return

        try:
            if not self._proc.is_running() or self._proc.status() == psutil.STATUS_ZOMBIE:
                self._proc = None
                self.collector_pid = None
                self.card_status["val"].setText("Proceso Caído")
                self.card_status["val"].setStyleSheet("font-size: 18px; font-weight: bold; color: #dc2626;")
                return

            cpu = self._proc.cpu_percent()
            mem_info = self._proc.memory_info()
            ram_mb = mem_info.rss / (1024.0 * 1024.0)
            num_threads = self._proc.num_threads()

            # Actualizar tarjetas
            self.card_status["val"].setText("En Ejecución")
            self.card_status["val"].setStyleSheet("font-size: 18px; font-weight: bold; color: #22c55e;")
            self.card_status["sub"].setText(f"PID: {self.collector_pid}")

            self.card_cpu["val"].setText(f"{cpu:.1f} %")
            self.card_ram["val"].setText(f"{ram_mb:.1f} MB")
            self.card_threads["val"].setText(f"{num_threads} hilos")

            # Actualizar buffers para gráficos
            t_rel = time.time() - self.start_time
            self.x_data.append(t_rel)
            self.y_cpu.append(cpu)
            self.y_ram.append(ram_mb)

            if len(self.x_data) > 1:
                self.cpu_curve.setData(list(self.x_data), list(self.y_cpu))
                self.ram_curve.setData(list(self.x_data), list(self.y_ram))

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._proc = None
            self.collector_pid = None
            self.card_status["val"].setText("Proceso Detenido")
            self.card_status["val"].setStyleSheet("font-size: 18px; font-weight: bold; color: #dc2626;")
