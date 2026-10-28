#!/usr/bin/env bash
# Sertifika yenilendiginde paneli tazeler.
set -euo pipefail
INSTALL_DIR="/opt/agfo-firewall-ai"
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
  printf '%s\n' "$NEW" > "$STATE"; chmod 600 "$STATE"
  [ -n "$OLD" ] && systemctl restart agfo-firewall-ai || true
fi
