#!/usr/bin/env bash
# ==============================================================================
# Script de desinstalación para Linux (Monitor Energético Residencial)
# Detiene el servicio, elimina unidades systemd, lanzador .desktop, iconos
# y ofrece limpiar o conservar datos y configuraciones del usuario.
# ==============================================================================
set -euo pipefail

# Colores informativos
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== Desinstalación de Monitor Energético Residencial ===${NC}"

# 1. Detener y deshabilitar el servicio systemd de usuario
if command -v systemctl &>/dev/null; then
    echo -e "${BLUE}[INFO] Deteniendo y deshabilitando servicio energy-collector.service...${NC}"
    systemctl --user stop energy-collector.service 2>/dev/null || true
    systemctl --user disable energy-collector.service 2>/dev/null || true
fi

# Eliminar archivo de unidad de servicio
SERVICE_FILE="$HOME/.config/systemd/user/energy-collector.service"
if [ -f "$SERVICE_FILE" ]; then
    rm -f "$SERVICE_FILE"
    echo -e "${GREEN}[OK] Archivo de servicio eliminado: $SERVICE_FILE${NC}"
    if command -v systemctl &>/dev/null; then
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user reset-failed 2>/dev/null || true
    fi
fi

# 2. Eliminar lanzador de escritorio
DESKTOP_FILE="$HOME/.local/share/applications/monitor-energetico.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    echo -e "${GREEN}[OK] Lanzador eliminado: $DESKTOP_FILE${NC}"
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
fi

# 3. Eliminar icono instalado
ICON_FILE="$HOME/.local/share/icons/hicolor/256x256/apps/monitor-energetico.png"
if [ -f "$ICON_FILE" ]; then
    rm -f "$ICON_FILE"
    echo -e "${GREEN}[OK] Icono eliminado: $ICON_FILE${NC}"
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi
fi

# 4. Eliminar directorio de aplicación instalada si existe
APP_DIR="$HOME/.local/share/monitor-energetico/app"
if [ -d "$APP_DIR" ]; then
    echo -e "${BLUE}[INFO] Eliminando archivos de aplicación en $APP_DIR...${NC}"
    rm -rf "$APP_DIR"
    echo -e "${GREEN}[OK] Archivos de aplicación eliminados.${NC}"
fi

# 5. Preguntar al usuario si desea conservar o eliminar datos y logs
DATA_DIR="$HOME/.local/share/monitor-energetico"
CONFIG_DIR="$HOME/.config/monitor-energetico"

DELETE_DATA=false
if [ "${1:-}" = "--purge" ] || [ "${1:-}" = "-y" ]; then
    DELETE_DATA=true
elif [ "${1:-}" = "--keep-data" ]; then
    DELETE_DATA=false
else
    # Modo interactivo
    if [ -t 0 ]; then
        echo -e "\n${YELLOW}¿Desea conservar sus bases de datos históricas, alertas y configuraciones?${NC}"
        echo -e "Rutas: $DATA_DIR y $CONFIG_DIR"
        read -r -p "¿Eliminar permanentemente todos los datos y logs? (s/N): " response
        case "$response" in
            [sS][iI]|[sS]|[yY][eE][sS]|[yY])
                DELETE_DATA=true
                ;;
            *)
                DELETE_DATA=false
                ;;
        esac
    else
        echo -e "${BLUE}[INFO] Sesión no interactiva detectada: conservando datos y configuraciones por defecto.${NC}"
    fi
fi

if [ "$DELETE_DATA" = true ]; then
    echo -e "${YELLOW}[INFO] Eliminando datos, base de datos y configuraciones...${NC}"
    rm -rf "$DATA_DIR" "$CONFIG_DIR"
    echo -e "${GREEN}[OK] Directorios $DATA_DIR y $CONFIG_DIR eliminados.${NC}"
else
    echo -e "${GREEN}[INFO] Datos conservados en $DATA_DIR y $CONFIG_DIR.${NC}"
fi

echo -e "\n${GREEN}=== Desinstalación completada con éxito ===${NC}"
