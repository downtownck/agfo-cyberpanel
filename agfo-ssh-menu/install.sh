#!/usr/bin/env bash
# =============================================================================
# AGFO SSH Terminal - CyberPanel menu girdisi ekleyici
#
# Mevcut "AGFO Root Terminal" girdinizin sablondaki kalibini bulur, bir esini
# olusturup "AGFO SSH Terminal" olarak hemen altina ekler. Degistirdigi her
# dosyanin yedegini alir.
#
# Ortam degiskenleri (hepsi istege bagli):
#   AGFO_MENU_URL=https://IP:8822/?open=root   link adresi (bos ise otomatik)
#   AGFO_MENU_LABEL="AGFO SSH Terminal"        menude gorunecek ad
#   AGFO_MENU_ANCHOR="AGFO Root Terminal"      kalibi kopyalanacak mevcut girdi
#   AGFO_MENU_ROOT=/usr/local/CyberCP          sablon dizini
#   AGFO_MENU_SKIP_RESTART=0                   1 = lscpd'yi yeniden baslatma
# =============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { printf '[agfo-ssh-menu] %s\n' "$*"; }
die() { printf '[agfo-ssh-menu] HATA: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "root olarak calistirilmali."

PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || die "python3 bulunamadi."

# --- link adresini belirle ---
URL="${AGFO_MENU_URL:-}"
if [ -z "$URL" ]; then
  CFG="/opt/agfo-ssh-terminal/config/config.json"
  [ -f "$CFG" ] || die "AGFO SSH Terminal kurulu degil; AGFO_MENU_URL verin."
  # Terminal kurulumunda alan adi verildiyse (AGFO_SSH_DOMAIN) config'te
  # public_url hazirdir; sertifika uyarisi cikmasin diye oncelikle o kullanilir.
  PUB="$("$PYBIN" -c "import json;print(json.load(open('$CFG')).get('public_url') or '')" 2>/dev/null || true)"
  if [ -n "$PUB" ]; then
    URL="${PUB%/}/?open=root"
    say "link config.json'daki public_url'den alindi"
  else
    PORT="$("$PYBIN" -c "import json;print(json.load(open('$CFG'))['port'])")"
    TLS="$("$PYBIN" -c "import json;print('1' if json.load(open('$CFG'))['tls']['enabled'] else '0')")"
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -n "$IP" ] || die "sunucu IP'si bulunamadi; AGFO_MENU_URL verin."
    SCHEME="http"; [ "$TLS" = "1" ] && SCHEME="https"
    URL="${SCHEME}://${IP}:${PORT}/?open=root"
    say "UYARI: alan adi tanimli degil, IP kullaniliyor (tarayici SSL uyarisi verebilir)"
  fi
  say "link otomatik belirlendi: $URL"
fi

AGFO_MENU_URL="$URL" "$PYBIN" "${SRC_DIR}/menu_patch.py"

# --- CyberPanel'i yeniden baslat ---
if [ "${AGFO_MENU_SKIP_RESTART:-0}" != "1" ]; then
  loaded() { [ "$(systemctl show -p LoadState --value "$1" 2>/dev/null)" = "loaded" ]; }
  DONE=""
  if loaded lscpd; then
    say "lscpd yeniden baslatiliyor (yonetim paneli birkac saniye kesilir)"
    systemctl restart lscpd && DONE="lscpd"
  elif [ -x /usr/local/lsws/bin/lswsctrl ]; then
    say "LiteSpeed nazikce yeniden baslatiliyor (siteler kesilmez)"
    /usr/local/lsws/bin/lswsctrl restart >/dev/null 2>&1 && DONE="lsws (graceful)"
  elif loaded lsws; then
    say "lsws yeniden baslatiliyor"
    systemctl restart lsws && DONE="lsws"
  fi
  if [ -n "$DONE" ]; then
    say "yeniden baslatildi: $DONE"
  else
    say "CyberPanel servisi bulunamadi; cogu kurulumda sayfayi Ctrl+F5 ile"
    say "yenilemek yeterlidir. Gerekirse: systemctl restart lscpd"
  fi
fi

say "bitti. CyberPanel sayfasini yenileyin (Ctrl+F5)."
say "geri almak icin: bash ${SRC_DIR}/restore.sh"
