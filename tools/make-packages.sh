#!/usr/bin/env bash
# Her aracı, Package Runner'a doğrudan yüklenebilecek bir ZIP'e paketler.
# Çıktı: dist/<arac>-<surum>.zip  (install.sh arşivin kökünde olur)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${ROOT}/dist"
rm -rf "$DIST"; mkdir -p "$DIST"

for dir in "${ROOT}"/agfo-*/; do
  name="$(basename "$dir")"
  [ -f "${dir}install.sh" ] || continue
  version="$(cat "${dir}VERSION" 2>/dev/null || echo "0.0.0")"
  version="${version//[$'\t\r\n ']}"
  out="${DIST}/${name}-${version}.zip"
  ( cd "$dir" && zip -rq "$out" . -x '*__pycache__*' '*.pyc' 'config/config.json' \
      'config/providers.json' 'config/proposals.json' 'config/audit.log' 'config/tls/*' 'config/keys/*' )
  printf '%s  (%s)\n' "$(basename "$out")" "$(du -h "$out" | cut -f1)"
done
echo "Paketler: ${DIST}"
