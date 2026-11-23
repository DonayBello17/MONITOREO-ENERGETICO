# -*- mode: python ; coding: utf-8 -*-
"""Especificación de compilación con PyInstaller para Windows y Linux.

Genera ejecutables independientes para:
1. energy-collector: Proceso recolector en segundo plano (daemon/servicio).
2. energy-dashboard: Interfaz gráfica de usuario en PySide6 y PyQtGraph.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Datos y configuraciones del proyecto a incluir
datas = [
    ('config/default_config.json', 'config'),
    ('samples/lecturas_ejemplo.csv', 'samples'),
    ('samples/lecturas_ejemplo.json', 'samples'),
]

hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'pyqtgraph',
    'reportlab',
    'psutil',
    'platformdirs',
    'sqlite3',
]

# 1. Recolector en segundo plano (Console application)
a_collector = Analysis(
    ['src/collector/main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_collector = PYZ(a_collector.pure, a_collector.zipped_data, cipher=block_cipher)

exe_collector = EXE(
    pyz_collector,
    a_collector.scripts,
    a_collector.binaries,
    a_collector.zipfiles,
    a_collector.datas,
    [],
    name='energy-collector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Con consola para logs en segundo plano
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 2. Dashboard de escritorio (Windowed application)
a_dashboard = Analysis(
    ['src/dashboard/main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_dashboard = PYZ(a_dashboard.pure, a_dashboard.zipped_data, cipher=block_cipher)

exe_dashboard = EXE(
    pyz_dashboard,
    a_dashboard.scripts,
    a_dashboard.binaries,
    a_dashboard.zipfiles,
    a_dashboard.datas,
    [],
    name='energy-dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Sin ventana de consola en modo GUI
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
