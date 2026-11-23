"""Pestaña de configuración general del sistema, circuitos y tarifas eléctricas.

Provee un CRUD completo para la gestión de circuitos (nombre, ubicación, potencia e icono),
edición de esquemas de tarificación (fija y por horarios), intervalos de muestreo
y políticas de retención de datos.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.common.models import Circuit


class CircuitDialog(QDialog):
    """Diálogo para la creación y edición de circuitos eléctricos."""

    def __init__(self, circuit: Optional[Circuit] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar Circuito" if circuit else "Nuevo Circuito")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("ej. circ_06")
        if circuit:
            self.id_edit.setText(circuit.id)
            self.id_edit.setEnabled(False)  # No modificar clave primaria existente

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ej. Calentador de Agua")
        if circuit:
            self.name_edit.setText(circuit.name)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("ej. Baño Principal")
        if circuit:
            self.location_edit.setText(circuit.location)

        self.power_spin = QDoubleSpinBox()
        self.power_spin.setRange(10.0, 15000.0)
        self.power_spin.setValue(circuit.nominal_power_w if circuit else 1000.0)
        self.power_spin.setSuffix(" W")

        self.icon_combo = QComboBox()
        self.icon_combo.addItems([
            "zap",
            "refrigerator",
            "lightbulb",
            "air-conditioner",
            "washing-machine",
            "power-socket",
            "tv",
            "oven",
        ])
        if circuit:
            idx = self.icon_combo.findText(circuit.icon)
            if idx >= 0:
                self.icon_combo.setCurrentIndex(idx)

        self.active_check = QCheckBox("Circuito Activo")
        self.active_check.setChecked(circuit.is_active if circuit else True)

        form.addRow("Identificador (ID):", self.id_edit)
        form.addRow("Nombre descriptivo:", self.name_edit)
        form.addRow("Ubicación física:", self.location_edit)
        form.addRow("Potencia nominal:", self.power_spin)
        form.addRow("Icono visual:", self.icon_combo)
        form.addRow("Estado inicial:", self.active_check)

        layout.addLayout(form)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _validate_and_accept(self) -> None:
        if not self.id_edit.text().strip() or not self.name_edit.text().strip():
            QMessageBox.warning(self, "Campos incompletos", "El ID y el Nombre son obligatorios.")
            return
        self.accept()

    def get_circuit(self) -> Circuit:
        return Circuit(
            id=self.id_edit.text().strip(),
            name=self.name_edit.text().strip(),
            location=self.location_edit.text().strip() or "General",
            nominal_power_w=float(self.power_spin.value()),
            icon=self.icon_combo.currentText(),
            is_active=self.active_check.isChecked(),
        )


class ConfigTab(QWidget):
    """Pestaña de administración y edición de configuraciones del sistema."""

    circuits_changed = Signal(list)

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: DatabaseManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.cfg = config_manager
        self.db = db_manager

        self._init_ui()
        self.reload_circuits_table()

    def _init_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # ==========================================
        # 1. CRUD DE CIRCUITOS
        # ==========================================
        circuits_group = QGroupBox("Gestión de Circuitos Eléctricos")
        circ_layout = QVBoxLayout(circuits_group)

        # Botonera de acciones CRUD
        btn_bar = QHBoxLayout()
        self.btn_new_circuit = QPushButton("➕ Nuevo Circuito")
        self.btn_new_circuit.clicked.connect(self._add_circuit)
        self.btn_edit_circuit = QPushButton("✏️ Editar")
        self.btn_edit_circuit.setProperty("class", "secondary")
        self.btn_edit_circuit.clicked.connect(self._edit_circuit)
        self.btn_delete_circuit = QPushButton("🗑️ Eliminar")
        self.btn_delete_circuit.setProperty("class", "danger")
        self.btn_delete_circuit.clicked.connect(self._delete_circuit)

        btn_bar.addWidget(self.btn_new_circuit)
        btn_bar.addWidget(self.btn_edit_circuit)
        btn_bar.addWidget(self.btn_delete_circuit)
        btn_bar.addStretch()
        circ_layout.addLayout(btn_bar)

        # Tabla de circuitos
        self.table_circuits = QTableWidget()
        self.table_circuits.setColumnCount(6)
        self.table_circuits.setHorizontalHeaderLabels([
            "ID",
            "Nombre",
            "Ubicación",
            "Potencia Nominal (W)",
            "Icono",
            "Activo",
        ])
        self.table_circuits.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_circuits.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_circuits.setSelectionMode(QTableWidget.SingleSelection)
        self.table_circuits.setFixedHeight(180)
        circ_layout.addWidget(self.table_circuits)

        layout.addWidget(circuits_group)

        # ==========================================
        # 2. CONFIGURACIÓN DE TARIFA ELÉCTRICA
        # ==========================================
        tariff_group = QGroupBox("Tarifa Eléctrica y Facturación")
        t_layout = QVBoxLayout(tariff_group)

        form_tariff = QFormLayout()
        self.tariff_base_spin = QDoubleSpinBox()
        self.tariff_base_spin.setRange(0.01, 5.0)
        self.tariff_base_spin.setSingleStep(0.01)
        self.tariff_base_spin.setValue(self.cfg.tariff.get("base_rate_per_kwh", 0.15))
        self.tariff_base_spin.setPrefix("$ ")
        self.tariff_base_spin.setSuffix(" / kWh")

        self.currency_edit = QLineEdit()
        self.currency_edit.setText(self.cfg.tariff.get("currency", "USD"))
        self.currency_edit.setMaximumWidth(80)

        self.tou_check = QCheckBox("Habilitar Tarifa por Horarios (Valle / Llano / Punta)")
        self.tou_check.setChecked(bool(self.cfg.tariff.get("time_of_use_enabled", True)))

        form_tariff.addRow("Tarifa Base General:", self.tariff_base_spin)
        form_tariff.addRow("Moneda:", self.currency_edit)
        form_tariff.addRow("", self.tou_check)
        t_layout.addLayout(form_tariff)

        layout.addWidget(tariff_group)

        # ==========================================
        # 3. PARÁMETROS OPERATIVOS Y RETENCIÓN
        # ==========================================
        sys_group = QGroupBox("Parámetros del Sistema y Retención de Datos")
        sys_layout = QFormLayout(sys_group)

        self.sampling_spin = QSpinBox()
        self.sampling_spin.setRange(1, 60)
        self.sampling_spin.setValue(self.cfg.sampling_interval)
        self.sampling_spin.setSuffix(" segundos")

        retention = self.cfg.retention_policy
        self.raw_ret_spin = QSpinBox()
        self.raw_ret_spin.setRange(1, 365)
        self.raw_ret_spin.setValue(retention.get("raw_readings_days", 30))
        self.raw_ret_spin.setSuffix(" días")

        self.agg_ret_spin = QSpinBox()
        self.agg_ret_spin.setRange(30, 3650)
        self.agg_ret_spin.setValue(retention.get("aggregates_days", 730))
        self.agg_ret_spin.setSuffix(" días")

        sys_layout.addRow("Intervalo de Muestreo de Sensores:", self.sampling_spin)
        sys_layout.addRow("Retención de Lecturas Crudas:", self.raw_ret_spin)
        sys_layout.addRow("Retención de Tablas Agregadas:", self.agg_ret_spin)

        layout.addWidget(sys_group)

        # ==========================================
        # BOTÓN GUARDAR TODO
        # ==========================================
        self.btn_save_all = QPushButton("💾 Guardar Configuración Completa")
        self.btn_save_all.setFixedHeight(38)
        self.btn_save_all.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.btn_save_all.clicked.connect(self._save_all_settings)
        layout.addWidget(self.btn_save_all)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def reload_circuits_table(self) -> None:
        """Recarga la lista de circuitos desde la base de datos."""
        circuits = self.db.get_circuits()
        self.table_circuits.setRowCount(len(circuits))

        for row, c in enumerate(circuits):
            self.table_circuits.setItem(row, 0, QTableWidgetItem(c.id))
            self.table_circuits.setItem(row, 1, QTableWidgetItem(c.name))
            self.table_circuits.setItem(row, 2, QTableWidgetItem(c.location))
            self.table_circuits.setItem(row, 3, QTableWidgetItem(f"{c.nominal_power_w:.1f}"))
            self.table_circuits.setItem(row, 4, QTableWidgetItem(c.icon))
            status_text = "Sí" if c.is_active else "No"
            self.table_circuits.setItem(row, 5, QTableWidgetItem(status_text))

    def _add_circuit(self) -> None:
        dialog = CircuitDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_circuit = dialog.get_circuit()
            # Guardar en SQLite y Config
            self.db.upsert_circuit(new_circuit)
            current_circuits = self.db.get_circuits()
            self.cfg.set_circuits(current_circuits)
            self.cfg.save()
            self.reload_circuits_table()
            self.circuits_changed.emit(current_circuits)

    def _edit_circuit(self) -> None:
        row = self.table_circuits.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seleccionar", "Seleccione un circuito para editar.")
            return

        cid = self.table_circuits.item(row, 0).text()
        circuits = {c.id: c for c in self.db.get_circuits()}
        target = circuits.get(cid)
        if not target:
            return

        dialog = CircuitDialog(circuit=target, parent=self)
        if dialog.exec() == QDialog.Accepted:
            updated_circuit = dialog.get_circuit()
            self.db.upsert_circuit(updated_circuit)
            current_circuits = self.db.get_circuits()
            self.cfg.set_circuits(current_circuits)
            self.cfg.save()
            self.reload_circuits_table()
            self.circuits_changed.emit(current_circuits)

    def _delete_circuit(self) -> None:
        row = self.table_circuits.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seleccionar", "Seleccione un circuito para eliminar.")
            return

        cid = self.table_circuits.item(row, 0).text()
        name = self.table_circuits.item(row, 1).text()

        confirm = QMessageBox.question(
            self,
            "Confirmar Eliminación",
            f"¿Está seguro de eliminar el circuito '{name}' ({cid}) y sus datos asociados?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.db.delete_circuit(cid)
            current_circuits = self.db.get_circuits()
            self.cfg.set_circuits(current_circuits)
            self.cfg.save()
            self.reload_circuits_table()
            self.circuits_changed.emit(current_circuits)

    def _save_all_settings(self) -> None:
        """Persiste todas las modificaciones de tarifa, muestreo y retención."""
        # 1. Tarifa
        tariff = self.cfg.tariff
        tariff["base_rate_per_kwh"] = float(self.tariff_base_spin.value())
        tariff["currency"] = self.currency_edit.text().strip() or "USD"
        tariff["time_of_use_enabled"] = self.tou_check.isChecked()
        self.cfg.update_section("tariff", tariff)

        # 2. Muestreo
        self.cfg.sampling_interval = int(self.sampling_spin.value())

        # 3. Retención
        self.cfg.update_section("retention", {
            "raw_readings_days": int(self.raw_ret_spin.value()),
            "aggregates_days": int(self.agg_ret_spin.value()),
        })

        if self.cfg.save():
            QMessageBox.information(self, "Configuración", "Configuración guardada exitosamente.")
        else:
            QMessageBox.critical(self, "Error", "No se pudo guardar la configuración en disco.")
