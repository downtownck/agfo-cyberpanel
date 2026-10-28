#!/usr/bin/env bash
# Let's Encrypt / CyberPanel sertifikasi yenilendiginde servisi tazeler.
# Sunucu sertifikayi acilista yukler; yenilenen dosyayi gormesi icin
# yeniden baslatmak gerekir. Bu betik gunde bir kez timer ile calisir.
set -euo pipefail
INSTALL_DIR="/opt/agfo-ssh-terminal"
CFG="${INSTALL_DIR}/config/config.json"
STATE="${INSTALL_DIR}/config/tls/.cert.sha256"
[ -f "$CFG" ] || exit 0

CERT="$(python3 -c "import json;print(json.load(open('${CFG}'))['tls'].get('cert','') or '')" 2>/dev/null || echo "")"
ENABLED="$(python3 -c "import json;print('1' if json.load(open('${CFG}'))['tls'].get('enabled') else '0')" 2>/dev/null || echo "0")"
[ "$ENABLED" = "1" ] || exit 0
[ -n "$CERT" ] && [ -f "$CERT" ] || exit 0

NEW="$(sha256sum "$CERT" | awk '{print $1}')"
OLD="$(cat "$STATE" 2>/dev/null || true)"
if [ "$NEW" != "$OLD" ]; then
  printf '%s\n' "$NEW" > "$STATE"
  chmod 600 "$STATE"
  if [ -n "$OLD" ]; then
    logger -t agfo-ssh-terminal "sertifika degisti, servis yeniden baslatiliyor" 2>/dev/null || true
    systemctl restart agfo-ssh-terminal
  fi
fi
