@echo off
REM ==============================================================
REM Registro del Recolector como Tarea Programada de Inicio en Windows
REM ==============================================================
echo Registrando el Recolector Energetico como tarea automatica...

set TASK_NAME=MonitorEnergeticoCollector
set SCRIPT_PATH=%~dp0start_collector.bat

schtasks /create /tn "%TASK_NAME%" /tr "\"%SCRIPT_PATH%\"" /sc onlogon /rl highest /f

if %errorlevel% equ 0 (
    echo [OK] Tarea programada '%TASK_NAME%' registrada con exito.
    echo El recolector se ejecutara automaticamente al iniciar sesion.
) else (
    echo [ERROR] No se pudo crear la tarea programada. Ejecute como Administrador.
)

pause
