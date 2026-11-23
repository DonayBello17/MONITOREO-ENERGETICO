#!/usr/bin/env bash
# ==============================================================================
# Script de instalación para Linux (Monitor Energético Residencial)
# Cumple con estándares XDG Desktop Entry, FreeDesktop Icons y systemd user units
# ==============================================================================
set -euo pipefail

# Colores informativos
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== Instalación de Monitor Energético Residencial ===${NC}"

# 1. Validar Python 3 (versión 3.9+)
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] Python 3 no está instalado o no se encuentra en el PATH.${NC}" >&2
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    echo -e "${RED}[ERROR] Se requiere Python 3.9 o superior. Versión detectada: $PY_VERSION${NC}" >&2
    exit 1
fi
echo -e "${GREEN}[OK] Python $PY_VERSION detectado.${NC}"

# Directorio raíz del proyecto origen
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Directorio de instalación (configurable mediante argumento o variable de entorno)
TARGET_DIR="${1:-$HOME/.local/share/monitor-energetico/app}"

echo -e "${BLUE}[INFO] Directorio de instalación: $TARGET_DIR${NC}"
mkdir -p "$TARGET_DIR"

# 2. Copiar archivos del proyecto si el destino difiere del origen
if [ "$SOURCE_DIR" != "$TARGET_DIR" ]; then
    echo -e "${BLUE}[INFO] Copiando archivos del proyecto...${NC}"
    mkdir -p "$TARGET_DIR/src" "$TARGET_DIR/config" "$TARGET_DIR/packaging"
    cp -r "$SOURCE_DIR/src/"* "$TARGET_DIR/src/"
    cp -r "$SOURCE_DIR/config/"* "$TARGET_DIR/config/"
    cp -r "$SOURCE_DIR/packaging/"* "$TARGET_DIR/packaging/"
    cp "$SOURCE_DIR/requirements.txt" "$TARGET_DIR/requirements.txt"
    if [ -f "$SOURCE_DIR/README.md" ]; then
        cp "$SOURCE_DIR/README.md" "$TARGET_DIR/README.md"
    fi
fi

# 3. Crear entorno virtual (.venv) e instalar dependencias
cd "$TARGET_DIR"
if [ ! -d ".venv" ]; then
    echo -e "${BLUE}[INFO] Creando entorno virtual Python en $TARGET_DIR/.venv...${NC}"
    python3 -m venv .venv
else
    echo -e "${BLUE}[INFO] Entorno virtual existente detectado en .venv.${NC}"
fi

echo -e "${BLUE}[INFO] Instalando dependencias desde requirements.txt...${NC}"
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
echo -e "${GREEN}[OK] Dependencias instaladas correctamente.${NC}"

chmod +x packaging/linux/*.sh 2>/dev/null || true

# 4. Instalar icono en ~/.local/share/icons/hicolor/256x256/apps/
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DIR"
if [ -f "$TARGET_DIR/packaging/assets/monitor-energetico.png" ]; then
    cp "$TARGET_DIR/packaging/assets/monitor-energetico.png" "$ICON_DIR/monitor-energetico.png"
    echo -e "${GREEN}[OK] Icono instalado en $ICON_DIR/monitor-energetico.png${NC}"
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi
fi

# 5. Instalar lanzador .desktop en ~/.local/share/applications/ actualizando rutas reales
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
DESKTOP_TARGET="$APPS_DIR/monitor-energetico.desktop"
cp "$TARGET_DIR/packaging/linux/monitor-energetico.desktop" "$DESKTOP_TARGET"

START_SCRIPT="$TARGET_DIR/packaging/linux/start_dashboard.sh"
sed -i "s|^Exec=.*|Exec=$START_SCRIPT|" "$DESKTOP_TARGET"
sed -i "s|^Icon=.*|Icon=monitor-energetico|" "$DESKTOP_TARGET"
chmod 644 "$DESKTOP_TARGET"

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
echo -e "${GREEN}[OK] Lanzador de escritorio instalado en $DESKTOP_TARGET${NC}"

# 6. Instalar y habilitar servicio systemd de usuario (energy-collector.service)
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
SERVICE_SRC="$TARGET_DIR/packaging/linux/energy-collector.service"
SERVICE_DEST="$SYSTEMD_USER_DIR/energy-collector.service"

cp "$SERVICE_SRC" "$SERVICE_DEST"

# Adaptar el servicio para ejecución de usuario systemd (--user):
sed -i '/^User=/d' "$SERVICE_DEST"
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$TARGET_DIR|" "$SERVICE_DEST"
sed -i "s|^ExecStart=.*|ExecStart=$TARGET_DIR/.venv/bin/python -m src.collector.main|" "$SERVICE_DEST"
sed -i "s|^WantedBy=.*|WantedBy=default.target|" "$SERVICE_DEST"

if command -v systemctl &>/dev/null; then
    echo -e "${BLUE}[INFO] Recargando y habilitando servicio systemd de usuario...${NC}"
    systemctl --user daemon-reload
    systemctl --user enable --now energy-collector.service 2>/dev/null || {
        echo -e "${YELLOW}[AVISO] No se pudo iniciar el servicio de usuario automáticamente (sesión sin dbus activo).${NC}"
    }
    echo -e "${GREEN}[OK] Servicio systemd de usuario configurado.${NC}"
else
    echo -e "${YELLOW}[AVISO] systemctl no disponible en este entorno.${NC}"
fi

echo -e "\n${GREEN}=== Instalación completada con éxito ===${NC}"
echo -e "Para iniciar el Dashboard:"
echo -e "  - Desde el menú de aplicaciones del sistema (Monitor Energético)"
echo -e "  - O ejecutando: $START_SCRIPT\n"
