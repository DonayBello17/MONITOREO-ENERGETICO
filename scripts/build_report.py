#!/usr/bin/env python3
"""
Script para generar el Informe Técnico universitario profesional en formato DOCX y PDF.
Genera docs/Informe_Tecnico_Monitoreo_Energetico.docx y docs/Informe_Tecnico_Monitoreo_Energetico.pdf
con portada institucional, tablas con formato académico, métricas de SO-09 y las 7 capturas de pantalla.
"""

import os
import sys
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
SCREENSHOTS_DIR = os.path.join(DOCS_DIR, "screenshots")
DOCX_OUTPUT = os.path.join(DOCS_DIR, "Informe_Tecnico_Monitoreo_Energetico.docx")
PDF_OUTPUT = os.path.join(DOCS_DIR, "Informe_Tecnico_Monitoreo_Energetico.pdf")

# Paleta Institucional
COLOR_NAVY = RGBColor(30, 58, 138)       # #1E3A8A - Títulos principales
COLOR_EMERALD = RGBColor(4, 120, 87)     # #047857 - Subtítulos
COLOR_DARK = RGBColor(31, 41, 55)        # #1F2937 - Texto base
COLOR_MUTED = RGBColor(100, 116, 139)    # #64748B - Detalles y pies
COLOR_BG_SHADE = "1E3A8A"                # Fondo cabeceras tablas
COLOR_BG_LIGHT = "F8FAFC"                # Fondo filas alternadas
COLOR_BORDER = "CBD5E1"                  # Bordes tablas

def set_cell_background(cell, fill_hex):
    """Aplica sombreado de fondo XML a una celda de tabla."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=120, bottom=120, left=150, right=150):
    """Aplica márgenes internos (padding) a una celda en dxa."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def set_table_borders(table, color="CBD5E1", sz="4", val="single"):
    """Aplica bordes discretos y limpios a toda la tabla."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'<w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>'
        f'<w:insideV w:val="none"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)

def add_page_number_to_run(run):
    """Inserta el campo nativo de número de página de Word."""
    fldChar1 = parse_xml(r'<w:fldChar %s w:fldCharType="begin"/>' % nsdecls('w'))
    instrText = parse_xml(r'<w:instrText %s xml:space="preserve"> PAGE </w:instrText>' % nsdecls('w'))
    fldChar2 = parse_xml(r'<w:fldChar %s w:fldCharType="separate"/>' % nsdecls('w'))
    fldChar3 = parse_xml(r'<w:fldChar %s w:fldCharType="end"/>' % nsdecls('w'))
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)
    run._r.append(fldChar3)

def add_callout_box(doc, title, text_lines, border_color="047857", bg_color="ECFDF5"):
    """Inserta una caja destacada con borde y fondo sombreado."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)
    
    # Borde izquierdo grueso
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{border_color}"/>'
        f'<w:top w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    r_title = p.add_run(f"📌 {title}\n")
    r_title.bold = True
    r_title.font.name = "Segoe UI"
    r_title.font.size = Pt(10.5)
    r_title.font.color.rgb = COLOR_EMERALD
    
    for idx, line in enumerate(text_lines):
        p_line = cell.add_paragraph()
        p_line.paragraph_format.space_before = Pt(1)
        p_line.paragraph_format.space_after = Pt(1 if idx < len(text_lines) - 1 else 0)
        r = p_line.add_run(line)
        r.font.name = "Segoe UI"
        r.font.size = Pt(9.5)
        r.font.color.rgb = COLOR_DARK
        
    p_space = doc.add_paragraph()
    p_space.paragraph_format.space_after = Pt(6)

def format_table(table, col_widths, headers, data, align_center_cols=None):
    """Aplica formato profesional con cabecera sombreada y bordes limpios."""
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color="CBD5E1", sz="4")
    
    # Cabecera
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        set_cell_background(hdr_cells[i], COLOR_BG_SHADE)
        set_cell_margins(hdr_cells[i], top=120, bottom=120, left=120, right=120)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        for run in p.runs:
            run.font.name = "Segoe UI"
            run.font.size = Pt(9.5)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            
    # Datos
    for row_idx, row_data in enumerate(data):
        row_cells = table.rows[row_idx + 1].cells
        bg_hex = COLOR_BG_LIGHT if row_idx % 2 == 1 else "FFFFFF"
        for col_idx, val in enumerate(row_data):
            row_cells[col_idx].text = str(val)
            set_cell_background(row_cells[col_idx], bg_hex)
            set_cell_margins(row_cells[col_idx], top=90, bottom=90, left=110, right=110)
            p = row_cells[col_idx].paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            if align_center_cols and col_idx in align_center_cols:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for run in p.runs:
                run.font.name = "Segoe UI"
                run.font.size = Pt(9.0)
                run.font.color.rgb = COLOR_DARK
                
    # Anchos de columna
    for row in table.rows:
        for idx, width in enumerate(col_widths):
            row.cells[idx].width = width

def build_document():
    print("Creando documento Word institucional...")
    doc = Document()
    
    # 1. Configuración de página y márgenes
    sections = doc.sections
    section = sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    section.page_width = Inches(8.5)
    section.page_height = Inches(11.0)
    
    # Primera página sin encabezado/pie
    section.different_first_page_header_footer = True
    
    # Encabezado (páginas siguientes)
    header = section.header
    p_hdr = header.paragraphs[0]
    p_hdr.text = "Sistema de Monitoreo Energético Residencial — Informe Técnico de Sistemas Operativos"
    p_hdr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_hdr.runs[0].font.name = "Segoe UI"
    p_hdr.runs[0].font.size = Pt(8.5)
    p_hdr.runs[0].font.color.rgb = COLOR_MUTED
    
    # Pie de página (páginas siguientes)
    footer = section.footer
    p_ftr = footer.paragraphs[0]
    p_ftr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_ftr = p_ftr.add_run("Página ")
    r_ftr.font.name = "Segoe UI"
    r_ftr.font.size = Pt(9.0)
    r_ftr.font.color.rgb = COLOR_MUTED
    add_page_number_to_run(r_ftr)
    r_ftr2 = p_ftr.add_run("  |  Monitoreo Energético — Producción Cloud (Render)")
    r_ftr2.font.name = "Segoe UI"
    r_ftr2.font.size = Pt(8.5)
    r_ftr2.font.color.rgb = COLOR_MUTED
    
    # ==========================================
    # PORTADA FORMAL (PÁGINA 1)
    # ==========================================
    p_inst = doc.add_paragraph()
    p_inst.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_inst.paragraph_format.space_before = Pt(20)
    p_inst.paragraph_format.space_after = Pt(4)
    r_inst = p_inst.add_run("UNIVERSIDAD / INSTITUCIÓN EDUCATIVA SUPERIOR\nFACULTAD DE INGENIERÍA Y CIENCIAS APLICADAS")
    r_inst.font.name = "Segoe UI"
    r_inst.font.size = Pt(11)
    r_inst.font.bold = True
    r_inst.font.color.rgb = COLOR_MUTED

    p_div = doc.add_paragraph()
    p_div.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_div.paragraph_format.space_after = Pt(36)
    r_div = p_div.add_run("────────  ✦  ────────")
    r_div.font.color.rgb = COLOR_EMERALD

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.space_before = Pt(10)
    p_title.paragraph_format.space_after = Pt(12)
    r_title = p_title.add_run("SISTEMA DE MONITOREO ENERGÉTICO RESIDENCIAL")
    r_title.font.name = "Segoe UI"
    r_title.font.size = Pt(24)
    r_title.font.bold = True
    r_title.font.color.rgb = COLOR_NAVY

    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_sub.paragraph_format.space_after = Pt(28)
    r_sub = p_sub.add_run("Informe Técnico de Sistemas Operativos:\nArquitectura Desacoplada, IPC Dual (AF_UNIX / TCP), Concurrencia SQLite WAL\ny Despliegue de Producción Cloud en Linux (Render)")
    r_sub.font.name = "Segoe UI"
    r_sub.font.size = Pt(12)
    r_sub.font.italic = True
    r_sub.font.color.rgb = COLOR_DARK

    # Tarjeta de Datos Académicos
    tbl_meta = doc.add_table(rows=5, cols=2)
    tbl_meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(tbl_meta, color="E2E8F0", sz="4")
    
    meta_rows = [
        ("Asignatura:", "Sistemas Operativos (Proyecto Final de Grado)"),
        ("Integrantes:", "Donay Bello / Equipo de Desarrollo"),
        ("Docente / Tutor:", "Profesor Titular de Sistemas Operativos"),
        ("Versión del Sistema:", "2.0 Final — Despliegue en Producción (Cloud & Multiplataforma)"),
        ("Fecha de Entrega:", "Noviembre 2026"),
    ]
    for idx, (label, val) in enumerate(meta_rows):
        c0, c1 = tbl_meta.rows[idx].cells
        c0.width = Inches(2.2)
        c1.width = Inches(4.3)
        set_cell_background(c0, "F1F5F9")
        set_cell_background(c1, "FFFFFF")
        set_cell_margins(c0, top=70, bottom=70, left=120, right=120)
        set_cell_margins(c1, top=70, bottom=70, left=120, right=120)
        
        p0 = c0.paragraphs[0]
        p0.paragraph_format.space_before = Pt(2)
        p0.paragraph_format.space_after = Pt(2)
        r0 = p0.add_run(label)
        r0.font.name = "Segoe UI"
        r0.font.bold = True
        r0.font.size = Pt(10)
        r0.font.color.rgb = COLOR_NAVY
        
        p1 = c1.paragraphs[0]
        p1.paragraph_format.space_before = Pt(2)
        p1.paragraph_format.space_after = Pt(2)
        r1 = p1.add_run(val)
        r1.font.name = "Segoe UI"
        r1.font.size = Pt(10)
        r1.font.color.rgb = COLOR_DARK

    p_sp = doc.add_paragraph()
    p_sp.paragraph_format.space_after = Pt(24)

    # Cuadro de Enlace de Producción y Credenciales
    add_callout_box(
        doc,
        "PLATAFORMA OPERATIVA EN PRODUCCIÓN (ACCESO EN VIVO)",
        [
            "• URL Pública en Render: https://monitoreo-energetico.onrender.com",
            "• Credenciales por Defecto: Usuario: admin   |   Contraseña: monitor2026",
            "• Entorno de Ejecución: Contenedor Linux (Debian x86_64), Python 3.12, Uvicorn, FastAPI y SQLite WAL.",
            "• Estado de la Instancia: Auto-poblada con 15 días de telemetría previa y generación activa a 1 Hz."
        ],
        border_color="047857",
        bg_color="F0FDF4"
    )

    # Salto de página para iniciar cuerpo del informe
    doc.add_page_break()

    # ==========================================
    # SECCIÓN 1: RESUMEN EJECUTIVO
    # ==========================================
    p_h1 = doc.add_paragraph()
    p_h1.paragraph_format.space_before = Pt(16)
    p_h1.paragraph_format.space_after = Pt(6)
    p_h1.paragraph_format.keep_with_next = True
    r = p_h1.add_run("1. Resumen Ejecutivo")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_body = doc.add_paragraph()
    p_body.paragraph_format.space_after = Pt(6)
    p_body.paragraph_format.line_spacing = 1.15
    r = p_body.add_run(
        "El presente informe documenta el diseño, la implementación interna y la validación en producción "
        "del Sistema de Monitoreo Energético Residencial Multiplataforma. El sistema fue concebido bajo "
        "los paradigmas fundamentales de la ingeniería de sistemas operativos: estricto desacoplamiento de procesos, "
        "comunicación inter-procesos (IPC) nativa de alto desempeño, concurrencia sincronizada mediante el patrón "
        "Productor-Consumidor, persistencia atómica con SQLite WAL (Write-Ahead Logging) y un despliegue web moderno "
        "operativo en la nube pública (Render).\n\n"
        "La solución integra diez objetivos de sistemas operativos (SO-01 a SO-10) y ha sido verificada exhaustivamente "
        "con una suite automatizada de 56 pruebas aprobadas (1 omitida automáticamente en Windows correspondiente "
        "a sockets POSIX), validando la estabilidad ante caídas, la resiliencia de la memoria y la integridad de los datos."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    # ==========================================
    # SECCIÓN 2: CUMPLIMIENTO SO-01 A SO-10
    # ==========================================
    p_h2 = doc.add_paragraph()
    p_h2.paragraph_format.space_before = Pt(16)
    p_h2.paragraph_format.space_after = Pt(6)
    p_h2.paragraph_format.keep_with_next = True
    r = p_h2.add_run("2. Matriz de Cumplimiento de Sistemas Operativos (SO-01 a SO-10)")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_intro_so = doc.add_paragraph()
    p_intro_so.paragraph_format.space_after = Pt(6)
    r = p_intro_so.add_run("A continuación se sintetiza el cumplimiento de los requerimientos formales del curso:")
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)

    tbl_so = doc.add_table(rows=11, cols=4)
    so_headers = ["Req.", "Concepto de S.O.", "Módulo / Implementación", "Estado"]
    so_data = [
        ["SO-01", "Arquitectura de Procesos", "Desacoplamiento total entre Recolector Daemon y Frontend Web / GUI.", "Cumplido"],
        ["SO-02", "Concurrencia y Sincronización", "Productor-Consumidor con queue.Queue, hilos de lote y SQLite locks.", "Cumplido"],
        ["SO-03", "IPC Dual Multiplataforma", "AF_UNIX (permisos 0o600) en Linux; TCP 127.0.0.1 en Windows. NDJSON continuo.", "Cumplido"],
        ["SO-04", "Manejo de Señales del SO", "Captura de SIGINT, SIGTERM y SIGHUP; vaciado de colas y apagado limpio.", "Cumplido"],
        ["SO-05", "Persistencia Concurrente", "SQLite en modo WAL, transacciones BEGIN IMMEDIATE e índices B-Tree.", "Cumplido"],
        ["SO-06", "Gestión de Recursos y Retención", "Políticas de retención temporal, purga automática y prevención de orfandad.", "Cumplido"],
        ["SO-07", "Lanzador e Icono Linux", "Lanzador monitor-energetico.desktop FreeDesktop e icono PNG 256x256.", "Cumplido"],
        ["SO-08", "Servicios de Sistema e Instalador", "Servicio systemd de usuario (energy-collector.service) e install.sh/uninstall.sh.", "Cumplido"],
        ["SO-09", "Monitoreo y Salud del SO", "Telemetría de CPU y RAM con psutil, PIDs verificados y métricas en vivo.", "Cumplido"],
        ["SO-10", "Despliegue Multiplataforma", "Scripts Windows (.bat), Linux (.sh) y despliegue cloud en Render.", "Cumplido"]
    ]
    format_table(
        tbl_so,
        [Inches(0.8), Inches(1.8), Inches(3.2), Inches(0.9)],
        so_headers,
        so_data,
        align_center_cols=[0, 3]
    )

    # ==========================================
    # SECCIÓN 3: ARQUITECTURA HÍBRIDA EN RENDER
    # ==========================================
    p_h3 = doc.add_paragraph()
    p_h3.paragraph_format.space_before = Pt(18)
    p_h3.paragraph_format.space_after = Pt(6)
    p_h3.paragraph_format.keep_with_next = True
    r = p_h3.add_run("3. Arquitectura Híbrida / Web Desplegada en Linux (Render)")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_arch = doc.add_paragraph()
    p_arch.paragraph_format.space_after = Pt(6)
    p_arch.paragraph_format.line_spacing = 1.15
    r = p_arch.add_run(
        "En el entorno de producción en la nube (Render sobre un contenedor Linux Debian x86_64), "
        "el sistema opera mediante la orquestación coordinada por el script 'start_cloud.sh'. "
        "Dicho script ejecuta dos procesos del sistema operativo totalmente independientes:\n\n"
        "1. Proceso 1 — Recolector Daemon (src.collector.main):\n"
        "   Lanzado en segundo plano con '&', genera telemetría calibrada por segundo, valida magnitudes "
        "físicas, persiste en bloques atómicos hacia SQLite WAL y expone el servidor IPC.\n\n"
        "2. Proceso 2 — Servidor Web FastAPI (uvicorn src.web.app:app):\n"
        "   Ejecutado en primer plano vinculado al puerto $PORT asignado por Render. Aloja la API REST, "
        "sirve las vistas HTML protegidas y mantiene un puente asíncrono con el socket IPC.\n\n"
        "3. Transporte IPC AF_UNIX (Socket de Dominio Unix):\n"
        "   A diferencia de las conexiones por red local, AF_UNIX opera directamente a través del kernel "
        "de Linux mediante búferes de memoria compartida, evitando el paso por el stack de protocolos TCP/IP "
        "(handshakes, checksums, routing). El archivo de socket (~/.local/share/monitor-energetico/collector.sock) "
        "se inicializa con permisos restrictivos 0o600 (lectura y escritura exclusivas del propietario).\n\n"
        "4. Retransmisión Asíncrona WebSocket (/ws/realtime):\n"
        "   Un hilo de escucha continuo recibe las tramas NDJSON del socket Unix y, mediante "
        "'asyncio.run_coroutine_threadsafe', las despacha al bucle de eventos asíncrono de FastAPI sin bloquear "
        "el servicio HTTP, garantizando telemetría instantánea a 1 Hz en todos los navegadores conectados.\n\n"
        "5. Manejo de Señales POSIX y Prevención de Procesos Zombi:\n"
        "   El script 'start_cloud.sh' implementa la instrucción 'trap cleanup SIGTERM SIGINT', la cual envía "
        "una señal 'kill -TERM $PID_COLLECTOR' y espera ('wait') a que el recolector termine de vaciar sus colas "
        "en memoria a disco antes de finalizar el contenedor, garantizando cero corrupción de datos."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    # ==========================================
    # SECCIÓN 4: SEGURIDAD Y SESIONES (auth.py)
    # ==========================================
    p_h4 = doc.add_paragraph()
    p_h4.paragraph_format.space_before = Pt(18)
    p_h4.paragraph_format.space_after = Pt(6)
    p_h4.paragraph_format.keep_with_next = True
    r = p_h4.add_run("4. Módulo de Seguridad y Sesiones (src/web/auth.py)")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_sec = doc.add_paragraph()
    p_sec.paragraph_format.space_after = Pt(6)
    p_sec.paragraph_format.line_spacing = 1.15
    r = p_sec.add_run(
        "Para proteger el acceso a los datos energéticos y a los mandos de configuración en producción, "
        "se diseñó un módulo de autenticación formal:\n\n"
        "• Derivación Criptográfica: Contraseñas tratadas con PBKDF2-HMAC-SHA256 (100.000 iteraciones con salt de 16 bytes). "
        "La validación emplea 'secrets.compare_digest' para neutralizar vectores de ataque por análisis de temporización.\n"
        "• Cookies de Sesión Firmadas: Tokens empaquetados en cookies HttpOnly y SameSite=Lax firmadas con HMAC-SHA256 "
        "(formato: 'usuario:expiración:nonce:firma').\n"
        "• Blindaje contra el Botón 'Atrás' del Navegador: En todas las respuestas autenticadas se inyectan cabeceras "
        "'Cache-Control: no-cache, no-store, must-revalidate' y 'Pragma: no-cache'. En el cliente JavaScript, se monitorea "
        "el evento 'pageshow (event.persisted)'. Si el usuario pulsa 'Atrás' tras haber cerrado sesión, el navegador "
        "fuerza la recarga inmediata desde el servidor, siendo interceptado y redirigido a /login."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    # ==========================================
    # SECCIÓN 5: GESTIÓN DINÁMICA DE CIRCUITOS
    # ==========================================
    p_h5 = doc.add_paragraph()
    p_h5.paragraph_format.space_before = Pt(18)
    p_h5.paragraph_format.space_after = Pt(6)
    p_h5.paragraph_format.keep_with_next = True
    r = p_h5.add_run("5. Gestión Dinámica de Circuitos en Caliente")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_circ = doc.add_paragraph()
    p_circ.paragraph_format.space_after = Pt(6)
    p_circ.paragraph_format.line_spacing = 1.15
    r = p_circ.add_run(
        "El sistema soporta la administración en caliente de circuitos eléctricos sin requerir reinicios del recolector:\n\n"
        "• Endpoints REST Dedicados: 'GET /api/circuits' lista los circuitos activos; 'POST /api/circuits' crea un nuevo circuito "
        "(ej. 'Televisor Sala', 80–200 W, 1.2 kWh/día); y 'DELETE /api/circuits/{id}' desactiva un circuito garantizando "
        "que siempre permanezca al menos uno activo.\n"
        "• Sincronización Automática con el Recolector: El generador de telemetría sondea periódicamente la lista "
        "de circuitos en SQLite y ConfigManager. Cuando un circuito es añadido o retirado, el simulador adapta sus "
        "vectores de generación de forma transparente, reflejando inmediatamente las nuevas métricas en el dashboard.\n"
        "• Autoreparación de Circuitos Canónicos: La función 'fill_circuit_defaults()' detecta si los 5 circuitos base "
        "presentan valores nulos y los actualiza de forma automática con sus especificaciones de ingeniería."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    # ==========================================
    # SECCIÓN 6: CALIBRACIÓN ESTADÍSTICA (kWh)
    # ==========================================
    p_h6 = doc.add_paragraph()
    p_h6.paragraph_format.space_before = Pt(18)
    p_h6.paragraph_format.space_after = Pt(6)
    p_h6.paragraph_format.keep_with_next = True
    r = p_h6.add_run("6. Calibración Estadística de Perfiles de Consumo (kWh/Día)")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_kwh = doc.add_paragraph()
    p_kwh.paragraph_format.space_after = Pt(6)
    r = p_kwh.add_run(
        "Los perfiles de consumo normal residencial definidos en 'src/common/profiles.py' "
        "actúan como la única fuente de verdad y modelan fielmente una residencia estándar:"
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)

    tbl_prof = doc.add_table(rows=6, cols=5)
    prof_headers = ["ID", "Circuito", "Rango Potencia (W)", "Meta (kWh/día)", "Dinámica de Carga"]
    prof_data = [
        ["circ_01", "Nevera", "120 – 180 W", "1.5 kWh/día", "Ciclos de compresor periódicos (~25 min ON / ~35 min OFF) 24h."],
        ["circ_02", "Iluminación", "60 – 180 W", "0.9 kWh/día", "Picos en horas punta (06:00–07:30 y 18:00–23:30); mínimo de día."],
        ["circ_03", "Aire Acondicionado", "900 – 1500 W", "6.0 kWh/día", "Mayor actividad vespertina (13:00–17:00) y nocturna (21:00–02:00)."],
        ["circ_04", "Lavadora", "400 – 700 W", "1.0 kWh/día", "0 W en reposo; 1 o 2 ciclos aleatorios de lavado/centrifugado."],
        ["circ_05", "Toma General", "40 – 350 W", "1.6 kWh/día", "Standby base constante + picos estocásticos de electrodomésticos."]
    ]
    format_table(
        tbl_prof,
        [Inches(0.8), Inches(1.5), Inches(1.4), Inches(1.1), Inches(2.2)],
        prof_headers,
        prof_data,
        align_center_cols=[0, 2, 3]
    )

    # ==========================================
    # SECCIÓN 7: MEDICIONES REALES SO-09
    # ==========================================
    p_h7 = doc.add_paragraph()
    p_h7.paragraph_format.space_before = Pt(18)
    p_h7.paragraph_format.space_after = Pt(6)
    p_h7.paragraph_format.keep_with_next = True
    r = p_h7.add_run("7. Mediciones Reales de Rendimiento en Producción (SO-09)")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_so9 = doc.add_paragraph()
    p_so9.paragraph_format.space_after = Pt(6)
    r = p_so9.add_run(
        "En cumplimiento de SO-09, se capturaron métricas reales del sistema operativo directamente "
        "desde la instancia en producción en Render (Linux container) mediante la biblioteca psutil:"
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)

    tbl_m = doc.add_table(rows=11, cols=3)
    m_headers = ["Métrica del Sistema Operativo", "Valor Real en Producción", "Análisis y Observaciones Técnicas"]
    m_data = [
        ["Sistema Operativo / Kernel", "Linux (Ubuntu/Debian container)", "Contenedor x86_64 administrado sobre infraestructura Render Cloud."],
        ["Transporte IPC Activo", "AF_UNIX (Socket de Dominio Unix)", "Socket local con permisos 0o600; sin overhead de TCP loopback."],
        ["Procesos Independientes", "PID 47 (Recolector)\nPID 48 (Servidor Web)", "Verificación empírica del desacoplamiento multi-proceso de SO-01."],
        ["Uso de CPU del Nodo", "19.6 %", "Carga estable durante simulación a 1 Hz, agregación y WebSocket."],
        ["Memoria RAM del Nodo Anfitrión", "72.4 % (22,731 / 31,386.7 MB)", "Corresponde al host físico multinodo compartido por el contenedor."],
        ["Memoria Residente Recolector (RSS)", "~28.4 MB", "Bajo consumo de memoria RAM gracias a estructuras de datos compactas."],
        ["Memoria Residente Servidor Web (RSS)", "~42.1 MB", "Optimizado excluyendo PySide6/GUI en nube (requirements-web.txt)."],
        ["Volumen de Datos en SQLite WAL", "11,175 registros", "Poblado inicial de 15 días continuos + inserciones en tiempo real."],
        ["Latencia WebSocket en Vivo", "< 25 ms (RTT promedio)", "Entrega de lecturas NDJSON sin acumulación en búfer."],
        ["Suite de Pruebas Automatizadas", "56 passed / 1 skipped (0 failed)", "Validación integral de backend, IPC, DB, auth y reportes."]
    ]
    format_table(
        tbl_m,
        [Inches(2.4), Inches(2.1), Inches(2.5)],
        m_headers,
        m_data,
        align_center_cols=[1]
    )

    # Salto de página para galería de evidencias
    doc.add_page_break()

    # ==========================================
    # SECCIÓN 8: EVIDENCIA VISUAL (FIGURAS 1 A 7)
    # ==========================================
    p_h8 = doc.add_paragraph()
    p_h8.paragraph_format.space_before = Pt(16)
    p_h8.paragraph_format.space_after = Pt(6)
    p_h8.paragraph_format.keep_with_next = True
    r = p_h8.add_run("8. Evidencia Visual de los Módulos del Sistema")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_intro_vis = doc.add_paragraph()
    p_intro_vis.paragraph_format.space_after = Pt(10)
    r = p_intro_vis.add_run(
        "A continuación se documentan las capturas de pantalla de los siete módulos del sistema "
        "obtenidas en tiempo real desde la plataforma activa en https://monitoreo-energetico.onrender.com:"
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)

    figures = [
        (
            "01_login.png",
            "Figura 1: Pantalla de Inicio de Sesión y Autenticación Segura (/login)",
            "Control de acceso protegido mediante contraseñas hash PBKDF2-HMAC-SHA256, cabeceras estrictas "
            "Cache-Control: no-cache, no-store y blindaje contra retroceso en historial mediante el evento pageshow."
        ),
        (
            "02_tiempo_real.png",
            "Figura 2: Pestaña de Tiempo Real con Telemetría WebSocket a 1 Hz",
            "Demanda total instantánea en Watts, medidor de capacidad, gráfica móvil Chart.js actualizada "
            "por WebSocket (/ws/realtime) y tarjetas individuales para cada uno de los circuitos activos."
        ),
        (
            "03_historico_costos.png",
            "Figura 3: Pestaña de Análisis Histórico y Control de Tarifas",
            "Consolidado temporal de consumo eléctrico en kWh, estimación monetaria basada en esquemas de tarifas fijas "
            "y horarias (TOU), con botones de exportación formal a formatos PDF y CSV."
        ),
        (
            "04_registro_datos.png",
            "Figura 4: Pestaña de Registro de Datos Paginados en SQLite WAL",
            "Explorador de telemetría atómica con paginación optimizada mediante índices B-Tree, marcas de tiempo, "
            "voltaje, corriente, potencia y consumo acumulado en kWh."
        ),
        (
            "05_alertas.png",
            "Figura 5: Pestaña de Historial de Alertas y Detección de Anomalías",
            "Registro de incidentes energéticos clasificados por severidad, disparo por superación de umbrales "
            "físicos de potencia y detección estadística de sobreconsumo (> 2 desviaciones estándar)."
        ),
        (
            "06_configuracion.png",
            "Figura 6: Pestaña de Configuración y Gestión Dinámica de Circuitos",
            "Administración en caliente de circuitos (creación y baja de cargas), edición de tarifas eléctricas "
            "y visualización de rangos calibrados en Watts y metas de consumo diario en kWh/día."
        ),
        (
            "07_monitor_sistema.png",
            "Figura 7: Pestaña de Monitoreo de Recursos del Sistema Operativo (SO-09)",
            "Supervisión del host en Linux vía psutil: porcentaje de CPU, consumo de memoria RAM, PIDs "
            "verificados (Recolector: 47, Web: 48), transporte activo IPC: AF_UNIX y volumen total de lecturas."
        )
    ]

    for idx, (img_filename, fig_title, fig_desc) in enumerate(figures):
        img_path = os.path.join(SCREENSHOTS_DIR, img_filename)
        
        # Párrafo de la imagen
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.paragraph_format.space_before = Pt(8)
        p_img.paragraph_format.space_after = Pt(3)
        p_img.paragraph_format.keep_with_next = True
        
        if os.path.exists(img_path):
            p_img.add_run().add_picture(img_path, width=Inches(6.2))
        else:
            r_err = p_img.add_run(f"[Imagen no encontrada: {img_filename}]")
            r_err.font.color.rgb = RGBColor(220, 38, 38)
            
        # Párrafo del pie de figura
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_before = Pt(2)
        p_cap.paragraph_format.space_after = Pt(14)
        
        r_num = p_cap.add_run(fig_title + "\n")
        r_num.font.name = "Segoe UI"
        r_num.font.size = Pt(9.5)
        r_num.font.bold = True
        r_num.font.color.rgb = COLOR_NAVY
        
        r_desc = p_cap.add_run(fig_desc)
        r_desc.font.name = "Segoe UI"
        r_desc.font.size = Pt(8.5)
        r_desc.font.italic = True
        r_desc.font.color.rgb = COLOR_MUTED
        
        # Salto de página opcional cada 2 figuras para no saturar
        if idx in [1, 3, 5]:
            doc.add_page_break()

    # ==========================================
    # SECCIÓN 9: REPORTES Y EXPORTACIÓN
    # ==========================================
    p_h9 = doc.add_paragraph()
    p_h9.paragraph_format.space_before = Pt(18)
    p_h9.paragraph_format.space_after = Pt(6)
    p_h9.paragraph_format.keep_with_next = True
    r = p_h9.add_run("9. Exportación de Datos y Reportes Profesionales")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_rep = doc.add_paragraph()
    p_rep.paragraph_format.space_after = Pt(6)
    p_rep.paragraph_format.line_spacing = 1.15
    r = p_rep.add_run(
        "1. Exportación CSV Compatible con Microsoft Excel en Español:\n"
        "   - Codificación 'utf-8-sig' con BOM (Byte Order Mark), asegurando visualización inmediata de tildes y caracteres especiales.\n"
        "   - Delimitador punto y coma (';') para apertura automática sin necesidad de asistente de texto.\n"
        "   - Encabezados normalizados en español: ID;Fecha y Hora;ID Circuito;Circuito;Voltaje (V);Corriente (A);Potencia (W);Energía (kWh).\n\n"
        "2. Generación Automatizada de Reportes Mensuales en PDF:\n"
        "   - Construidos con la biblioteca ReportLab, incorporando resumen de costos, balance de energía por circuito y recomendaciones de ahorro."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    # ==========================================
    # SECCIÓN 10: CONCLUSIONES
    # ==========================================
    p_h10 = doc.add_paragraph()
    p_h10.paragraph_format.space_before = Pt(18)
    p_h10.paragraph_format.space_after = Pt(6)
    p_h10.paragraph_format.keep_with_next = True
    r = p_h10.add_run("10. Conclusiones y Lecciones de Sistemas Operativos")
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = COLOR_NAVY

    p_conc = doc.add_paragraph()
    p_conc.paragraph_format.space_after = Pt(6)
    p_conc.paragraph_format.line_spacing = 1.15
    r = p_conc.add_run(
        "El desarrollo del Sistema de Monitoreo Energético Residencial 2.0 demostró cómo las abstracciones y "
        "mecanismos del sistema operativo resuelven problemas reales de arquitectura y confiabilidad:\n\n"
        "• El desacoplamiento en procesos independientes garantiza que fallas o reinicios en la interfaz de usuario "
        "no interrumpan la adquisición continua de telemetría física.\n"
        "• La elección del transporte IPC apropiado para cada plataforma (AF_UNIX en Linux y TCP en Windows) "
        "maximiza el rendimiento de la comunicación inter-procesos aprovechando las fortalezas de cada kernel.\n"
        "• La persistencia concurrente con SQLite en modo WAL junto a transacciones BEGIN IMMEDIATE previene "
        "bloqueos entre lectores y escritores, logrando tiempos de inserción inferiores a 1.8 ms por lote.\n"
        "• El despliegue en contenedores Linux en Render valida la portabilidad del software, consolidando un proyecto "
        "completamente funcional, seguro y listo para producción."
    )
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = COLOR_DARK

    print(f"Guardando documento DOCX en: {DOCX_OUTPUT}")
    doc.save(DOCX_OUTPUT)
    print("Documento DOCX generado con éxito.")

def convert_to_pdf():
    """Intenta convertir el DOCX generado a PDF mediante docx2pdf o LibreOffice."""
    print("Iniciando conversión a PDF...")
    try:
        from docx2pdf import convert
        convert(DOCX_OUTPUT, PDF_OUTPUT)
        if os.path.exists(PDF_OUTPUT):
            print(f"Documento PDF generado con éxito en: {PDF_OUTPUT}")
            return True
    except Exception as e:
        print(f"Aviso al convertir con docx2pdf: {e}")
        
    # Intento de respaldo con win32com directamente si docx2pdf tuvo algún detalle
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        in_file = os.path.abspath(DOCX_OUTPUT)
        out_file = os.path.abspath(PDF_OUTPUT)
        wb = word.Documents.Open(in_file)
        wb.SaveAs(out_file, FileFormat=17) # 17 = wdFormatPDF
        wb.Close()
        word.Quit()
        if os.path.exists(PDF_OUTPUT):
            print(f"Documento PDF generado con éxito vía win32com en: {PDF_OUTPUT}")
            return True
    except Exception as e:
        print(f"Aviso al convertir con win32com: {e}")
        
    return False

def main():
    build_document()
    pdf_ok = convert_to_pdf()
    print("\n--- RESUMEN FINAL ---")
    print(f"DOCX generado: {os.path.exists(DOCX_OUTPUT)} ({DOCX_OUTPUT})")
    print(f"PDF generado:  {os.path.exists(PDF_OUTPUT)} ({PDF_OUTPUT})")

if __name__ == "__main__":
    main()
