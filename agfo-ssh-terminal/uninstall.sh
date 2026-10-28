#!/usr/bin/env bash
# AGFO SSH Terminal - kaldirma betigi.
#   AGFO_SSH_PURGE=1 ile config, anahtarlar ve sertifikalar da silinir.
set -euo pipefail
APP_SLUG="agfo-ssh-terminal"
INSTALL_DIR="/opt/${APP_SLUG}"
PURGE="${AGFO_SSH_PURGE:-0}"

[ "$(id -u)" = "0" ] || { echo "[${APP_SLUG}] HATA: root gerekli." >&2; exit 1; }

echo "[${APP_SLUG}] servis durduruluyor"
systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable --now "${APP_SLUG}-certwatch.timer" 2>/dev/null || true
rm -f "/etc/systemd/system/${APP_SLUG}.service" \
      "/etc/systemd/system/${APP_SLUG}-certwatch.service" \
      "/etc/systemd/system/${APP_SLUG}-certwatch.timer"
systemctl daemon-reload 2>/dev/null || true

PORT="$(python3 -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json'))['port'])" 2>/dev/null || echo "")"
if [ -n "$PORT" ]; then
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --remove-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    echo "[${APP_SLUG}] firewalld: ${PORT}/tcp kapatildi"
  elif command -v ufw >/dev/null 2>&1; then
    ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
  fi
fi

if [ "$PURGE" = "1" ]; then
  rm -rf "${INSTALL_DIR}" /var/log/${APP_SLUG}
  echo "[${APP_SLUG}] tamamen kaldirildi (config dahil)"
else
  rm -rf "${INSTALL_DIR}/app"
  echo "[${APP_SLUG}] kaldirildi; ayarlar ${INSTALL_DIR}/config altinda korundu"
  echo "[${APP_SLUG}] tamamen silmek icin: AGFO_SSH_PURGE=1 bash $0"
fi
