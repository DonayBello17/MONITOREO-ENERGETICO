# Sistema de Monitoreo Energético para Vivienda

Sistema modular de grado industrial y multiplataforma (Windows y Linux) para el monitoreo, análisis en tiempo real, detección de anomalías y control de costos del consumo eléctrico residencial.

Diseñado bajo una arquitectura desacoplada de dos procesos independientes:
1. **Recolector en segundo plano (Daemon / Backend)**: Captura telemetría de circuitos eléctricos, valida integridad física, persiste en SQLite con soporte WAL y transmite eventos en tiempo real mediante un servidor IPC dual (Socket de dominio Unix `AF_UNIX` con permisos `0o600` en Linux/POSIX y TCP local `127.0.0.1:50555` en Windows) en formato NDJSON.
2. **Dashboard de escritorio (Frontend)**: Aplicación gráfica moderna construida con PySide6 y PyQtGraph, con soporte de temas claro/oscuro, análisis histórico y de costos, detección de anomalías ($>2\sigma$), generación de reportes mensuales en PDF con ReportLab, exportación/importación masiva CSV/JSON y monitoreo de salud del sistema.

---

## 📁 Estructura del Proyecto

```text
MONITOREO/
├── config/
│   └── default_config.json        # Configuración inicial de tarifas, circuitos y retención
├── packaging/
│   ├── assets/
│   │   └── monitor-energetico.png # Icono oficial en alta resolución (256x256 PNG)
│   ├── pyinstaller.spec           # Especificación PyInstaller para binarios independientes
│   ├── build_packages.py          # Script de empaquetado automatizado
│   ├── windows/
│   │   ├── start_collector.bat    # Script de inicio del recolector en Windows
│   │   ├── start_dashboard.bat    # Script de inicio del dashboard en Windows
│   │   └── install_service.bat    # Registro como tarea programada de inicio
│   └── linux/
│       ├── energy-collector.service   # Unidad de servicio systemd para Linux
│       ├── monitor-energetico.desktop # Lanzador FreeDesktop para menú de aplicaciones
│       ├── install.sh             # Script de instalación integral para Linux
│       ├── uninstall.sh           # Script de desinstalación limpia y purga opcional
│       ├── start_collector.sh     # Script de inicio para Linux / macOS
│       └── start_dashboard.sh     # Lanzador del dashboard para Linux / macOS
├── samples/
│   ├── lecturas_ejemplo.csv       # Muestra de telemetría para pruebas de importación
│   └── lecturas_ejemplo.json      # Muestra en formato JSON
├── src/
│   ├── common/                    # Núcleo compartido
│   │   ├── config_manager.py      # Gestor de configuración multihilo con recarga en caliente
│   │   ├── database.py            # SQLite WAL con agregaciones e índices optimizados
│   │   ├── logger.py              # Logging rotativo (RotatingFileHandler) y consola
│   │   ├── models.py              # Dataclasses de Circuit, Reading, Alert, AggregateReading
│   │   └── paths.py               # Rutas nativas XDG/AppData y permisos seguros (0o600/0o700)
│   ├── collector/                 # Proceso 1: Recolector en segundo plano
│   │   ├── main.py                # Entrada ejecutable (patrón Productor-Consumidor con Queue)
│   │   ├── simulator.py           # Simulador de telemetría con perfiles de carga domiciliarios
│   │   ├── validator.py           # Validador de rangos físicos y duplicados (ReadingValidator)
│   │   ├── ipc_server.py          # Servidor IPC dual multiplataforma (AF_UNIX en Linux, TCP en Windows)
│   │   └── aggregator.py          # Hilo programado de agregaciones y retención periódica
│   └── dashboard/                 # Proceso 2: Dashboard de escritorio
│       ├── main.py                # Punto de entrada ejecutable de la interfaz gráfica
│       ├── ipc_client.py          # Cliente IPC dual en QThread con reconexión automática continua
│       ├── cost_calculator.py     # Motor de cálculo de tarifas fijas, horarias (TOU) y por tramos
│       ├── anomaly_detector.py    # Detección de anomalías estadísticas (> 2 desviaciones estándar)
│       ├── theme.py               # Gestor de estilos CSS y temas Claro y Oscuro
│       ├── reports/               # Módulo de reportes y exportación
│       │   ├── exporter.py        # Exportación CSV, capturas PNG e importación CSV/JSON
│       │   └── pdf_report.py      # Generador de reportes mensuales en PDF con ReportLab
│       └── ui/                    # Pestañas y componentes visuales PySide6
│           ├── main_window.py     # Ventana principal, bandeja del sistema y barra de estado
│           ├── realtime_tab.py    # Medidor de potencia, gráfico móvil 1Hz y tarjetas de circuito
│           ├── history_tab.py     # Gráficos históricos, KPIs, costos y botones de reporte
│           ├── alerts_tab.py      # Control de umbrales, historial de eventos y anomalías
│           ├── config_tab.py      # CRUD de circuitos y edición de tarifas
│           └── monitor_tab.py     # Monitoreo de CPU y RAM del recolector con psutil
├── tests/
│   ├── test_config.py             # Pruebas de modelos, configuración y permisos
│   ├── test_database.py           # Pruebas unitarias de persistencia, CRUD y agregaciones
│   ├── test_validator.py          # Pruebas del validador de telemetría y duplicados
│   ├── test_simulator.py          # Pruebas del simulador y perfiles de carga
│   ├── test_ipc_server.py         # Pruebas del servidor TCP NDJSON y desconexión abrupta
│   ├── test_aggregator.py         # Pruebas del hilo de agregación y disparo manual
│   ├── test_collector_main.py     # Pruebas de integración del productor-consumidor y backoff
│   ├── test_costs.py              # Pruebas de tarifas (fija, TOU, tramos) y anomalías
│   ├── test_dashboard_ui.py       # Pruebas de inicialización de la UI y cambio de temas
│   ├── test_reports.py            # Pruebas de exportación/importación y generación de PDF
│   └── test_volume.py             # Prueba de estrés masivo (1.000.000 de lecturas en SQLite)
├── requirements.txt               # Dependencias del proyecto
└── README.md                      # Documentación integral
```

---

## 🚀 Instalación y Puesta en Marcha

### 1. Requisitos
- **Python 3.10 o superior**.
- Sistemas operativos compatibles: **Windows 10/11** y **Linux** (Ubuntu, Debian, Fedora, Arch, etc.).

### 2. Configuración del Entorno Virtual

#### En Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### En Linux (Bash):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 💻 Ejecución de los Procesos y Comunicación IPC (SO-03)

El sistema se ejecuta en dos procesos completamente desacoplados con transporte IPC dual y seguro:

* **En Linux / POSIX**: Utiliza un **socket de dominio Unix (`socket.AF_UNIX`)** ubicado en `$XDG_RUNTIME_DIR/monitor-energetico.sock` (o `~/.local/share/monitor-energetico/collector.sock`), aplicando permisos restrictivos `0o600` y limpiando cualquier socket previo huérfano al iniciar.
* **En Windows**: Mantiene el socket **TCP local en `127.0.0.1:50555`**.
* **Protocolo**: En ambas plataformas se emplea exactamente el mismo flujo de datos **NDJSON** (JSON delimitado por `\n`), con hilo de escucha asíncrono y reconexión continua en el Dashboard.
* **Logs**: Ambos procesos registran explícitamente en el log qué transporte IPC se activó (`AF_UNIX` o `TCP`).

### Proceso 1: Recolector en Segundo Plano (Backend)
```bash
python -m src.collector.main
```
- Lee lecturas de los circuitos cada N segundos.
- Valida los datos y los encola en memoria (patrón Productor-Consumidor).
- Persiste lotes en SQLite con WAL mode.
- Transmite telemetría en vivo vía NDJSON por el socket IPC activo.
- Maneja señales de apagado limpio (`SIGINT`, `SIGTERM`), vaciando la cola sin pérdida de datos.

### Proceso 2: Dashboard de Escritorio (Frontend)
```bash
python -m src.dashboard.main
```
- Conecta automáticamente al socket IPC del recolector (con reintento automático si no está activo aún).
- Muestra la potencia total y tarjetas de circuito en tiempo real.
- Permite alternar entre **Tema Claro** y **Tema Oscuro**.
- Consulta históricos, KPIs y costos en segundo plano.
- Exporta a CSV, genera **Reportes en PDF** y toma capturas de pantalla PNG.
- Emite notificaciones nativas en la bandeja de sistema ante anomalías.

---

## 🧪 Pruebas Automatizadas

Para ejecutar la suite completa de pruebas unitarias, de integración, IPC y resiliencia:

```bash
pytest
```

Para ver el detalle de cada prueba individual:
```bash
pytest -v
```

### Prueba de Estrés y Volumen (1.000.000 de Lecturas)
El archivo `tests/test_volume.py` valida la inserción de **1.000.000 de lecturas** en lotes atómicos y mide la velocidad de consulta indexada:
- **Tasa de inserción**: > 250.000 lecturas/segundo.
- **Consulta indexada**: < 10 ms para rangos entre un millón de registros.

---

## 📦 Empaquetado y Despliegue

### Instalación y Desinstalación en Linux (SO-07 y SO-08)

El directorio `packaging/linux/` provee scripts listos para producción con saltos de línea LF:

#### Instalación Integral en Linux:
```bash
chmod +x packaging/linux/install.sh
./packaging/linux/install.sh
```
El script automatiza los siguientes pasos:
1. Valida la presencia de Python 3 (versión 3.9 o superior).
2. Crea el entorno virtual `.venv` e instala las dependencias de `requirements.txt`.
3. Instala el icono oficial (256x256 PNG) en `~/.local/share/icons/hicolor/256x256/apps/monitor-energetico.png`.
4. Copia `monitor-energetico.desktop` en `~/.local/share/applications/` resolviendo las rutas absolutas reales (`Exec` e `Icon`).
5. Copia la unidad de servicio `energy-collector.service` en `~/.config/systemd/user/` y ejecuta:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now energy-collector.service
   ```

#### Desinstalación Limpia en Linux:
```bash
chmod +x packaging/linux/uninstall.sh
./packaging/linux/uninstall.sh
```
O para eliminar permanentemente datos de telemetría y configuración en modo desatendido:
```bash
./packaging/linux/uninstall.sh --purge
```
El script:
1. Detiene y deshabilita `energy-collector.service`.
2. Elimina la unidad systemd de usuario, el lanzador `.desktop` y el icono.
3. Pregunta interactivamente al usuario si desea conservar o eliminar la base de datos y logs en `~/.local/share/monitor-energetico` y la configuración en `~/.config/monitor-energetico`.

### Compilación con PyInstaller
Para generar ejecutables autónomos (`dist/energy-collector` y `dist/energy-dashboard`):
```bash
python packaging/build_packages.py
```

### Despliegue en Windows
Ejecutar `packaging\windows\install_service.bat` como Administrador para registrar el recolector como una tarea programada que inicia automáticamente al iniciar sesión.
