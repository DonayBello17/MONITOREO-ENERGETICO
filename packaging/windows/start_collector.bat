@echo off
REM ==============================================================
REM Script de inicio del Recolector Energético para Windows
REM ==============================================================
title Monitor Energetico - Recolector en Segundo Plano
cd /d "%~dp0..\.."

if exist ".venv\Scripts\python.exe" (
    echo Iniciando recolector con entorno virtual...
    ".venv\Scripts\python.exe" -m src.collector.main
) else (
    echo Iniciando recolector con Python global...
    python -m src.collector.main
)

pause
