"""Punto de entrada ejecutable del Dashboard de Monitoreo Energético.

Inicia la aplicación Qt, aplica el tema visual por defecto y despliega la ventana principal visible en pantalla.
Ejecución: `python -m src.dashboard.main`
"""

from __future__ import annotations

import logging
import os
import signal
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from src.common.logger import setup_logger
from src.dashboard.theme import apply_theme
from src.dashboard.ui.main_window import MainWindow

logger = logging.getLogger("dashboard")


def main() -> int:
    """Función principal de inicio del dashboard de escritorio."""
    # Eliminar cualquier configuración residual de 'offscreen' del entorno del shell (ej. de sesiones previas de prueba)
    if "--offscreen" not in sys.argv and "--headless" not in sys.argv:
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            os.environ.pop("QT_QPA_PLATFORM", None)

    setup_logger("dashboard")
    logger.info("Iniciando Dashboard de Monitoreo Energético...")

    # Permitir interrupción por Ctrl+C en consola
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    try:
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("MonitorEnergetico")
    app.setOrganizationName("MonitorEnergetico")
    app.setQuitOnLastWindowClosed(True)

    # Aplicar tema oscuro por defecto
    apply_theme(app, is_dark=True)

    window = MainWindow()

    # Garantizar que la ventana se despliegue visible en pantalla y en la barra de tareas
    window.showNormal()
    window.show()
    window.raise_()
    window.activateWindow()

    logger.info(
        "Ventana principal desplegada correctamente (visible=%s, estado=%s).",
        window.isVisible(),
        window.windowState(),
    )
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
