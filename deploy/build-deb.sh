#!/bin/bash
# =============================================================================
# Genera el paquete .deb para radar-asr300p v1.3.0 (arm64, RPi5)
#
# Requisitos: dpkg-deb (correr en Linux: WSL, RPi misma, o servidor Debian)
#
# Uso:
#   cd /ruta/al/Radar-ASR300-v1.3
#   chmod +x deploy/build-deb.sh
#   ./deploy/build-deb.sh
#
# Resultado: deploy/radar-asr300p_1.3.0_arm64.deb
# =============================================================================
set -e

VERSION="1.3.0"
ARCH="arm64"
PKG_NAME="radar-asr300p"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$REPO_DIR/deploy/deb-build/${PKG_NAME}_${VERSION}_${ARCH}"

echo "=========================================="
echo " Construyendo ${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo "=========================================="

# --- 1) Limpiar build previo ---
echo "[1/5] Limpiando build previo..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/opt/radar"
mkdir -p "$BUILD_DIR/etc/systemd/system"

# --- 2) Copiar archivos del proyecto ---
echo "[2/5] Copiando codigo fuente..."
rsync -a \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.db' \
    --exclude='*.log' \
    --exclude='*.err.log' \
    --exclude='plate_pic/' \
    --exclude='scene_pic/' \
    --exclude='deploy/' \
    --exclude='tests/' \
    --exclude='.git/' \
    --exclude='.gitignore' \
    --exclude='.claude/' \
    --exclude='.vscode/' \
    --exclude='.idea/' \
    "$REPO_DIR/" "$BUILD_DIR/opt/radar/"

# --- 3) Copiar metadatos DEBIAN ---
echo "[3/5] Copiando metadatos DEBIAN..."
cp "$REPO_DIR/deploy/debian/control"   "$BUILD_DIR/DEBIAN/control"
cp "$REPO_DIR/deploy/debian/conffiles" "$BUILD_DIR/DEBIAN/conffiles"
cp "$REPO_DIR/deploy/debian/postinst"  "$BUILD_DIR/DEBIAN/postinst"
cp "$REPO_DIR/deploy/debian/prerm"     "$BUILD_DIR/DEBIAN/prerm"
cp "$REPO_DIR/deploy/debian/postrm"    "$BUILD_DIR/DEBIAN/postrm"
chmod 755 "$BUILD_DIR/DEBIAN/postinst" "$BUILD_DIR/DEBIAN/prerm" "$BUILD_DIR/DEBIAN/postrm"

# --- 4) Copiar unidades systemd ---
echo "[4/5] Copiando unidades systemd..."
cp "$REPO_DIR/deploy/systemd/"*.service "$BUILD_DIR/etc/systemd/system/"
cp "$REPO_DIR/deploy/systemd/radar.target" "$BUILD_DIR/etc/systemd/system/"

# --- 5) Construir .deb ---
echo "[5/5] Construyendo paquete..."
chmod -R 755 "$BUILD_DIR/opt/radar/"
dpkg-deb --build "$BUILD_DIR" "$REPO_DIR/deploy/${PKG_NAME}_${VERSION}_${ARCH}.deb"

echo ""
echo "=========================================="
echo " PAQUETE GENERADO"
echo "=========================================="
echo " Archivo: deploy/${PKG_NAME}_${VERSION}_${ARCH}.deb"
echo ""
echo " Para instalar en la RPi5:"
echo "   scp deploy/${PKG_NAME}_${VERSION}_${ARCH}.deb pi@<ip>:/tmp/"
echo "   ssh pi@<ip> 'sudo apt install /tmp/${PKG_NAME}_${VERSION}_${ARCH}.deb'"
echo ""
echo " Para desinstalar:"
echo "   sudo apt remove ${PKG_NAME}      # mantiene config y datos"
echo "   sudo apt purge  ${PKG_NAME}      # borra todo (incl. venv y plate_pic)"
echo ""
