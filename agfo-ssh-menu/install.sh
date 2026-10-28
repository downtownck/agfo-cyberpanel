#!/usr/bin/env bash
# =============================================================================
# AGFO CyberPanel menu duzenleyici (1.3.0)
#
# Varsayilan davranis:
#   - Menuye "AGFO SSH Terminal" ve "AGFO Firewall AI" girdilerini ekler
#     (kurulu olanlar icin), adreslerini otomatik giris jetonuyla yazar.
#   - "AGFO Root Terminal" ve "AGFO SafeGuard" girdilerini kaldirir.
#   - Linkler ayni sekmede acilir.
#
# Ortam degiskenleri:
#   AGFO_MENU_REMOVE="A,B"      silinecek girdiler ("" = hicbiri)
#   AGFO_MENU_ENTRIES="X|url"   eklenecek girdileri elle vermek icin
#   AGFO_MENU_TARGET=self|blank ayni sekme / yeni sekme
#   AGFO_MENU_NO_TOKEN=1        jetonsuz link yaz (panel sifre sorar)
#   AGFO_MENU_ROOT=/usr/local/CyberCP
#   AGFO_MENU_SKIP_RESTART=1    CyberPanel servisini yeniden baslatma
# =============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { printf '[agfo-ssh-menu] %s\n' "$*"; }
die() { printf '[agfo-ssh-menu] HATA: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "root olarak calistirilmali."
PYBIN="$(command -v python3 || true)"
[ -n "$PYBIN" ] || die "python3 bulunamadi."

# --- kurulu panellerden link uret ---------------------------------------------
# $1 kurulum dizini, $2 menu etiketi, $3 ek sorgu parametresi
build_entry() {
  local dir="$1" label="$2" extra="${3:-}"
  local cfg="${dir}/config/config.json"
  [ -f "$cfg" ] || return 1
  local pub tok url
  pub="$("$PYBIN" -c "import json;print(json.load(open('$cfg')).get('public_url') or '')" 2>/dev/null || true)"
  tok="$("$PYBIN" -c "import json;print(json.load(open('$cfg')).get('auth',{}).get('login_token',''))" 2>/dev/null || true)"
  if [ -z "$pub" ]; then
    local port scheme ip
    port="$("$PYBIN" -c "import json;print(json.load(open('$cfg'))['port'])" 2>/dev/null || true)"
    [ -n "$port" ] || return 1
    scheme="$("$PYBIN" -c "import json;print('https' if json.load(open('$cfg'))['tls'].get('enabled') else 'http')" 2>/dev/null || echo https)"
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    pub="${scheme}://${ip}:${port}/"
  fi
  url="${pub%/}/"
  local qs=""
  if [ "${AGFO_MENU_NO_TOKEN:-0}" != "1" ] && [ -n "$tok" ]; then
    qs="t=${tok}"
  fi
  if [ -n "$extra" ]; then
    [ -n "$qs" ] && qs="${qs}&${extra}" || qs="$extra"
  fi
  [ -n "$qs" ] && url="${url}?${qs}"
  printf '%s|%s\n' "$label" "$url"
}

ENTRIES="${AGFO_MENU_ENTRIES:-}"
if [ -z "$ENTRIES" ]; then
  TERM_ENTRY="$(build_entry /opt/agfo-ssh-terminal "AGFO SSH Terminal" "open=root" || true)"
  FW_ENTRY="$(build_entry /opt/agfo-firewall-ai "AGFO Firewall AI" "" || true)"
  [ -n "$TERM_ENTRY" ] && ENTRIES="$TERM_ENTRY"
  if [ -n "$FW_ENTRY" ]; then
    [ -n "$ENTRIES" ] && ENTRIES="${ENTRIES}
${FW_ENTRY}" || ENTRIES="$FW_ENTRY"
  else
    say "UYARI: /opt/agfo-firewall-ai bulunamadi; Firewall girdisi atlaniyor."
    say "       Once firewall paketini kurup bu paketi tekrar calistirin."
  fi
  [ -n "$ENTRIES" ] || die "Kurulu panel bulunamadi; AGFO_MENU_ENTRIES ile elle verin."
fi

REMOVE="${AGFO_MENU_REMOVE-AGFO Root Terminal,AGFO SafeGuard}"

AGFO_MENU_ENTRIES="$ENTRIES" AGFO_MENU_REMOVE="$REMOVE" \
AGFO_MENU_TARGET="${AGFO_MENU_TARGET:-self}" \
AGFO_MENU_ROOT="${AGFO_MENU_ROOT:-/usr/local/CyberCP}" \
AGFO_MENU_DUMP="${AGFO_MENU_DUMP:-0}" \
"$PYBIN" "${SRC_DIR}/menu_patch.py"

# --- CyberPanel'i tazele -------------------------------------------------------
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
    systemctl restart lsws && DONE="lsws"
  fi
  [ -n "$DONE" ] && say "yeniden baslatildi: $DONE" || \
    say "CyberPanel servisi bulunamadi; sayfayi Ctrl+F5 ile yenileyin."
fi

say "bitti. CyberPanel sayfasini Ctrl+F5 ile yenileyin."
say "geri almak icin: bash ${SRC_DIR}/restore.sh"
