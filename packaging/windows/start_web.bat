@echo off
REM ==============================================================
REM Script de inicio del Servidor Web FastAPI para Windows
REM ==============================================================
title Monitor Energetico - Servidor Web
cd /d "%~dp0..\.."

echo ===================================================
echo Iniciando Servidor Web FastAPI en http://127.0.0.1:8000
echo ===================================================

REM Abrir navegador predeterminado tras 2 segundos en segundo plano
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

if exist ".venv\Scripts\python.exe" (
    echo Usando entorno virtual .venv...
    ".venv\Scripts\python.exe" -m uvicorn src.web.app:app --host 127.0.0.1 --port 8000 --reload
) else (
    echo Usando Python global...
    python -m uvicorn src.web.app:app --host 127.0.0.1 --port 8000 --reload
)
pause
