#!/usr/bin/env bash
# =============================================================================
# AGFO App Store - kurulum betigi
# CyberPanel sunucularinda AGFO Package Runner ile root olarak calistirilir.
# tty gerektirmez, soru sormaz.
#
# Ortam degiskenleri (hepsi istege bagli):
#   AGFO_STORE_PORT=8824            panel portu
#   AGFO_STORE_BIND=0.0.0.0         dinlenecek adres
#   AGFO_STORE_PASSWORD=...         panel sifresi (yoksa uretilir, korunur)
#   AGFO_STORE_DOMAIN=alanadi.com   TLS sertifikasi bu alan adindan bulunur.
#                                   Verilmezse CyberPanel'in 8090 sertifikasindaki
#                                   alan adi kullanilir (Let's Encrypt varsa).
#   AGFO_STORE_CERT / AGFO_STORE_KEY  sertifikayi elle vermek icin
#   AGFO_STORE_TLS=1                0 = duz HTTP
#   AGFO_STORE_ALLOW_IPS=1.2.3.4    panele erisebilecek IP'ler
#   AGFO_STORE_SKIP_FIREWALL=0      1 = guvenlik duvarina dokunma
#   AGFO_STORE_PHP=8.2              yeni sitelerin varsayilan PHP surumu
#   AGFO_STORE_WAIT=600             yukseltmede suren kurulumlar icin bekleme (sn)
# =============================================================================
set -euo pipefail

APP_NAME="AGFO App Store"
APP_SLUG="agfo-app-store"
APP_VERSION="1.0.3"
INSTALL_DIR="/opt/${APP_SLUG}"
UNIT_PATH="/etc/systemd/system/${APP_SLUG}.service"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${AGFO_STORE_PORT:-8824}"
BIND="${AGFO_STORE_BIND:-0.0.0.0}"
TLS="${AGFO_STORE_TLS:-1}"
DOMAIN="${AGFO_STORE_DOMAIN:-}"
ALLOW_IPS="${AGFO_STORE_ALLOW_IPS:-}"
SKIP_FW="${AGFO_STORE_SKIP_FIREWALL:-0}"
CERT="${AGFO_STORE_CERT:-}"
KEY="${AGFO_STORE_KEY:-}"
WAIT_MAX="${AGFO_STORE_WAIT:-600}"

say()  { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
warn() { printf '[%s] UYARI: %s\n' "$APP_SLUG" "$*" >&2; }
die()  { printf '[%s] HATA: %s\n' "$APP_SLUG" "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "root olarak calistirilmali."
say "${APP_NAME} ${APP_VERSION} kurulumu basliyor"

# --- 1. on kosullar ----------------------------------------------------------
PYBIN=""
for cand in /usr/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,8) else 1)' 2>/dev/null; then
    PYBIN="$cand"; break
  fi
done
[ -n "$PYBIN" ] || die "Python 3.8+ bulunamadi."
say "python: ${PYBIN} ($("$PYBIN" -V 2>&1))"
[ -f "${SRC_DIR}/app/server.py" ] || die "Paket bozuk: app/server.py yok."
N_APPS="$(ls "${SRC_DIR}/app/catalog/"*.json 2>/dev/null | wc -l)"
[ "$N_APPS" -gt 0 ] || die "Paket bozuk: katalog bos."

CP_CLI=""
for cand in /usr/local/CyberCP/bin/cyberpanel /usr/bin/cyberpanel /usr/local/bin/cyberpanel "$(command -v cyberpanel 2>/dev/null || true)"; do
  [ -n "$cand" ] && [ -x "$cand" ] && { CP_CLI="$cand"; break; }
done
if [ -n "$CP_CLI" ]; then
  say "CyberPanel CLI: ${CP_CLI}"
else
  warn "cyberpanel komutu bulunamadi; panel acilir ama site olusturamaz."
fi
for tool in tar unzip mysql; do
  command -v "$tool" >/dev/null 2>&1 || warn "'${tool}' bulunamadi; bazi uygulamalar kurulamayabilir."
done

# --- 2. yukseltme: suren kurulumlari bekle -----------------------------------
running_jobs() {
  local f="${INSTALL_DIR}/config/jobs.json"
  [ -f "$f" ] || { echo 0; return; }
  "$PYBIN" -c "import json;print(sum(1 for j in json.load(open('$f')) if j.get('status') in ('queued','running')))" 2>/dev/null || echo 0
}
if systemctl list-unit-files 2>/dev/null | grep -q "^${APP_SLUG}.service" \
   && systemctl is-active --quiet "${APP_SLUG}.service"; then
  waited=0
  while [ "$(running_jobs)" != "0" ] && [ "$waited" -lt "$WAIT_MAX" ]; do
    [ $((waited % 30)) -eq 0 ] && say "suren uygulama kurulumu var; bitmesi bekleniyor (${waited}/${WAIT_MAX} sn)"
    sleep 5; waited=$((waited + 5))
  done
  [ "$(running_jobs)" = "0" ] || warn "kurulum hala suruyor; yarida kesilecek (is hata olarak isaretlenir)."
  say "mevcut servis durduruluyor (yukseltme)"
  systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
fi

# --- 3. dosyalar -------------------------------------------------------------
say "dosyalar ${INSTALL_DIR} dizinine kopyalaniyor (${N_APPS} uygulama tarifi)"
mkdir -p "${INSTALL_DIR}/config/tls" "${INSTALL_DIR}/work"
rm -rf "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/app" "${INSTALL_DIR}/app"
find "${INSTALL_DIR}/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp -a "${SRC_DIR}/README.md" "${INSTALL_DIR}/README.md" 2>/dev/null || true
cp -a "${SRC_DIR}/uninstall.sh" "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
printf '%s\n' "$APP_VERSION" > "${INSTALL_DIR}/VERSION"
chown -R root:root "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}" "${INSTALL_DIR}/app"
chmod 700 "${INSTALL_DIR}/config" "${INSTALL_DIR}/config/tls" "${INSTALL_DIR}/work"
find "${INSTALL_DIR}/app" -type f -exec chmod 644 {} \;
find "${INSTALL_DIR}/app" -type d -exec chmod 755 {} \;
chmod +x "${INSTALL_DIR}/app/certwatch.sh"

# --- 4. TLS ------------------------------------------------------------------
# Alan adi verilmediyse CyberPanel'in kendi (8090) sertifikasindan oku: tarayici
# 8090'i guvenli buluyorsa ayni alan adi bu panel icin de dogru olandir.
if [ "$TLS" = "1" ] && [ -z "$DOMAIN" ] && [ -z "$CERT" ] && command -v openssl >/dev/null 2>&1; then
  for pc in /usr/local/lscp/conf/cert.pem /usr/local/lscp/conf/server.crt; do
    [ -f "$pc" ] || continue
    cand="$(openssl x509 -in "$pc" -noout -ext subjectAltName 2>/dev/null \
            | tr ',' '\n' | sed -n 's/^ *DNS://p' | grep -v '^\*' | head -1 || true)"
    if [ -n "$cand" ]; then
      DOMAIN="$cand"; say "alan adi CyberPanel sertifikasindan alindi: ${DOMAIN}"; break
    fi
  done
fi

if [ "$TLS" = "1" ] && [ -n "$DOMAIN" ] && [ -z "$CERT" ]; then
  for base in "/etc/letsencrypt/live/${DOMAIN}" "/etc/letsencrypt/live/${DOMAIN}-0001" \
              "/usr/local/lsws/conf/vhosts/${DOMAIN}" "/etc/letsencrypt/live/www.${DOMAIN}"; do
    if [ -f "${base}/fullchain.pem" ] && [ -f "${base}/privkey.pem" ]; then
      CERT="${base}/fullchain.pem"; KEY="${base}/privkey.pem"
      say "sertifika bulundu: ${CERT}"; break
    fi
  done
  if [ -z "$CERT" ]; then
    warn "${DOMAIN} icin Let's Encrypt sertifikasi bulunamadi; kendinden imzali kullanilacak"
    warn "ve tarayici uyari verecek. CyberPanel > SSL > Hostname SSL ile uretip tekrar calistirin."
  fi
fi

if [ "$TLS" = "1" ]; then
  if [ -n "$CERT" ] && [ -n "$KEY" ]; then
    [ -f "$CERT" ] && [ -f "$KEY" ] || die "Sertifika dosyalari bulunamadi."
  else
    CERT="${INSTALL_DIR}/config/tls/server.crt"
    KEY="${INSTALL_DIR}/config/tls/server.key"
    if [ -f "$CERT" ] && [ -f "$KEY" ]; then
      say "mevcut kendinden imzali sertifika korunuyor"
    else
      command -v openssl >/dev/null 2>&1 || die "openssl yok; AGFO_STORE_TLS=0 deneyin."
      say "kendinden imzali sertifika uretiliyor"
      HN="$(hostname -f 2>/dev/null || hostname)"
      openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout "$KEY" -out "$CERT" -subj "/C=TR/O=AGFO/CN=${HN}" \
        -addext "subjectAltName=DNS:${HN},IP:127.0.0.1" >/dev/null 2>&1 \
        || die "sertifika uretilemedi."
      chmod 600 "$KEY"; chmod 644 "$CERT"
    fi
  fi
fi

# --- 5. yapilandirma ---------------------------------------------------------
SCHEME="http"; [ "$TLS" = "1" ] && SCHEME="https"
SRV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$SRV_IP" ] || SRV_IP="SUNUCU-IP"
if [ -n "$DOMAIN" ]; then PUBLIC_URL="${SCHEME}://${DOMAIN}:${PORT}/"; else PUBLIC_URL="${SCHEME}://${SRV_IP}:${PORT}/"; fi

cfg_get() {  # $1 = python ifadesi (c = config sozlugu)
  local f="${INSTALL_DIR}/config/config.json"
  [ -f "$f" ] || return 0
  "$PYBIN" -c "import json;c=json.load(open('$f'));print($1)" 2>/dev/null || true
}
EXISTING_HASH="$(cfg_get "c.get('auth',{}).get('password_hash','')")"
EXISTING_TOKEN="$(cfg_get "c.get('auth',{}).get('login_token','')")"

GEN_PASSWORD=""
if [ -z "${AGFO_STORE_PASSWORD:-}" ] && [ -z "$EXISTING_HASH" ]; then
  GEN_PASSWORD="$("$PYBIN" -c 'import secrets,string;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(20)))')"
fi
LOGIN_TOKEN="${EXISTING_TOKEN}"
[ -n "$LOGIN_TOKEN" ] || LOGIN_TOKEN="$("$PYBIN" -c 'import secrets;print(secrets.token_urlsafe(32))')"

say "config.json yaziliyor"
AGFO_STORE_PASSWORD="${AGFO_STORE_PASSWORD:-$GEN_PASSWORD}" \
AGFO_CFG_PORT="$PORT" AGFO_CFG_BIND="$BIND" AGFO_CFG_TLS="$TLS" \
AGFO_CFG_CERT="${CERT:-}" AGFO_CFG_KEY="${KEY:-}" AGFO_CFG_ALLOW="$ALLOW_IPS" \
AGFO_CFG_PUBLIC="$PUBLIC_URL" AGFO_CFG_TOKEN="$LOGIN_TOKEN" AGFO_CFG_CLI="$CP_CLI" \
AGFO_CFG_PHP="${AGFO_STORE_PHP:-}" \
AGFO_STORE_CONFIG_DIR="${INSTALL_DIR}/config" AGFO_CFG_APP="${INSTALL_DIR}/app" \
"$PYBIN" - <<'PYEOF'
import json, os, sys
sys.path.insert(0, os.environ["AGFO_CFG_APP"])
import store

path = store.CONFIG_PATH
existing = {}
if os.path.exists(path):
    try:
        existing = json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        print("[agfo-app-store] UYARI: eski config okunamadi (%s)" % exc)
cfg = store.deep_merge(store.DEFAULT_CONFIG, existing)
cfg["bind"] = os.environ["AGFO_CFG_BIND"]
cfg["port"] = int(os.environ["AGFO_CFG_PORT"])
cfg["public_url"] = os.environ.get("AGFO_CFG_PUBLIC") or ""
cfg["tls"]["enabled"] = os.environ["AGFO_CFG_TLS"] == "1"
if os.environ.get("AGFO_CFG_CERT"):
    cfg["tls"]["cert"] = os.environ["AGFO_CFG_CERT"]
    cfg["tls"]["key"] = os.environ["AGFO_CFG_KEY"]
cfg["allow_ips"] = [x.strip() for x in (os.environ.get("AGFO_CFG_ALLOW") or "").split(",") if x.strip()]
if os.environ.get("AGFO_CFG_CLI") and not cfg["cyberpanel"].get("cli"):
    cfg["cyberpanel"]["cli"] = os.environ["AGFO_CFG_CLI"]
if os.environ.get("AGFO_CFG_PHP"):
    cfg["cyberpanel"]["default_php"] = os.environ["AGFO_CFG_PHP"]
cfg["auth"]["login_token"] = os.environ.get("AGFO_CFG_TOKEN") or cfg["auth"].get("login_token") or ""

pw = os.environ.get("AGFO_STORE_PASSWORD") or ""
if pw:
    cfg["auth"]["password_hash"] = store.hash_password(pw)
    print("[agfo-app-store] panel sifresi ayarlandi")
elif not cfg["auth"].get("password_hash"):
    raise SystemExit("[agfo-app-store] HATA: sifre yok")
else:
    print("[agfo-app-store] mevcut panel sifresi korunuyor")

store._atomic_write(path, json.dumps(cfg, indent=2, ensure_ascii=False))
for target, empty in ((store.JOBS_PATH, []), (store.INSTALLS_PATH, [])):
    if not os.path.exists(target):
        store._atomic_write(target, json.dumps(empty))
PYEOF

# --- 6. servis ---------------------------------------------------------------
say "systemd servisi kuruluyor"
sed -e "s#@PYBIN@#${PYBIN}#g" -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" \
    "${SRC_DIR}/systemd/${APP_SLUG}.service" > "$UNIT_PATH"
chmod 644 "$UNIT_PATH"
SELF_SIGNED="${INSTALL_DIR}/config/tls/server.crt"
CERTWATCH=0
if [ "$TLS" = "1" ] && [ -n "${CERT:-}" ] && [ "$CERT" != "$SELF_SIGNED" ]; then
  sed -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.service" \
      > "/etc/systemd/system/${APP_SLUG}-certwatch.service"
  cp -a "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.timer" "/etc/systemd/system/${APP_SLUG}-certwatch.timer"
  chmod 644 "/etc/systemd/system/${APP_SLUG}-certwatch."*
  CERTWATCH=1
else
  systemctl disable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${APP_SLUG}-certwatch."*
fi
systemctl daemon-reload
systemctl enable "${APP_SLUG}.service" >/dev/null 2>&1 || true
systemctl restart "${APP_SLUG}.service"
if [ "$CERTWATCH" = "1" ]; then
  systemctl enable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true
fi

# --- 7. guvenlik duvari ------------------------------------------------------
if [ "$SKIP_FW" != "1" ] && [ "$BIND" != "127.0.0.1" ]; then
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    say "firewalld: ${PORT}/tcp aciliyor"
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    # firewalld reload'u CrowdSec bouncer kurallarini dusurebilir; tazele.
    systemctl try-restart crowdsec-firewall-bouncer >/dev/null 2>&1 || true
  elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
    say "ufw: ${PORT}/tcp acildi"
  fi
fi

# --- 8. ozet -----------------------------------------------------------------
sleep 1.5
if ! systemctl is-active --quiet "${APP_SLUG}.service"; then
  warn "panel servisi baslatilamadi; son gunluk:"
  journalctl -u "${APP_SLUG}.service" -n 30 --no-pager 2>/dev/null || true
  die "kurulum tamamlanamadi"
fi

echo
echo "============================================================"
echo " ${APP_NAME} ${APP_VERSION} kuruldu (${N_APPS} uygulama)"
echo "============================================================"
echo " Panel      : ${PUBLIC_URL}"
echo " Menu linki : ${PUBLIC_URL}?t=${LOGIN_TOKEN}"
echo "              (menu paketi 1.4.0+ bu linki kendisi ekler)"
if [ -n "$GEN_PASSWORD" ]; then
echo " Panel sifre: ${GEN_PASSWORD}"
echo " ! Bu sifreyi simdi kaydedin; bir daha gosterilmez."
elif [ -n "${AGFO_STORE_PASSWORD:-}" ]; then
echo " Panel sifre: (AGFO_STORE_PASSWORD ile verdiginiz deger)"
else
echo " Panel sifre: (onceki kurulumdan korundu)"
fi
echo " CyberPanel : ${CP_CLI:-BULUNAMADI}"
echo " Servis     : systemctl status ${APP_SLUG}"
echo " Gunluk     : journalctl -u ${APP_SLUG} -f"
echo " Kaldirma   : bash ${INSTALL_DIR}/uninstall.sh"
echo
echo " ILK ADIM: Ayarlar sekmesinde 'Katalogu dogrula' ile indirme"
echo " adreslerinin bu sunucudan erisilebildigini kontrol edin."
echo "============================================================"
