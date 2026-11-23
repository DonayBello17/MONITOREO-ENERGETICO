"""Generador de reportes mensuales en formato PDF con ReportLab.

Incluye:
- Encabezado institucional y metadatos de emisión.
- Resumen ejecutivo de consumo total (kWh) y costo monetario estimado.
- Gráfico de barras embebido de consumo diario a lo largo del mes.
- Gráfico de pastel embebido de distribución porcentual por circuito.
- Tabla detallada de consumo por circuito con potencias y costos.
- Numeración dinámica de páginas ('Página X de Y') y encabezado/pie de página.
- Ejecución asíncrona mediante QThread para evitar congelamiento de la interfaz.
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PySide6.QtCore import QThread, Signal
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.common.config_manager import ConfigManager
from src.common.database import DatabaseManager
from src.dashboard.cost_calculator import calculate_fixed_cost

logger = logging.getLogger(__name__)

# Paleta cromática corporativa para reportes
PDF_COLORS = [
    HexColor("#2563eb"),  # Azul
    HexColor("#eab308"),  # Amarillo
    HexColor("#06b6d4"),  # Cian
    HexColor("#a855f7"),  # Púrpura
    HexColor("#10b981"),  # Esmeralda
    HexColor("#f97316"),  # Naranja
    HexColor("#ec4899"),  # Rosa
    HexColor("#64748b"),  # Gris
]


class NumberedCanvas(canvas.Canvas):
    """Canvas de dos pasadas para calcular dinámicamente el total de páginas 'Página X de Y'."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def _draw_page_decorations(self, total_pages: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(HexColor("#64748b"))

        # Encabezado superior
        self.drawString(54, 750, "Sistema de Monitoreo Energético para Vivienda | Reporte Mensual")
        self.setStrokeColor(HexColor("#e2e8f0"))
        self.setLineWidth(0.75)
        self.line(54, 742, 558, 742)

        # Pie de página inferior
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Documento confidencial generado automáticamente.")
        page_str = f"Página {self._pageNumber} de {total_pages}"
        self.drawRightString(558, 32, page_str)

        self.restoreState()


def _build_daily_chart(daily_totals: Dict[int, float], days_in_month: int) -> Drawing:
    """Construye un gráfico de barras embebido con el consumo diario en kWh."""
    d = Drawing(504, 150)

    # Fondo suave para el gráfico
    d.add(Rect(0, 0, 504, 150, fillColor=HexColor("#f8fafc"), strokeColor=HexColor("#e2e8f0"), strokeWidth=0.5))

    chart = VerticalBarChart()
    chart.x = 45
    chart.y = 25
    chart.height = 105
    chart.width = 445

    days_data = [daily_totals.get(day, 0.0) for day in range(1, days_in_month + 1)]
    chart.data = [days_data]
    chart.categoryAxis.categoryNames = [str(d) if d % 2 != 0 or d == days_in_month else "" for d in range(1, days_in_month + 1)]
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor = HexColor("#475569")

    chart.valueAxis.valueMin = 0
    max_val = max(days_data) if days_data and max(days_data) > 0 else 5.0
    chart.valueAxis.valueMax = max_val * 1.15
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = HexColor("#475569")

    chart.bars[0].fillColor = HexColor("#38bdf8")
    chart.bars[0].strokeColor = HexColor("#0284c7")
    chart.bars[0].strokeWidth = 0.5

    d.add(chart)
    return d


def _build_pie_chart(circuit_data: List[Dict[str, Any]]) -> Drawing:
    """Construye un gráfico de pastel embebido con la distribución de consumo por circuito."""
    d = Drawing(504, 150)
    d.add(Rect(0, 0, 504, 150, fillColor=HexColor("#f8fafc"), strokeColor=HexColor("#e2e8f0"), strokeWidth=0.5))

    # Filtrar circuitos con consumo > 0
    active_circuits = [c for c in circuit_data if c["energy_kwh"] > 0]
    if not active_circuits:
        d.add(String(200, 75, "Sin datos de consumo registrados para el periodo", fontSize=10, fillColor=HexColor("#64748b")))
        return d

    pie = Pie()
    pie.x = 60
    pie.y = 15
    pie.width = 120
    pie.height = 120
    pie.data = [c["energy_kwh"] for c in active_circuits]
    pie.labels = [f"{c['pct']:.1f}%" for c in active_circuits]
    pie.simpleLabels = 0

    for idx in range(len(active_circuits)):
        pie.slices[idx].fillColor = PDF_COLORS[idx % len(PDF_COLORS)]
        pie.slices[idx].strokeColor = colors.white
        pie.slices[idx].strokeWidth = 1.0

    d.add(pie)

    # Leyenda al lado derecho
    legend = Legend()
    legend.x = 240
    legend.y = 125
    legend.dx = 10
    legend.dy = 10
    legend.fontName = "Helvetica"
    legend.fontSize = 8
    legend.boxAnchor = "nw"
    legend.columnMaximum = 8
    legend.strokeWidth = 0
    legend.strokeColor = colors.transparent
    legend.colorNamePairs = [(PDF_COLORS[i % len(PDF_COLORS)], f"{c['name']} ({c['energy_kwh']:.2f} kWh)") for i, c in enumerate(active_circuits)]

    d.add(legend)
    return d


def generate_monthly_pdf_report(
    db: DatabaseManager,
    config: ConfigManager,
    year: int,
    month: int,
    output_path: Union[Path, str],
) -> str:
    """Genera el reporte mensual completo en PDF con tablas y gráficos vectoriales embebidos.

    Args:
        db: Gestor de base de datos SQLite.
        config: Gestor de configuración.
        year: Año del reporte (ej. 2026).
        month: Mes del reporte (1 a 12).
        output_path: Ruta de salida del archivo PDF.

    Returns:
        str: Ruta absoluta al archivo PDF generado.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Rango temporal del mes
    _, days_in_month = calendar.monthrange(year, month)
    dt_start = datetime(year, month, 1, 0, 0, 0)
    dt_end = datetime(year, month, days_in_month, 23, 59, 59)
    start_ts = dt_start.timestamp()
    end_ts = dt_end.timestamp()

    month_name = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ][month - 1]

    # 2. Consultar datos agregados diarios
    daily_aggregates = db.get_aggregates("daily", start_time=start_ts, end_time=end_ts)
    circuits = {c.id: c for c in db.get_circuits()}

    # Agrupaciones
    daily_totals: Dict[int, float] = {}
    circuit_stats: Dict[str, Dict[str, Any]] = {
        cid: {"energy": 0.0, "powers": [], "peak_power": 0.0} for cid in circuits
    }

    total_month_kwh = 0.0
    for agg in daily_aggregates:
        day_num = datetime.fromtimestamp(agg.period_start).day
        daily_totals[day_num] = daily_totals.get(day_num, 0.0) + agg.total_energy_kwh
        total_month_kwh += agg.total_energy_kwh

        if agg.circuit_id in circuit_stats:
            stats = circuit_stats[agg.circuit_id]
            stats["energy"] += agg.total_energy_kwh
            stats["powers"].append(agg.avg_power_w)
            if agg.max_power_w > stats["peak_power"]:
                stats["peak_power"] = agg.max_power_w

    # Tarifas y costos
    tariff_data = config.tariff
    base_rate = float(tariff_data.get("base_rate_per_kwh", 0.15))
    currency = tariff_data.get("currency", "USD")
    total_cost = calculate_fixed_cost(total_month_kwh, base_rate)
    budget = float(config.alert_thresholds.get("monthly_budget", 120.0))

    # Tabla de circuitos procesada
    circuit_rows: List[Dict[str, Any]] = []
    for cid, c in circuits.items():
        st = circuit_stats.get(cid, {"energy": 0.0, "powers": [], "peak_power": 0.0})
        e_kwh = st["energy"]
        pct = (e_kwh / total_month_kwh * 100.0) if total_month_kwh > 0 else 0.0
        avg_p = sum(st["powers"]) / len(st["powers"]) if st["powers"] else 0.0
        c_cost = calculate_fixed_cost(e_kwh, base_rate)

        circuit_rows.append({
            "id": cid,
            "name": c.name,
            "location": c.location,
            "energy_kwh": e_kwh,
            "pct": pct,
            "avg_power": avg_p,
            "peak_power": st["peak_power"],
            "cost": c_cost,
        })

    # Ordenar por mayor consumo
    circuit_rows.sort(key=lambda x: x["energy_kwh"], reverse=True)

    # 3. Construcción del Documento con ReportLab
    doc = SimpleDocTemplate(
        str(out_file),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Estilos personalizados
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        textColor=HexColor("#475569"),
    )
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=HexColor("#1e40af"),
        spaceBefore=14,
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=HexColor("#1e293b"),
    )
    cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=cell_style,
        fontName="Helvetica-Bold",
    )

    story = []

    # Encabezado principal
    story.append(Paragraph("<b>REPORTE MENSUAL DE EFICIENCIA ENERGÉTICA</b>", title_style))
    story.append(Paragraph(f"Periodo: <b>{month_name} {year}</b> | Emitido el {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#3b82f6"), spaceAfter=14))

    # Resumen Ejecutivo / Tarjetas KPI en tabla
    budget_pct = (total_cost / budget * 100.0) if budget > 0 else 0.0
    budget_color = "#dc2626" if total_cost > budget else "#16a34a"

    summary_data = [
        [
            Paragraph("<b>CONSUMO TOTAL</b>", cell_style),
            Paragraph("<b>COSTO ESTIMADO</b>", cell_style),
            Paragraph("<b>TARIFA BASE</b>", cell_style),
            Paragraph("<b>EJECUCIÓN PRESUPUESTO</b>", cell_style),
        ],
        [
            Paragraph(f"<font size=13 color='#0284c7'><b>{total_month_kwh:.2f} kWh</b></font>", cell_style),
            Paragraph(f"<font size=13 color='#0284c7'><b>${total_cost:.2f} {currency}</b></font>", cell_style),
            Paragraph(f"<font size=11><b>${base_rate:.3f} / kWh</b></font>", cell_style),
            Paragraph(f"<font size=11 color='{budget_color}'><b>{budget_pct:.1f}% (${budget:.2f})</b></font>", cell_style),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[126, 126, 126, 126])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 1, HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # Gráfico 1: Consumo diario del mes
    story.append(Paragraph("1. Evolución del Consumo Diario de Energía (kWh)", section_title))
    daily_chart = _build_daily_chart(daily_totals, days_in_month)
    story.append(daily_chart)
    story.append(Spacer(1, 14))

    # Gráfico 2: Distribución por circuito
    story.append(Paragraph("2. Distribución del Consumo por Circuito (%)", section_title))
    pie_chart = _build_pie_chart(circuit_rows)
    story.append(pie_chart)
    story.append(Spacer(1, 14))

    # Tabla Desglosada por Circuito
    story.append(Paragraph("3. Desglose Detallado por Circuito", section_title))

    table_data = [[
        Paragraph("<b>Circuito</b>", cell_bold),
        Paragraph("<b>Ubicación</b>", cell_bold),
        Paragraph("<b>Consumo (kWh)</b>", cell_bold),
        Paragraph("<b>Part. (%)</b>", cell_bold),
        Paragraph("<b>Pot. Media (W)</b>", cell_bold),
        Paragraph("<b>Pot. Pico (W)</b>", cell_bold),
        Paragraph(f"<b>Costo ({currency})</b>", cell_bold),
    ]]

    for r in circuit_rows:
        table_data.append([
            Paragraph(r["name"], cell_style),
            Paragraph(r["location"], cell_style),
            Paragraph(f"{r['energy_kwh']:.2f}", cell_style),
            Paragraph(f"{r['pct']:.1f}%", cell_style),
            Paragraph(f"{r['avg_power']:.1f}", cell_style),
            Paragraph(f"{r['peak_power']:.1f}", cell_style),
            Paragraph(f"${r['cost']:.2f}", cell_style),
        ])

    # Fila de totales
    table_data.append([
        Paragraph("<b>TOTAL</b>", cell_bold),
        Paragraph("-", cell_style),
        Paragraph(f"<b>{total_month_kwh:.2f}</b>", cell_bold),
        Paragraph("<b>100.0%</b>", cell_bold),
        Paragraph("-", cell_style),
        Paragraph("-", cell_style),
        Paragraph(f"<b>${total_cost:.2f}</b>", cell_bold),
    ])

    col_widths = [110, 85, 75, 55, 65, 60, 54]
    detail_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(KeepTogether(detail_table))

    # Construir PDF con NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info("Reporte PDF generado exitosamente: %s", out_file)
    return str(out_file)


class GeneratePdfWorker(QThread):
    """Hilo de trabajo para generar el reporte PDF mensual sin congelar la UI."""

    finished = Signal(bool, str)  # success, message

    def __init__(
        self,
        db: DatabaseManager,
        config: ConfigManager,
        year: int,
        month: int,
        output_path: str,
        parent: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.year = year
        self.month = month
        self.output_path = output_path

    def run(self) -> None:
        try:
            path = generate_monthly_pdf_report(
                db=self.db,
                config=self.config,
                year=self.year,
                month=self.month,
                output_path=self.output_path,
            )
            self.finished.emit(True, f"Reporte PDF generado exitosamente en:\n{path}")
        except Exception as exc:
            logger.error("Error al generar reporte PDF: %s", exc)
            self.finished.emit(False, f"Error al generar reporte PDF: {exc}")
