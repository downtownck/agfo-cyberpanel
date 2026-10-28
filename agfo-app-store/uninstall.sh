#!/usr/bin/env bash
# AGFO App Store - kaldirma.
# Kurulan siteler ve veritabanlari SILINMEZ; onlar CyberPanel'e aittir.
#   AGFO_STORE_PURGE=1   panel ayarlarini ve kurulum kayitlarini da sil
set -euo pipefail
APP_SLUG="agfo-app-store"
INSTALL_DIR="/opt/${APP_SLUG}"
say() { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
[ "$(id -u)" = "0" ] || { echo "root gerekli" >&2; exit 1; }

PORT="$(python3 -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json'))['port'])" 2>/dev/null || echo "")"

systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable --now "${APP_SLUG}-certwatch.timer" 2>/dev/null || true
rm -f "/etc/systemd/system/${APP_SLUG}.service" "/etc/systemd/system/${APP_SLUG}-certwatch."*
systemctl daemon-reload 2>/dev/null || true
say "panel servisi kaldirildi"

if [ -n "$PORT" ] && command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --remove-port="${PORT}/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  systemctl try-restart crowdsec-firewall-bouncer >/dev/null 2>&1 || true
  say "firewalld: ${PORT}/tcp kapatildi"
fi

if [ "${AGFO_STORE_PURGE:-0}" = "1" ]; then
  rm -rf "${INSTALL_DIR}"
  say "panel tamamen silindi"
else
  rm -rf "${INSTALL_DIR}/app" "${INSTALL_DIR}/work"
  say "ayarlar ve kurulum kayitlari ${INSTALL_DIR}/config altinda korundu"
  say "tamamen silmek icin: AGFO_STORE_PURGE=1 bash $0"
fi
say "kurdugunuz siteler yerinde duruyor; onlari CyberPanel'den yonetin."
say "menu girdisini kaldirmak icin agfo-ssh-menu paketini (1.4.0+) yeniden calistirin."
