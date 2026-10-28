#!/usr/bin/env bash
# =============================================================================
# AGFO CyberPanel menu duzenleyici (1.5.1)
#
# Varsayilan davranis:
#   - Menuye "AGFO SSH Terminal", "AGFO Firewall AI", "AGFO App Store" ve "AGFO File Manager"
#     girdilerini ekler
#     (kurulu olanlar icin), adreslerini otomatik giris jetonuyla yazar.
#   - "AGFO Root Terminal" ve "AGFO SafeGuard" girdilerini kaldirir.
#   - Linkler ayni sekmede acilir.
#
# Ortam degiskenleri:
#   AGFO_MENU_REMOVE="A,B"      silinecek girdiler ("" = hicbiri)
#   AGFO_MENU_ENTRIES="X|url"   eklenecek girdileri elle vermek icin
#   AGFO_MENU_TARGET=blank|self yeni sekme (varsayilan) / ayni sekme
#   AGFO_MENU_DOMAIN=alanadi    IP yerine kullanilacak alan adi (verilmezse
#                               CyberPanel 8090 sertifikasindan okunur)
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
  # uninstall.sh ayarlari korur ama app/ dizinini siler: o panel artik yok.
  [ -f "${dir}/app/server.py" ] || return 1
  local pub tok url
  pub="$("$PYBIN" "${SRC_DIR}/panel_url.py" "$cfg" "$label" || true)"
  [ -n "$pub" ] || return 1
  tok="$("$PYBIN" -c "import json;print(json.load(open('$cfg')).get('auth',{}).get('login_token',''))" 2>/dev/null || true)"
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
DROP_EXTRA=""
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
  for spec in "agfo-app-store|AGFO App Store" "agfo-file-manager|AGFO File Manager"; do
    slug="${spec%%|*}"; label="${spec#*|}"
    ENTRY="$(build_entry "/opt/${slug}" "$label" "" || true)"
    if [ -n "$ENTRY" ]; then
      [ -n "$ENTRIES" ] && ENTRIES="${ENTRIES}
${ENTRY}" || ENTRIES="$ENTRY"
    else
      say "bilgi: /opt/${slug} yok; '${label}' girdisi varsa kaldirilacak."
      [ -n "$DROP_EXTRA" ] && DROP_EXTRA="${DROP_EXTRA},${label}" || DROP_EXTRA="$label"
    fi
  done
fi

REMOVE="${AGFO_MENU_REMOVE-AGFO Root Terminal,AGFO SafeGuard}"
if [ -n "$DROP_EXTRA" ] && [ -z "${AGFO_MENU_REMOVE+x}" ]; then
  REMOVE="${REMOVE},${DROP_EXTRA}"
fi
if [ -z "$ENTRIES" ] && [ -z "$REMOVE" ]; then
  die "Kurulu panel bulunamadi; AGFO_MENU_ENTRIES ile elle verin."
fi

AGFO_MENU_ENTRIES="$ENTRIES" AGFO_MENU_REMOVE="$REMOVE" \
AGFO_MENU_TARGET="${AGFO_MENU_TARGET:-blank}" \
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
