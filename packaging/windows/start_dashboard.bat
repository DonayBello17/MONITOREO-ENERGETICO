@echo off
REM ==============================================================
REM Script de inicio del Dashboard de Escritorio para Windows
REM ==============================================================
title Monitor Energetico - Dashboard
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    echo Iniciando Dashboard con entorno virtual...
    start "" ".venv\Scripts\python.exe" -m src.dashboard.main
) else (
    echo Iniciando Dashboard con Python global...
    start "" python -m src.dashboard.main
)
