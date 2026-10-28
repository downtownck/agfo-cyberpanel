#!/usr/bin/env bash
# AGFO File Manager - kaldirma.
#   AGFO_FM_PURGE=1   ayarlari (sifre, jeton, sertifika) da sil
set -euo pipefail
APP_SLUG="agfo-file-manager"
INSTALL_DIR="/opt/${APP_SLUG}"
say() { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
[ "$(id -u)" = "0" ] || { echo "root gerekli" >&2; exit 1; }

PORT="$(python3 -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json'))['port'])" 2>/dev/null || echo "")"
systemctl stop "${APP_SLUG}.service" "${APP_SLUG}-backend.service" 2>/dev/null || true
systemctl disable "${APP_SLUG}.service" "${APP_SLUG}-backend.service" 2>/dev/null || true
systemctl disable --now "${APP_SLUG}-certwatch.timer" 2>/dev/null || true
rm -f "/etc/systemd/system/${APP_SLUG}.service" "/etc/systemd/system/${APP_SLUG}-backend.service" \
      "/etc/systemd/system/${APP_SLUG}-certwatch."*
systemctl daemon-reload 2>/dev/null || true
say "servisler kaldirildi"

if [ -n "$PORT" ] && command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --remove-port="${PORT}/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  systemctl try-restart crowdsec-firewall-bouncer >/dev/null 2>&1 || true
  say "firewalld: ${PORT}/tcp kapatildi"
fi

if [ "${AGFO_FM_PURGE:-0}" = "1" ]; then
  rm -rf "${INSTALL_DIR}"
  say "tamamen silindi"
else
  rm -rf "${INSTALL_DIR}/app" "${INSTALL_DIR}/www" "${INSTALL_DIR}/sessions"
  say "ayarlar ${INSTALL_DIR}/config altinda korundu (tamamen silmek icin AGFO_FM_PURGE=1)"
fi
say "menu girdisini kaldirmak icin agfo-ssh-menu paketini yeniden calistirin."
