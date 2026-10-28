#!/usr/bin/env bash
# =============================================================================
# AGFO File Manager - kurulum betigi
# Root yetkili web dosya yoneticisi (Tiny File Manager uyarlamasi + AGFO on panel).
# CyberPanel sunucularinda AGFO Package Runner ile root olarak calistirilir.
#
# Ortam degiskenleri (hepsi istege bagli):
#   AGFO_FM_PORT=8826               panel portu
#   AGFO_FM_BIND=0.0.0.0            dinlenecek adres
#   AGFO_FM_PASSWORD=...            panel sifresi (yoksa uretilir, korunur)
#   AGFO_FM_DOMAIN=alanadi.com      TLS icin alan adi (verilmezse CyberPanel'in
#                                   8090 sertifikasindan okunur)
#   AGFO_FM_CERT / AGFO_FM_KEY      sertifikayi elle vermek icin
#   AGFO_FM_TLS=1                   0 = duz HTTP (onerilmez)
#   AGFO_FM_ALLOW_IPS=1.2.3.4       panele erisebilecek IP'ler (onerilir)
#   AGFO_FM_PHP=8.3                 arka uc icin lsphp surumu (verilmezse en yenisi)
#   AGFO_FM_TIMEZONE=Europe/Istanbul
#   AGFO_FM_SKIP_FIREWALL=0         1 = guvenlik duvarina dokunma
# =============================================================================
set -euo pipefail

APP_NAME="AGFO File Manager"
APP_SLUG="agfo-file-manager"
APP_VERSION="1.0.0"
INSTALL_DIR="/opt/${APP_SLUG}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=18096

PORT="${AGFO_FM_PORT:-8826}"
BIND="${AGFO_FM_BIND:-0.0.0.0}"
TLS="${AGFO_FM_TLS:-1}"
DOMAIN="${AGFO_FM_DOMAIN:-}"
ALLOW_IPS="${AGFO_FM_ALLOW_IPS:-}"
SKIP_FW="${AGFO_FM_SKIP_FIREWALL:-0}"
CERT="${AGFO_FM_CERT:-}"
KEY="${AGFO_FM_KEY:-}"
TIMEZONE="${AGFO_FM_TIMEZONE:-Europe/Istanbul}"
LSPHP_TEMPLATE="${AGFO_FM_PHP_TEMPLATE:-/usr/local/lsws/lsphp@V@/bin/php}"

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
[ -f "${SRC_DIR}/www/index.php" ] && [ -f "${SRC_DIR}/app/server.py" ] || die "Paket bozuk."

# Arka uc icin PHP: istenen surum ya da kurulu en yeni lsphp (yerlesik sunucu -S gerekir).
PHPBIN=""
want="${AGFO_FM_PHP:-}"
for v in ${want:+${want/./}} 85 84 83 82 81; do
  cand="${LSPHP_TEMPLATE//@V@/$v}"
  if [ -x "$cand" ] && "$cand" -r 'exit(PHP_VERSION_ID >= 80100 ? 0 : 1);' 2>/dev/null; then
    PHPBIN="$cand"; break
  fi
done
if [ -z "$PHPBIN" ] && command -v php >/dev/null 2>&1; then PHPBIN="$(command -v php)"; fi
[ -n "$PHPBIN" ] || die "Uygun PHP (8.1+) bulunamadi. CyberPanel > PHP > Install PHP ile bir lsphp kurun."
PHPVER="$("$PHPBIN" -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;')"
say "arka uc PHP: ${PHPBIN} (${PHPVER})"
MODS="$("$PHPBIN" -m 2>/dev/null | tr 'A-Z' 'a-z')"
for ext in session json mbstring fileinfo; do
  printf '%s\n' "$MODS" | grep -qx "$ext" || warn "PHP ${PHPVER}'te '${ext}' eklentisi yok; bazi ozellikler calismayabilir."
done
for ext in zip posix iconv; do
  printf '%s\n' "$MODS" | grep -qx "$ext" || warn "PHP ${PHPVER}'te '${ext}' yok (zip acma / sahip adlari / karakter donusumu). CyberPanel > PHP > Install Extensions: lsphp${PHPVER/./}-${ext}"
done

# --- 2. dosyalar -------------------------------------------------------------
if systemctl list-unit-files 2>/dev/null | grep -q "^${APP_SLUG}.service"; then
  say "mevcut servis durduruluyor (yukseltme)"
  systemctl stop "${APP_SLUG}.service" "${APP_SLUG}-backend.service" 2>/dev/null || true
fi
say "dosyalar ${INSTALL_DIR} dizinine kopyalaniyor"
mkdir -p "${INSTALL_DIR}/config/tls" "${INSTALL_DIR}/sessions" "${INSTALL_DIR}/logs"
rm -rf "${INSTALL_DIR}/app" "${INSTALL_DIR}/www"
cp -a "${SRC_DIR}/app" "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/www" "${INSTALL_DIR}/www"
find "${INSTALL_DIR}/app" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp -a "${SRC_DIR}/README.md" "${SRC_DIR}/uninstall.sh" "${INSTALL_DIR}/" 2>/dev/null || true
printf '%s\n' "$APP_VERSION" > "${INSTALL_DIR}/VERSION"
chown -R root:root "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}" "${INSTALL_DIR}/app"
chmod 700 "${INSTALL_DIR}/config" "${INSTALL_DIR}/config/tls" "${INSTALL_DIR}/sessions" "${INSTALL_DIR}/logs" "${INSTALL_DIR}/www"
find "${INSTALL_DIR}/app" -type f -exec chmod 644 {} \;
find "${INSTALL_DIR}/app" -type d -exec chmod 755 {} \;
chmod +x "${INSTALL_DIR}/app/certwatch.sh"

# --- 3. TLS ------------------------------------------------------------------
if [ "$TLS" = "1" ] && [ -z "$DOMAIN" ] && [ -z "$CERT" ] && command -v openssl >/dev/null 2>&1; then
  for pc in /usr/local/lscp/conf/cert.pem /usr/local/lscp/conf/server.crt; do
    [ -f "$pc" ] || continue
    cand="$(openssl x509 -in "$pc" -noout -ext subjectAltName 2>/dev/null \
            | tr ',' '\n' | sed -n 's/^ *DNS://p' | grep -v '^\*' | head -1 || true)"
    if [ -n "$cand" ]; then DOMAIN="$cand"; say "alan adi CyberPanel sertifikasindan alindi: ${DOMAIN}"; break; fi
  done
fi
if [ "$TLS" = "1" ] && [ -n "$DOMAIN" ] && [ -z "$CERT" ]; then
  for base in "/etc/letsencrypt/live/${DOMAIN}" "/etc/letsencrypt/live/${DOMAIN}-0001" \
              "/usr/local/lsws/conf/vhosts/${DOMAIN}" "/etc/letsencrypt/live/www.${DOMAIN}"; do
    if [ -f "${base}/fullchain.pem" ] && [ -f "${base}/privkey.pem" ]; then
      CERT="${base}/fullchain.pem"; KEY="${base}/privkey.pem"; say "sertifika bulundu: ${CERT}"; break
    fi
  done
  [ -n "$CERT" ] || warn "${DOMAIN} icin Let's Encrypt sertifikasi bulunamadi; kendinden imzali kullanilacak."
fi
if [ "$TLS" = "1" ]; then
  if [ -n "$CERT" ] && [ -n "$KEY" ]; then
    [ -f "$CERT" ] && [ -f "$KEY" ] || die "Sertifika dosyalari bulunamadi."
  else
    CERT="${INSTALL_DIR}/config/tls/server.crt"; KEY="${INSTALL_DIR}/config/tls/server.key"
    if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
      command -v openssl >/dev/null 2>&1 || die "openssl yok; AGFO_FM_TLS=0 deneyin."
      HN="$(hostname -f 2>/dev/null || hostname)"
      openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes -keyout "$KEY" -out "$CERT" \
        -subj "/C=TR/O=AGFO/CN=${HN}" -addext "subjectAltName=DNS:${HN},IP:127.0.0.1" >/dev/null 2>&1 \
        || die "sertifika uretilemedi."
      chmod 600 "$KEY"; chmod 644 "$CERT"
    fi
  fi
fi

# --- 4. yapilandirma ---------------------------------------------------------
SCHEME="http"; [ "$TLS" = "1" ] && SCHEME="https"
SRV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$SRV_IP" ] || SRV_IP="SUNUCU-IP"
if [ -n "$DOMAIN" ]; then PUBLIC_URL="${SCHEME}://${DOMAIN}:${PORT}/"; else PUBLIC_URL="${SCHEME}://${SRV_IP}:${PORT}/"; fi

say "config.json yaziliyor"
OUT="$(AGFO_FM_PASSWORD="${AGFO_FM_PASSWORD:-}" AGFO_CFG_PORT="$PORT" AGFO_CFG_BIND="$BIND" AGFO_CFG_TLS="$TLS" \
AGFO_CFG_CERT="${CERT:-}" AGFO_CFG_KEY="${KEY:-}" AGFO_CFG_ALLOW="$ALLOW_IPS" AGFO_CFG_PUBLIC="$PUBLIC_URL" \
AGFO_CFG_BPORT="$BACKEND_PORT" AGFO_FM_CONFIG_DIR="${INSTALL_DIR}/config" AGFO_CFG_APP="${INSTALL_DIR}/app" \
"$PYBIN" - <<'PYEOF'
import json, os, secrets, string, sys
sys.path.insert(0, os.environ["AGFO_CFG_APP"])
import server
path = server.CONFIG_PATH
cfg = server.load_config()
cfg["bind"] = os.environ["AGFO_CFG_BIND"]
cfg["port"] = int(os.environ["AGFO_CFG_PORT"])
cfg["public_url"] = os.environ.get("AGFO_CFG_PUBLIC") or ""
cfg["tls"]["enabled"] = os.environ["AGFO_CFG_TLS"] == "1"
if os.environ.get("AGFO_CFG_CERT"):
    cfg["tls"]["cert"], cfg["tls"]["key"] = os.environ["AGFO_CFG_CERT"], os.environ["AGFO_CFG_KEY"]
cfg["allow_ips"] = [x.strip() for x in (os.environ.get("AGFO_CFG_ALLOW") or "").split(",") if x.strip()]
cfg["backend"]["host"] = "127.0.0.1"
cfg["backend"]["port"] = int(os.environ["AGFO_CFG_BPORT"])
cfg["backend"]["key"] = cfg["backend"].get("key") or secrets.token_urlsafe(48)
cfg["auth"]["login_token"] = cfg["auth"].get("login_token") or secrets.token_urlsafe(32)
generated = ""
given = os.environ.get("AGFO_FM_PASSWORD") or ""
if given:
    cfg["auth"]["password_hash"] = server.hash_password(given)
elif not cfg["auth"].get("password_hash"):
    generated = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    cfg["auth"]["password_hash"] = server.hash_password(generated)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("KEY=%s" % cfg["backend"]["key"])
print("TOKEN=%s" % cfg["auth"]["login_token"])
print("GENPW=%s" % generated)
PYEOF
)"
BKEY="$(printf '%s\n' "$OUT" | sed -n 's/^KEY=//p')"
LOGIN_TOKEN="$(printf '%s\n' "$OUT" | sed -n 's/^TOKEN=//p')"
GEN_PASSWORD="$(printf '%s\n' "$OUT" | sed -n 's/^GENPW=//p')"
[ -n "$BKEY" ] || die "yapilandirma yazilamadi."

# Tiny File Manager ayarlari: gizli anahtarla (yalniz on panel erisebilir).
sed -e "s#@BACKEND_KEY@#${BKEY}#" -e "s#@TIMEZONE@#${TIMEZONE}#" \
    "${SRC_DIR}/config/tfm-config.php.tmpl" > "${INSTALL_DIR}/www/config.php"
chmod 600 "${INSTALL_DIR}/www/config.php"
"$PHPBIN" -l "${INSTALL_DIR}/www/config.php" >/dev/null || die "config.php sozdizimi hatali."

# --- 5. servisler ------------------------------------------------------------
say "systemd servisleri kuruluyor"
for unit in "${APP_SLUG}" "${APP_SLUG}-backend"; do
  sed -e "s#@PYBIN@#${PYBIN}#g" -e "s#@PHPBIN@#${PHPBIN}#g" -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" \
      -e "s#@BACKEND_PORT@#${BACKEND_PORT}#g" -e "s#@TIMEZONE@#${TIMEZONE}#g" \
      "${SRC_DIR}/systemd/${unit}.service" > "/etc/systemd/system/${unit}.service"
  chmod 644 "/etc/systemd/system/${unit}.service"
done
CERTWATCH=0
if [ "$TLS" = "1" ] && [ "$CERT" != "${INSTALL_DIR}/config/tls/server.crt" ]; then
  sed -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.service" \
      > "/etc/systemd/system/${APP_SLUG}-certwatch.service"
  cp -a "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.timer" "/etc/systemd/system/"
  chmod 644 "/etc/systemd/system/${APP_SLUG}-certwatch."*
  CERTWATCH=1
fi
systemctl daemon-reload
systemctl enable "${APP_SLUG}-backend.service" "${APP_SLUG}.service" >/dev/null 2>&1 || true
systemctl restart "${APP_SLUG}-backend.service"
systemctl restart "${APP_SLUG}.service"
[ "$CERTWATCH" = "1" ] && systemctl enable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true

# --- 6. guvenlik duvari ------------------------------------------------------
if [ "$SKIP_FW" != "1" ] && [ "$BIND" != "127.0.0.1" ]; then
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    say "firewalld: ${PORT}/tcp aciliyor"
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    systemctl try-restart crowdsec-firewall-bouncer >/dev/null 2>&1 || true
  elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  fi
fi

# --- 7. dogrulama ------------------------------------------------------------
sleep 2
for unit in "${APP_SLUG}-backend" "${APP_SLUG}"; do
  if ! systemctl is-active --quiet "${unit}.service"; then
    journalctl -u "${unit}.service" -n 30 --no-pager 2>/dev/null || true
    die "${unit} servisi baslatilamadi"
  fi
done
# Arka uc anahtarsiz istegi reddetmeli; anahtarla kabul etmeli.
if command -v curl >/dev/null 2>&1; then
  NOKEY="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:${BACKEND_PORT}/" || true)"
  WITHKEY="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "X-AGFO-FM-Key: ${BKEY}" "http://127.0.0.1:${BACKEND_PORT}/" || true)"
  if [ "$NOKEY" != "403" ]; then
    systemctl stop "${APP_SLUG}.service" "${APP_SLUG}-backend.service" >/dev/null 2>&1 || true
    die "GUVENLIK: arka uc anahtarsiz istege ${NOKEY} dondu (403 olmali). Servisler durduruldu."
  fi
  case "$WITHKEY" in 200|302) ;; *) warn "arka uc anahtarli istege ${WITHKEY} dondu; journalctl -u ${APP_SLUG}-backend ile bakin." ;; esac
  say "erisim denetimi: anahtarsiz ${NOKEY}, anahtarli ${WITHKEY}"
fi

echo
echo "============================================================"
echo " ${APP_NAME} ${APP_VERSION} kuruldu"
echo "============================================================"
echo " Panel      : ${PUBLIC_URL}"
echo " Menu linki : ${PUBLIC_URL}?t=${LOGIN_TOKEN}"
if [ -n "$GEN_PASSWORD" ]; then
echo " Panel sifre: ${GEN_PASSWORD}"
echo " ! Bu sifreyi simdi kaydedin; bir daha gosterilmez."
else
echo " Panel sifre: (onceki kurulumdan korundu ya da AGFO_FM_PASSWORD ile verildi)"
fi
echo " Kok dizin  : / (tum sunucu, root yetkisiyle)"
echo " Arka uc    : ${PHPBIN} -> 127.0.0.1:${BACKEND_PORT} (disariya kapali)"
echo " Kaldirma   : bash ${INSTALL_DIR}/uninstall.sh"
echo
[ -z "$ALLOW_IPS" ] && echo " ONERI: AGFO_FM_ALLOW_IPS ile paneli sabit IP'nize kilitleyin."
echo " Menuye eklemek icin agfo-ssh-menu paketini (1.5.0+) calistirin."
echo "============================================================"
