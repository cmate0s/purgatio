#!/usr/bin/env bash
# Instala Purgatio en el perfil del usuario (sin tocar el sistema).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

install_app() {
  mkdir -p "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
  ln -sf "${REPO}/bin/purgatio" "${BIN_DIR}/purgatio"
  install -m 644 "${REPO}/data/purgatio.svg" "${ICON_DIR}/purgatio.svg"
  sed "s|^Exec=.*|Exec=${BIN_DIR}/purgatio|" "${REPO}/data/purgatio.desktop" > "${APP_DIR}/purgatio.desktop"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
  echo "Purgatio instalado:"
  echo "  comando  -> ${BIN_DIR}/purgatio"
  echo "  menú     -> ${APP_DIR}/purgatio.desktop"
  echo "  icono    -> ${ICON_DIR}/purgatio.svg"
}

uninstall_app() {
  rm -f "${BIN_DIR}/purgatio" "${APP_DIR}/purgatio.desktop" "${ICON_DIR}/purgatio.svg"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true
  echo "Purgatio desinstalado (el repositorio sigue en ${REPO})."
}

case "${1:-install}" in
  install) install_app ;;
  uninstall) uninstall_app ;;
  *) echo "Uso: $0 [install|uninstall]" >&2; exit 2 ;;
esac
