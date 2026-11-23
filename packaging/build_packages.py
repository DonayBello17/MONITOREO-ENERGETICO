"""Script de automatización de compilación y empaquetado multiplataforma.

Permite verificar dependencias, ejecutar PyInstaller según packaging/pyinstaller.spec
y generar distribuciones listas para Windows y Linux.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def check_dependencies() -> bool:
    """Verifica que PyInstaller y las dependencias principales estén instaladas."""
    print("Verificando dependencias de empaquetado...")
    try:
        import PyInstaller
        import PySide6
        import pyqtgraph
        import reportlab
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
        print(f"[OK] PySide6 {PySide6.__version__}")
        print(f"[OK] PyQtGraph {pyqtgraph.__version__}")
        print(f"[OK] ReportLab {reportlab.__version__}")
        return True
    except ImportError as exc:
        print(f"[ERROR] Dependencia faltante: {exc}")
        return False


def build_binaries() -> bool:
    """Invoca PyInstaller usando packaging/pyinstaller.spec."""
    spec_path = ROOT_DIR / "packaging" / "pyinstaller.spec"
    if not spec_path.exists():
        print(f"[ERROR] Archivo spec no encontrado: {spec_path}")
        return False

    print(f"Iniciando compilación con PyInstaller: {spec_path}...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT_DIR))
    return result.returncode == 0


def main() -> int:
    print("==================================================")
    print(" Empaquetador del Sistema de Monitoreo Energético ")
    print("==================================================")

    if not check_dependencies():
        print("Instale PyInstaller con: pip install pyinstaller")
        return 1

    success = build_binaries()
    if success:
        print("\n[ÉXITO] Ejecutables generados en la carpeta 'dist/'")
    else:
        print("\n[ERROR] Falló la compilación con PyInstaller.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
