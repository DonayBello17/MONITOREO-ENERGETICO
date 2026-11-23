"""Gestión de rutas del sistema y permisos de archivos multiplataforma.

Maneja directorios de configuración, almacenamiento de datos y registros (logs)
respetando los estándares de cada sistema operativo (XDG en Linux y AppData en Windows).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    import platformdirs
except ImportError:  # pragma: no cover
    platformdirs = None

logger = logging.getLogger(__name__)

APP_NAME = "monitor-energetico"
APP_AUTHOR = "MonitorEnergetico"


def _is_posix() -> bool:
    """Verifica si el sistema operativo actual es POSIX (Linux, macOS)."""
    return os.name == "posix"


def apply_secure_permissions(path: Path, is_directory: bool = False) -> bool:
    """Aplica permisos restrictivos en sistemas POSIX.

    Directorios: 0o700 (rwx------)
    Archivos: 0o600 (rw-------)

    En Windows, la función no altera los permisos pero no genera error.

    Args:
        path: Ruta del archivo o directorio a proteger.
        is_directory: True si es directorio, False si es archivo.

    Returns:
        bool: True si los permisos se aplicaron correctamente o si estamos en Windows.
              False si ocurrió un error al aplicar permisos o si el archivo no existe.
    """
    if not _is_posix():
        return True

    try:
        path_obj = Path(path)
        if not path_obj.exists():
            return False

        mode = 0o700 if is_directory else 0o600
        os.chmod(path_obj, mode)
        return True
    except (PermissionError, OSError) as exc:
        logger.warning(
            "No se pudieron asignar permisos restrictivos a %s: %s", path, exc
        )
        return False
    except Exception as exc:
        logger.warning(
            "Error inesperado al asignar permisos a %s: %s", path, exc
        )
        return False


def ensure_directory(path: Path) -> Path:
    """Asegura que un directorio exista, creándolo si es necesario con permisos seguros.

    Si falla por permisos o disco, intenta crear una ruta temporal de respaldo
    para evitar cierres abruptos del programa.

    Args:
        path: Directorio objetivo.

    Returns:
        Path: El directorio asegurado (o directorio temporal de respaldo si falla).
    """
    try:
        path_obj = Path(path)
        path_obj.mkdir(parents=True, exist_ok=True)
        apply_secure_permissions(path_obj, is_directory=True)
        return path_obj
    except (PermissionError, OSError) as exc:
        logger.error(
            "Error al crear directorio principal '%s': %s. Usando directorio de respaldo temporal.",
            path,
            exc,
        )
        try:
            fallback = Path.home() / f".{APP_NAME}_fallback"
            fallback.mkdir(parents=True, exist_ok=True)
            apply_secure_permissions(fallback, is_directory=True)
            return fallback
        except Exception as fallback_exc:
            logger.critical(
                "Fallo crítico: No se pudo crear ni el directorio de respaldo: %s",
                fallback_exc,
            )
            return Path(path)
    except Exception as exc:
        logger.error("Error inesperado en ensure_directory para '%s': %s", path, exc)
        return Path(path)


def get_config_dir() -> Path:
    """Obtiene el directorio de configuración del usuario.

    Linux: ~/.config/monitor-energetico
    Windows: %LOCALAPPDATA%/monitor-energetico/config o Roaming
    """
    base = None
    if platformdirs:
        try:
            base = Path(platformdirs.user_config_dir(appname=APP_NAME, appauthor=False))
        except Exception:
            base = None

    if base is None:
        if _is_posix():
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            base = Path(xdg_config) / APP_NAME if xdg_config else Path.home() / ".config" / APP_NAME
        else:
            appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            base = Path(appdata) / APP_NAME if appdata else Path.home() / f".{APP_NAME}"

    return ensure_directory(base)


def get_data_dir() -> Path:
    """Obtiene el directorio de almacenamiento de datos del usuario.

    Linux: ~/.local/share/monitor-energetico
    Windows: %LOCALAPPDATA%/monitor-energetico
    """
    base = None
    if platformdirs:
        try:
            base = Path(platformdirs.user_data_dir(appname=APP_NAME, appauthor=False))
        except Exception:
            base = None

    if base is None:
        if _is_posix():
            xdg_data = os.environ.get("XDG_DATA_HOME")
            base = Path(xdg_data) / APP_NAME if xdg_data else Path.home() / ".local" / "share" / APP_NAME
        else:
            local_appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            base = Path(local_appdata) / APP_NAME if local_appdata else Path.home() / f".{APP_NAME}"

    return ensure_directory(base)


def get_config_file_path() -> Path:
    """Ruta al archivo de configuración del usuario."""
    return get_config_dir() / "config.json"


def get_database_path() -> Path:
    """Ruta al archivo SQLite principal de la base de datos."""
    return get_data_dir() / "energy_monitor.db"


def get_log_file_path() -> Path:
    """Ruta al archivo de registro (log) de la aplicación."""
    return get_data_dir() / "energy_monitor.log"


def get_socket_path() -> Path:
    """Obtiene la ruta para el socket de dominio Unix en sistemas POSIX.

    Prioriza $XDG_RUNTIME_DIR si está definido y es un directorio válido,
    de lo contrario utiliza el directorio de datos del usuario (~/.local/share/monitor-energetico/collector.sock).
    """
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        try:
            runtime_dir = Path(xdg_runtime)
            if runtime_dir.is_dir():
                return runtime_dir / f"{APP_NAME}.sock"
        except (OSError, ValueError):
            pass
    return get_data_dir() / "collector.sock"


def get_default_config_template_path() -> Path:
    """Ruta a la plantilla de configuración por defecto incluida en el proyecto."""
    # Busca relativo a este archivo (src/common/paths.py -> ../../config/default_config.json)
    base_dir = Path(__file__).resolve().parent.parent.parent
    return base_dir / "config" / "default_config.json"
