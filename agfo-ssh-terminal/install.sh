#!/usr/bin/env bash
# =============================================================================
# AGFO SSH Terminal - kurulum betigi
# CyberPanel sunucularinda AGFO Package Runner ile root olarak calistirilir.
# tty gerektirmez, hicbir soru sormaz; tum ayarlar ortam degiskeni ile verilir.
#
# Ortam degiskenleri (hepsi istege bagli):
#   AGFO_SSH_PORT=8822          dinlenecek port
#   AGFO_SSH_BIND=0.0.0.0       dinlenecek adres (yalniz yerel icin 127.0.0.1)
#   AGFO_SSH_PASSWORD=...       panel sifresi (verilmezse rastgele uretilir)
#   AGFO_SSH_TLS=1              1=HTTPS (varsayilan), 0=HTTP
#   AGFO_SSH_DOMAIN=agfocert.net
#                               panele bu alan adiyla erisilir; CyberPanel'in
#                               mevcut Let's Encrypt sertifikasi otomatik
#                               bulunur, boylece tarayici uyarisi cikmaz.
#   AGFO_SSH_CERT=/yol/fullchain.pem
#   AGFO_SSH_KEY=/yol/privkey.pem
#   AGFO_SSH_ALLOW_IPS=1.2.3.4,5.6.7.*   bos ise herkese acik
#   AGFO_SSH_SESSION_LOG=0      1=oturum kayitlarini sunucuda tut
#   AGFO_SSH_SKIP_FIREWALL=0    1=guvenlik duvarina dokunma
#   AGFO_SSH_FRAME_ANCESTORS="https://IP:8090"
#                               paneli cerceve (iframe) icinde gosterebilecek
#                               adresler; CyberPanel icine gommek icin gerekli.
#                               Bos deger vermek izni kaldirir.
#   AGFO_SSH_COOKIE_SAMESITE=Strict
#                               farkli bir ALAN ADI altindan cerceveleme icin
#                               "None" (TLS sart); ayni host'un baska portu icin
#                               Strict yeterlidir.
# =============================================================================
set -euo pipefail

APP_NAME="AGFO SSH Terminal"
APP_SLUG="agfo-ssh-terminal"
APP_VERSION="1.3.2"
INSTALL_DIR="/opt/${APP_SLUG}"
UNIT_PATH="/etc/systemd/system/${APP_SLUG}.service"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${AGFO_SSH_PORT:-8822}"
BIND="${AGFO_SSH_BIND:-0.0.0.0}"
TLS="${AGFO_SSH_TLS:-1}"
SESSION_LOG="${AGFO_SSH_SESSION_LOG:-0}"
ALLOW_IPS="${AGFO_SSH_ALLOW_IPS:-}"
SKIP_FW="${AGFO_SSH_SKIP_FIREWALL:-0}"
FRAME_SET=0; [ "${AGFO_SSH_FRAME_ANCESTORS+x}" = "x" ] && FRAME_SET=1
SAMESITE_SET=0; [ "${AGFO_SSH_COOKIE_SAMESITE+x}" = "x" ] && SAMESITE_SET=1

say()  { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
warn() { printf '[%s] UYARI: %s\n' "$APP_SLUG" "$*" >&2; }
die()  { printf '[%s] HATA: %s\n' "$APP_SLUG" "$*" >&2; exit 1; }

# --- 1. ortam kontrolleri --------------------------------------------------
[ "$(id -u)" = "0" ] || die "Bu betik root olarak calistirilmali."
say "${APP_NAME} ${APP_VERSION} kurulumu basliyor"
say "kaynak dizin: ${SRC_DIR}"

PYBIN=""
for cand in /usr/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,6) else 1)' 2>/dev/null; then
    PYBIN="$cand"; break
  fi
done
[ -n "$PYBIN" ] || die "Python 3.6+ bulunamadi. AlmaLinux: dnf -y install python3 | Ubuntu: apt -y install python3"
say "python: ${PYBIN} ($("$PYBIN" -V 2>&1))"

"$PYBIN" -c 'import pty, termios, fcntl, ssl, hashlib, http.server' 2>/dev/null \
  || die "Python standart kutuphanesi eksik (pty/termios/ssl). python3 kurulumunu kontrol edin."

if command -v ssh >/dev/null 2>&1; then
  say "ssh istemcisi: $(command -v ssh)"
else
  warn "ssh istemcisi yok -> yalnizca yerel root kabugu calisir."
  warn "kurmak icin: dnf -y install openssh-clients   (Debian/Ubuntu: apt -y install openssh-client)"
fi

[ -f "${SRC_DIR}/app/server.py" ] || die "Paket bozuk: app/server.py bulunamadi."

# --- 2. servisi durdur (yukseltme) -----------------------------------------
if systemctl list-unit-files 2>/dev/null | grep -q "^${APP_SLUG}.service"; then
  say "mevcut servis durduruluyor (yukseltme)"
  systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
fi

# --- 3. dosyalari kopyala ---------------------------------------------------
say "dosyalar ${INSTALL_DIR} dizinine kopyalaniyor"
mkdir -p "${INSTALL_DIR}/config/keys" "${INSTALL_DIR}/config/tls"
rm -rf "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/app" "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/uninstall.sh" "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
cp -a "${SRC_DIR}/README.md" "${INSTALL_DIR}/README.md" 2>/dev/null || true
printf '%s\n' "$APP_VERSION" > "${INSTALL_DIR}/VERSION"

# Runner'in calisma dizini baska kullanicilar tarafindan okunamaz; bu nedenle
# tum islemler kopyalandiktan sonra INSTALL_DIR uzerinden yurutulur.
chown -R root:root "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}" "${INSTALL_DIR}/app"
chmod 700 "${INSTALL_DIR}/config" "${INSTALL_DIR}/config/keys" "${INSTALL_DIR}/config/tls"
find "${INSTALL_DIR}/app" -type f -exec chmod 644 {} \;
find "${INSTALL_DIR}/app" -type d -exec chmod 755 {} \;
chmod 644 "${INSTALL_DIR}/app/server.py"

# --- 4. TLS sertifikasi -----------------------------------------------------
CERT="${AGFO_SSH_CERT:-}"
KEY="${AGFO_SSH_KEY:-}"
DOMAIN="${AGFO_SSH_DOMAIN:-}"

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
  # --- alan adi bu sunucuyu mu gosteriyor? ---
  LOCAL_IPS="$(hostname -I 2>/dev/null || true)"
  DOM_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
  if [ -n "$DOM_IP" ]; then
    if printf '%s\n' $LOCAL_IPS | grep -qx "$DOM_IP"; then
      say "DNS: ${DOMAIN} -> ${DOM_IP} (bu sunucu)"
    else
      warn "DNS: ${DOMAIN} -> ${DOM_IP}, bu sunucunun adresleri: ${LOCAL_IPS}"
      warn "Alan adi baska bir sunucuya isaret ediyor; panele bu adresten ulasilamayabilir."
    fi
  else
    warn "DNS: ${DOMAIN} cozumlenemedi; kuruluma devam ediliyor."
  fi

  # --- CyberPanel/Let's Encrypt sertifikasini ara ---
  for base in "/etc/letsencrypt/live/${DOMAIN}" "/etc/letsencrypt/live/${DOMAIN}-0001" \
              "/usr/local/lsws/conf/vhosts/${DOMAIN}" "/etc/letsencrypt/live/www.${DOMAIN}"; do
    if [ -f "${base}/fullchain.pem" ] && [ -f "${base}/privkey.pem" ]; then
      CERT="${base}/fullchain.pem"; KEY="${base}/privkey.pem"
      say "sertifika bulundu: ${CERT}"
      break
    fi
  done
  if [ -z "$CERT" ]; then
    warn "${DOMAIN} icin hazir sertifika bulunamadi; kendinden imzali kullanilacak."
    warn "CyberPanel > SSL > Manage SSL ile sertifika cikarip bu paketi tekrar calistirin."
  fi
fi

if [ "$TLS" = "1" ]; then
  if [ -n "$CERT" ] && [ -n "$KEY" ]; then
    [ -f "$CERT" ] || die "Sertifika bulunamadi: $CERT"
    [ -f "$KEY" ]  || die "Anahtar bulunamadi: $KEY"
    say "verilen TLS sertifikasi kullanilacak: $CERT"
  else
    CERT="${INSTALL_DIR}/config/tls/server.crt"
    KEY="${INSTALL_DIR}/config/tls/server.key"
    if [ -f "$CERT" ] && [ -f "$KEY" ]; then
      say "mevcut kendinden imzali sertifika korunuyor"
    else
      command -v openssl >/dev/null 2>&1 || die "openssl bulunamadi; TLS sertifikasi uretilemiyor (AGFO_SSH_TLS=0 ile HTTP deneyin)."
      say "kendinden imzali sertifika uretiliyor (3650 gun)"
      openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout "$KEY" -out "$CERT" \
        -subj "/C=TR/O=AGFO/CN=$(hostname -f 2>/dev/null || hostname)" \
        -addext "subjectAltName=DNS:$(hostname -f 2>/dev/null || hostname),IP:127.0.0.1" \
        >/dev/null 2>&1 || die "openssl sertifika uretemedi."
      chmod 600 "$KEY"; chmod 644 "$CERT"
    fi
  fi
fi

# --- 5. yapilandirma --------------------------------------------------------
SCHEME="http"; [ "$TLS" = "1" ] && SCHEME="https"
SRV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$SRV_IP" ] || SRV_IP="SUNUCU-IP"
if [ -n "$DOMAIN" ]; then
  PUBLIC_URL="${SCHEME}://${DOMAIN}:${PORT}/"
else
  PUBLIC_URL="${SCHEME}://${SRV_IP}:${PORT}/"
fi

# Menu linkinde kullanilacak otomatik giris jetonu (sifreden bagimsiz).
EXISTING_TOKEN=""
if [ -f "${INSTALL_DIR}/config/config.json" ]; then
  EXISTING_TOKEN="$("$PYBIN" -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json')).get('auth',{}).get('login_token',''))" 2>/dev/null || true)"
fi
LOGIN_TOKEN="${EXISTING_TOKEN}"
if [ -z "$LOGIN_TOKEN" ]; then
  LOGIN_TOKEN="$("$PYBIN" -c 'import secrets;print(secrets.token_urlsafe(32))')"
fi

say "config.json yaziliyor"
# Yukseltmede mevcut sifre korunur: yalnizca hic sifre yoksa yenisi uretilir.
EXISTING_HASH=""
if [ -f "${INSTALL_DIR}/config/config.json" ]; then
  EXISTING_HASH="$("$PYBIN" -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json')).get('auth',{}).get('password_hash',''))" 2>/dev/null || true)"
fi
GEN_PASSWORD=""
if [ -z "${AGFO_SSH_PASSWORD:-}" ] && [ -z "$EXISTING_HASH" ]; then
  GEN_PASSWORD="$("$PYBIN" -c 'import secrets,string;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(20)))')"
fi

AGFO_SSH_PASSWORD="${AGFO_SSH_PASSWORD:-$GEN_PASSWORD}" \
AGFO_CFG_PORT="$PORT" AGFO_CFG_BIND="$BIND" AGFO_CFG_TLS="$TLS" \
AGFO_CFG_CERT="${CERT:-}" AGFO_CFG_KEY="${KEY:-}" \
AGFO_CFG_ALLOW="$ALLOW_IPS" AGFO_CFG_ALLOW_SET="${AGFO_SSH_ALLOW_IPS+1}" AGFO_CFG_LOG="$SESSION_LOG" \
AGFO_CFG_PUBLIC="$PUBLIC_URL" \
AGFO_CFG_FRAME="${AGFO_SSH_FRAME_ANCESTORS:-}" AGFO_CFG_FRAME_SET="$FRAME_SET" \
AGFO_CFG_SAMESITE="${AGFO_SSH_COOKIE_SAMESITE:-}" AGFO_CFG_SAMESITE_SET="$SAMESITE_SET" \
AGFO_CFG_TOKEN="$LOGIN_TOKEN" AGFO_CFG_DIR="${INSTALL_DIR}/config" AGFO_CFG_APP="${INSTALL_DIR}/app" \
"$PYBIN" - <<'PYEOF'
import json, os, sys

app_dir = os.environ["AGFO_CFG_APP"]
cfg_dir = os.environ["AGFO_CFG_DIR"]
sys.path.insert(0, app_dir)
import server  # hash_password ve DEFAULT_CONFIG icin

path = os.path.join(cfg_dir, "config.json")
existing = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            existing = json.load(fh)
    except Exception as exc:
        print("[agfo-ssh-terminal] UYARI: eski config okunamadi (%s), yenisi yazilacak" % exc)
        existing = {}

cfg = server.deep_merge(server.DEFAULT_CONFIG, existing)
cfg["bind"] = os.environ["AGFO_CFG_BIND"]
cfg["port"] = int(os.environ["AGFO_CFG_PORT"])
cfg["tls"]["enabled"] = os.environ["AGFO_CFG_TLS"] == "1"
if os.environ.get("AGFO_CFG_CERT"):
    cfg["tls"]["cert"] = os.environ["AGFO_CFG_CERT"]
    cfg["tls"]["key"] = os.environ["AGFO_CFG_KEY"]
allow = [x.strip() for x in (os.environ.get("AGFO_CFG_ALLOW") or "").split(",") if x.strip()]
if os.environ.get("AGFO_CFG_ALLOW_SET") == "1" or not existing:
    cfg["allow_ips"] = allow  # verilmediyse mevcut IP kilidi korunur
cfg["session_log"]["enabled"] = os.environ["AGFO_CFG_LOG"] == "1"
cfg["public_url"] = os.environ.get("AGFO_CFG_PUBLIC") or ""

if os.environ.get("AGFO_CFG_FRAME_SET") == "1":
    cfg["frame_ancestors"] = [x.strip() for x in (os.environ.get("AGFO_CFG_FRAME") or "").split(",") if x.strip()]
    if cfg["frame_ancestors"]:
        print("[agfo-ssh-terminal] cerceveleme izni: %s" % ", ".join(cfg["frame_ancestors"]))
    else:
        print("[agfo-ssh-terminal] cerceveleme izni kaldirildi")
if os.environ.get("AGFO_CFG_SAMESITE_SET") == "1":
    val = (os.environ.get("AGFO_CFG_SAMESITE") or "Strict").capitalize()
    if val not in ("Strict", "Lax", "None"):
        val = "Strict"
    cfg["cookie_samesite"] = val
    print("[agfo-ssh-terminal] cerez SameSite=%s" % val)

cfg["auth"]["login_token"] = os.environ.get("AGFO_CFG_TOKEN") or cfg["auth"].get("login_token") or ""

pw = os.environ.get("AGFO_SSH_PASSWORD") or ""
if pw:
    cfg["auth"]["password_hash"] = server.hash_password(pw)
    print("[agfo-ssh-terminal] panel sifresi ayarlandi")
elif not cfg["auth"].get("password_hash"):
    print("[agfo-ssh-terminal] HATA: sifre yok ve uretilemedi")
    raise SystemExit(1)
else:
    print("[agfo-ssh-terminal] mevcut panel sifresi korunuyor")

with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
os.chmod(path, 0o600)

prof = os.path.join(cfg_dir, "profiles.json")
if not os.path.exists(prof):
    with open(prof, "w", encoding="utf-8") as fh:
        json.dump([], fh)
    os.chmod(prof, 0o600)
PYEOF

if [ "$SESSION_LOG" = "1" ]; then
  mkdir -p /var/log/${APP_SLUG}/sessions
  chmod 700 /var/log/${APP_SLUG} /var/log/${APP_SLUG}/sessions
fi

# --- 6. systemd servisi -----------------------------------------------------
say "systemd servisi kuruluyor"
sed -e "s#@PYBIN@#${PYBIN}#g" -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" \
    "${SRC_DIR}/systemd/${APP_SLUG}.service" > "$UNIT_PATH"
chmod 644 "$UNIT_PATH"

# Disaridan verilen (Let's Encrypt) sertifika kullaniliyorsa: yenilendiginde
# servisi tazeleyen gunluk denetimi kur.
SELF_SIGNED="${INSTALL_DIR}/config/tls/server.crt"
if [ "$TLS" = "1" ] && [ -n "$CERT" ] && [ "$CERT" != "$SELF_SIGNED" ]; then
  sed -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" \
      "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.service" > "/etc/systemd/system/${APP_SLUG}-certwatch.service"
  cp -a "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.timer" "/etc/systemd/system/${APP_SLUG}-certwatch.timer"
  chmod 644 "/etc/systemd/system/${APP_SLUG}-certwatch."*
  chmod +x "${INSTALL_DIR}/app/certwatch.sh"
  CERTWATCH=1
  say "sertifika yenileme denetimi kuruldu (gunluk)"
else
  systemctl disable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${APP_SLUG}-certwatch.service" "/etc/systemd/system/${APP_SLUG}-certwatch.timer"
  CERTWATCH=0
fi

systemctl daemon-reload
systemctl enable "${APP_SLUG}.service" >/dev/null 2>&1 || true
systemctl restart "${APP_SLUG}.service"
if [ "${CERTWATCH}" = "1" ]; then
  systemctl enable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true
fi

# --- 7. guvenlik duvari -----------------------------------------------------
if [ "$SKIP_FW" != "1" ] && [ "$BIND" != "127.0.0.1" ]; then
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    say "firewalld: ${PORT}/tcp aciliyor"
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
  elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    say "ufw: ${PORT}/tcp aciliyor"
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  elif [ -f /etc/csf/csf.conf ]; then
    warn "CSF tespit edildi. TCP_IN listesine ${PORT} portunu elle ekleyip 'csf -r' calistirin."
  else
    say "aktif guvenlik duvari bulunamadi; port kontrolu gerekmiyor"
  fi
fi

# --- 8. durum ---------------------------------------------------------------
sleep 1.5
if ! systemctl is-active --quiet "${APP_SLUG}.service"; then
  warn "servis baslatilamadi. Son gunluk:"
  journalctl -u "${APP_SLUG}.service" -n 30 --no-pager 2>/dev/null || true
  die "kurulum tamamlanamadi"
fi

echo
echo "============================================================"
echo " ${APP_NAME} ${APP_VERSION} kuruldu ve calisiyor"
echo "============================================================"
echo " Adres      : ${PUBLIC_URL}"
if [ "$BIND" = "127.0.0.1" ]; then
echo " NOT        : yalniz 127.0.0.1 dinleniyor; ters vekil veya SSH tuneli gerekir"
fi
if [ -n "$GEN_PASSWORD" ]; then
echo " Panel sifre: ${GEN_PASSWORD}"
echo " ! Bu sifreyi simdi kaydedin; bir daha gosterilmez."
elif [ -n "${AGFO_SSH_PASSWORD:-}" ]; then
echo " Panel sifre: (AGFO_SSH_PASSWORD ile verdiginiz deger)"
else
echo " Panel sifre: (onceki kurulumdan korundu)"
fi
echo " Erisim     : panel root yetkisiyle calisir (yerel root kabugu dahil)"
echo " Menu linki : ${PUBLIC_URL}?t=${LOGIN_TOKEN}&open=root"
echo "              (yeni sekmede acin; tiklayinca dogrudan root kabugu gelir)"
echo " Servis     : systemctl status ${APP_SLUG}"
echo " Gunluk     : journalctl -u ${APP_SLUG} -f"
echo " Ayarlar    : ${INSTALL_DIR}/config/config.json"
echo " Kaldirma   : bash ${INSTALL_DIR}/uninstall.sh"
if [ "$TLS" = "1" ] && [ "$CERT" = "${INSTALL_DIR}/config/tls/server.crt" ]; then
echo " TLS        : kendinden imzali sertifika (tarayici uyarisi normaldir)"
elif [ "$TLS" = "1" ]; then
echo " TLS        : ${CERT}"
echo "              (yenilendiginde servis kendiliginden tazelenir)"
fi
echo "============================================================"
