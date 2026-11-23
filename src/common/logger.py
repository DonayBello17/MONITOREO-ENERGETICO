"""Configuración centralizada de logging para el Sistema de Monitoreo Energético.

Provee salida simultánea por consola y por archivo rotativo (RotatingFileHandler),
asegurando que los logs se almacenen en el directorio de datos del usuario con permisos seguros.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from src.common.paths import apply_secure_permissions, get_log_file_path

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "monitor_energetico",
    log_file: Optional[Path] = None,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB por archivo
    backup_count: int = 5,
) -> logging.Logger:
    """Configura y retorna un logger con salida a consola y archivo rotativo.

    Args:
        name: Nombre del logger.
        log_file: Ruta del archivo de registro. Si es None, usa get_log_file_path().
        level: Nivel base de logging (INFO por defecto).
        max_bytes: Tamaño máximo antes de rotar el archivo.
        backup_count: Número de copias rotadas a conservar.

    Returns:
        logging.Logger: Instancia del logger configurado.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Evitar añadir manejadores duplicados si se llama varias veces
    if logger.handlers:
        return logger

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    # 1. Manejador de Consola (Stdout/Stderr)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. Manejador de Archivo Rotativo
    target_log_file = log_file or get_log_file_path()
    try:
        # Asegurar directorio padre
        target_log_file.parent.mkdir(parents=True, exist_ok=True)
        apply_secure_permissions(target_log_file.parent, is_directory=True)

        file_handler = RotatingFileHandler(
            filename=str(target_log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Aplicar permisos 0o600 en POSIX al archivo si existe
        if target_log_file.exists():
            apply_secure_permissions(target_log_file, is_directory=False)

    except (OSError, PermissionError) as exc:
        logger.warning(
            "No se pudo inicializar RotatingFileHandler en '%s': %s. Se continuará solo con salida a consola.",
            target_log_file,
            exc,
        )

    return logger
