#!/usr/bin/env bash
# AGFO Firewall AI - kaldirma.
#   AGFO_FW_PURGE=1        panel ayarlarini ve API anahtarlarini da sil
#   AGFO_FW_PURGE_CROWDSEC=1  CrowdSec'i de kaldir (varsayilan: dokunma)
set -euo pipefail
APP_SLUG="agfo-firewall-ai"
INSTALL_DIR="/opt/${APP_SLUG}"
say() { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
[ "$(id -u)" = "0" ] || { echo "root gerekli" >&2; exit 1; }

systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable "${APP_SLUG}.service" 2>/dev/null || true
systemctl disable --now "${APP_SLUG}-certwatch.timer" 2>/dev/null || true
rm -f "/etc/systemd/system/${APP_SLUG}.service" "/etc/systemd/system/${APP_SLUG}-certwatch."*
systemctl daemon-reload 2>/dev/null || true
say "panel servisi kaldirildi"

PORT="$(python3 -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json'))['port'])" 2>/dev/null || echo "")"
if [ -n "$PORT" ] && command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --remove-port="${PORT}/tcp" >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
  say "firewalld: ${PORT}/tcp kapatildi"
fi

if [ "${AGFO_FW_PURGE_CROWDSEC:-0}" = "1" ]; then
  say "CrowdSec kaldiriliyor"
  systemctl disable --now crowdsec 2>/dev/null || true
  for unit in crowdsec-firewall-bouncer crowdsec-firewall-bouncer-nftables crowdsec-firewall-bouncer-iptables; do
    systemctl disable --now "$unit" 2>/dev/null || true
  done
  command -v apt-get >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq crowdsec 'crowdsec-firewall-bouncer*' >/dev/null 2>&1 || true
  rm -f /etc/crowdsec/acquis.d/agfo-cyberpanel.yaml
else
  say "CrowdSec'e dokunulmadi (kaldirmak icin AGFO_FW_PURGE_CROWDSEC=1)"
fi

if [ "${AGFO_FW_PURGE:-0}" = "1" ]; then
  rm -rf "${INSTALL_DIR}"
  say "panel tamamen silindi (API anahtarlari dahil)"
else
  rm -rf "${INSTALL_DIR}/app"
  say "ayarlar ve anahtarlar ${INSTALL_DIR}/config altinda korundu"
  say "tamamen silmek icin: AGFO_FW_PURGE=1 bash $0"
fi
