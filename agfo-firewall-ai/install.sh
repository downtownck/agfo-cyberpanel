#!/usr/bin/env bash
# =============================================================================
# AGFO Firewall AI - kurulum betigi
# CyberPanel sunucularinda AGFO Package Runner ile root olarak calistirilir.
# tty gerektirmez, soru sormaz.
#
# Ortam degiskenleri (hepsi istege bagli):
#   AGFO_FW_PORT=8823              panel portu
#   AGFO_FW_BIND=0.0.0.0           dinlenecek adres
#   AGFO_FW_PASSWORD=...           panel sifresi (yoksa uretilir, korunur)
#   AGFO_FW_DOMAIN=alanadi.com     TLS sertifikasi bu alan adindan bulunur
#   AGFO_FW_CERT / AGFO_FW_KEY     sertifikayi elle vermek icin
#   AGFO_FW_TLS=1                  0 = duz HTTP
#   AGFO_FW_ALLOW_IPS=1.2.3.4      panele erisebilecek IP'ler
#   AGFO_FW_INSTALL_CROWDSEC=1     0 = CrowdSec kurulumunu atla
#   AGFO_FW_BOUNCER=auto           auto | nftables | iptables | none
#   AGFO_FW_SKIP_FIREWALL=0        1 = guvenlik duvarina dokunma
#   AGFO_FW_FRAME_ANCESTORS="https://IP:8090"
#                                  paneli CyberPanel sayfasi icinde cerceve
#                                  (iframe) olarak gostermek icin
# =============================================================================
set -euo pipefail

APP_NAME="AGFO Firewall AI"
APP_SLUG="agfo-firewall-ai"
APP_VERSION="1.1.1"
INSTALL_DIR="/opt/${APP_SLUG}"
UNIT_PATH="/etc/systemd/system/${APP_SLUG}.service"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${AGFO_FW_PORT:-8823}"
BIND="${AGFO_FW_BIND:-0.0.0.0}"
TLS="${AGFO_FW_TLS:-1}"
DOMAIN="${AGFO_FW_DOMAIN:-}"
ALLOW_IPS="${AGFO_FW_ALLOW_IPS:-}"
DO_CROWDSEC="${AGFO_FW_INSTALL_CROWDSEC:-1}"
BOUNCER="${AGFO_FW_BOUNCER:-auto}"
SKIP_FW="${AGFO_FW_SKIP_FIREWALL:-0}"
CERT="${AGFO_FW_CERT:-}"
KEY="${AGFO_FW_KEY:-}"

say()  { printf '[%s] %s\n' "$APP_SLUG" "$*"; }
warn() { printf '[%s] UYARI: %s\n' "$APP_SLUG" "$*" >&2; }
die()  { printf '[%s] HATA: %s\n' "$APP_SLUG" "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "root olarak calistirilmali."
say "${APP_NAME} ${APP_VERSION} kurulumu basliyor"

# --- 1. python ---------------------------------------------------------------
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

# --- 2. CrowdSec -------------------------------------------------------------
have_cscli() { command -v cscli >/dev/null 2>&1; }

install_crowdsec() {
  if have_cscli; then
    say "CrowdSec zaten kurulu: $(cscli version 2>/dev/null | head -1)"
    return 0
  fi
  if [ "$DO_CROWDSEC" != "1" ]; then
    warn "CrowdSec kurulu degil ve kurulum atlandi (AGFO_FW_INSTALL_CROWDSEC=0)."
    return 0
  fi
  command -v apt-get >/dev/null 2>&1 || {
    warn "apt-get yok; CrowdSec'i elle kurun: https://docs.crowdsec.net"
    return 0
  }
  say "CrowdSec deposu ekleniyor"
  export DEBIAN_FRONTEND=noninteractive
  if ! curl -fsSL https://install.crowdsec.net | bash >/dev/null 2>&1; then
    warn "Depo betigi calismadi; apt deposu olmadan devam ediliyor."
  fi
  apt-get update -qq || true
  say "CrowdSec kuruluyor"
  apt-get install -y -qq crowdsec >/dev/null || die "crowdsec paketi kurulamadi."
  have_cscli || die "Kurulum sonrasi cscli bulunamadi."
  say "CrowdSec kuruldu: $(cscli version 2>/dev/null | head -1)"
}

install_bouncer() {
  have_cscli || return 0
  [ "$BOUNCER" = "none" ] && { say "bouncer kurulumu atlandi"; return 0; }
  if systemctl list-units --type=service 2>/dev/null | grep -q 'firewall-bouncer'; then
    say "firewall bouncer zaten kurulu"; return 0
  fi
  command -v apt-get >/dev/null 2>&1 || return 0
  local pkg="$BOUNCER"
  if [ "$pkg" = "auto" ]; then
    # iptables surumu bilerek secildi: nftables surumu kararlardaki CIDR
    # maskesini dusurup (1.2.3.0/24 -> yalniz 1.2.3.0) aralik yasaklarini
    # etkisiz birakiyor. iptables surumu ipset "nethash" kullanir, aralik calisir.
    # Ubuntu 24.04'te iptables zaten nft arka ucuyla calisir; firewalld ile
    # ayri tablolarda yasadiklari icin catismazlar.
    pkg="iptables"
  fi
  say "firewall bouncer kuruluyor (${pkg})"
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -qq "crowdsec-firewall-bouncer-${pkg}" >/dev/null 2>&1 || {
    warn "crowdsec-firewall-bouncer-${pkg} kurulamadi; digeri deneniyor"
    local other="iptables"; [ "$pkg" = "iptables" ] && other="nftables"
    apt-get install -y -qq "crowdsec-firewall-bouncer-${other}" >/dev/null 2>&1 \
      || warn "bouncer kurulamadi; CrowdSec yalnizca tespit eder, engellemez."
  }
}

setup_acquisition() {
  have_cscli || return 0
  local dir="/etc/crowdsec/acquis.d"
  [ -d "$dir" ] || mkdir -p "$dir"

  # Not: paket kurulumu sirasinda "cscli setup unattended" sshd ve linux
  # kaynaklarini setup.*.yaml olarak kendisi yazar. Ayni dosyayi iki kez
  # okutmak CPU'yu bosa yakar; bu yuzden burada YALNIZCA OpenLiteSpeed
  # kaynaklarini tanimliyoruz ve kendi dosya adlarimizi kullaniyoruz.
  local vhost="${dir}/agfo-ols-vhosts.yaml"
  local server="${dir}/agfo-ols-server.yaml"

  if [ ! -f "$vhost" ]; then
    cat > "$vhost" <<'YAML'
# CyberPanel site erisim kayitlari: /home/<alanadi>/logs/<alanadi>.access_log
# Bicim Apache "combined" oldugu icin apache2 ayristiricisi kullanilir;
# litespeed ayristiricisi "%b" alani "-" olan satirlari (304/HEAD) reddeder.
source: file
filenames:
  - /home/*/logs/*.access_log
exclude_regexps:
  - '\.gz$'
  - '\.\d+$'
# Yeni site acildiginda yeniden baslatmaya gerek kalmasin:
discovery_poll_enable: true
discovery_poll_interval: 60s
labels:
  type: apache2
YAML
    chmod 644 "$vhost"
    say "log kaynagi: site erisim kayitlari (apache2)"
  else
    say "log kaynagi zaten tanimli: $vhost"
  fi

  if [ ! -f "$server" ] && [ -d /usr/local/lsws/logs ]; then
    cat > "$server" <<'YAML'
# OpenLiteSpeed sunucu ve yonetim kayitlari: litespeed ayristiricisi
# yonetim paneli giris denemelerini (litespeed-admin-bf) yakalar.
source: file
filenames:
  - /usr/local/lsws/logs/error.log
  - /usr/local/lsws/logs/access.log
  - /usr/local/lsws/admin/logs/*.log
exclude_regexps:
  - '\.gz$'
labels:
  type: litespeed
---
source: file
filenames:
  - /home/*/logs/*.error_log
exclude_regexps:
  - '\.gz$'
labels:
  type: litespeed
YAML
    chmod 644 "$server"
    say "log kaynagi: OpenLiteSpeed sunucu/yonetim kayitlari (litespeed)"
  fi

  # sshd hic tanimli degilse (unattended setup calismadiysa) biz ekleyelim.
  if ! grep -rqs "ssh" "${dir}" /etc/crowdsec/acquis.yaml 2>/dev/null; then
    cat > "${dir}/agfo-sshd.yaml" <<'YAML'
source: journalctl
journalctl_filter:
  - "_SYSTEMD_UNIT=ssh.service"
labels:
  type: syslog
YAML
    chmod 644 "${dir}/agfo-sshd.yaml"
    say "log kaynagi: sshd (journal)"
  fi
}

install_collections() {
  have_cscli || return 0
  # linux -> sshd + whitelist-good-actors; apache2/litespeed -> base-http-scenarios + http-cve
  local wanted="crowdsecurity/linux crowdsecurity/apache2 crowdsecurity/litespeed crowdsecurity/wordpress crowdsecurity/http-dos"
  cscli hub update >/dev/null 2>&1 || true
  local installed; installed="$(cscli collections list -o json 2>/dev/null || echo '')"
  for coll in $wanted; do
    if printf '%s' "$installed" | grep -q "\"$coll\""; then continue; fi
    if cscli collections install "$coll" >/dev/null 2>&1; then
      say "koleksiyon kuruldu: $coll"
    else
      warn "koleksiyon kurulamadi: $coll"
    fi
  done
}

check_conflicts() {
  if [ -f /etc/csf/csf.conf ]; then
    warn "CSF tespit edildi. CSF iptables kurallarini agresif yonetir ve bouncer ile"
    warn "catisabilir. Bu sunucuda tek guvenlik duvari olarak firewalld onerilir."
  fi
  if [ -f /etc/firewalld/firewalld.conf ]; then
    if grep -qi '^FirewallBackend=iptables' /etc/firewalld/firewalld.conf; then
      warn "firewalld 'iptables' arka ucunda. 'nftables' onerilir; aksi halde"
      warn "firewall-cmd --reload bouncer kurallarini dusurebilir."
    fi
  fi
}

validate_crowdsec() {
  have_cscli || return 0
  if command -v crowdsec >/dev/null 2>&1; then
    if crowdsec -t >/dev/null 2>&1; then
      say "CrowdSec yapilandirmasi dogrulandi"
    else
      warn "CrowdSec yapilandirma dogrulamasi basarisiz; 'crowdsec -t' ciktisina bakin."
    fi
  fi
}

check_conflicts
install_crowdsec
install_bouncer
setup_acquisition
install_collections
validate_crowdsec
if have_cscli; then
  systemctl restart crowdsec 2>/dev/null || true
  systemctl enable crowdsec >/dev/null 2>&1 || true
  for unit in crowdsec-firewall-bouncer crowdsec-firewall-bouncer-nftables crowdsec-firewall-bouncer-iptables; do
    systemctl enable --now "$unit" >/dev/null 2>&1 || true
  done
fi

# --- 3. panel dosyalari ------------------------------------------------------
if systemctl list-unit-files 2>/dev/null | grep -q "^${APP_SLUG}.service"; then
  say "mevcut panel servisi durduruluyor (yukseltme)"
  systemctl stop "${APP_SLUG}.service" 2>/dev/null || true
fi
say "dosyalar ${INSTALL_DIR} dizinine kopyalaniyor"
mkdir -p "${INSTALL_DIR}/config/tls"
rm -rf "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/app" "${INSTALL_DIR}/app"
cp -a "${SRC_DIR}/README.md" "${INSTALL_DIR}/README.md" 2>/dev/null || true
cp -a "${SRC_DIR}/uninstall.sh" "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
printf '%s\n' "$APP_VERSION" > "${INSTALL_DIR}/VERSION"
chown -R root:root "${INSTALL_DIR}"
chmod 755 "${INSTALL_DIR}" "${INSTALL_DIR}/app"
chmod 700 "${INSTALL_DIR}/config" "${INSTALL_DIR}/config/tls"
find "${INSTALL_DIR}/app" -type f -exec chmod 644 {} \;
find "${INSTALL_DIR}/app" -type d -exec chmod 755 {} \;
chmod +x "${INSTALL_DIR}/app/certwatch.sh"

# --- 4. TLS ------------------------------------------------------------------
if [ "$TLS" = "1" ] && [ -n "$DOMAIN" ] && [ -z "$CERT" ]; then
  LOCAL_IPS="$(hostname -I 2>/dev/null || true)"
  DOM_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
  if [ -n "$DOM_IP" ]; then
    if printf '%s\n' $LOCAL_IPS | grep -qx "$DOM_IP"; then
      say "DNS: ${DOMAIN} -> ${DOM_IP} (bu sunucu)"
    else
      warn "DNS: ${DOMAIN} -> ${DOM_IP}, bu sunucu: ${LOCAL_IPS}"
    fi
  fi
  for base in "/etc/letsencrypt/live/${DOMAIN}" "/etc/letsencrypt/live/${DOMAIN}-0001" \
              "/usr/local/lsws/conf/vhosts/${DOMAIN}" "/etc/letsencrypt/live/www.${DOMAIN}"; do
    if [ -f "${base}/fullchain.pem" ] && [ -f "${base}/privkey.pem" ]; then
      CERT="${base}/fullchain.pem"; KEY="${base}/privkey.pem"
      say "sertifika bulundu: ${CERT}"; break
    fi
  done
  [ -n "$CERT" ] || warn "${DOMAIN} icin sertifika bulunamadi; kendinden imzali kullanilacak."
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
      command -v openssl >/dev/null 2>&1 || die "openssl yok; AGFO_FW_TLS=0 deneyin."
      say "kendinden imzali sertifika uretiliyor"
      openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
        -keyout "$KEY" -out "$CERT" -subj "/C=TR/O=AGFO/CN=$(hostname -f 2>/dev/null || hostname)" \
        -addext "subjectAltName=DNS:$(hostname -f 2>/dev/null || hostname),IP:127.0.0.1" >/dev/null 2>&1 \
        || die "sertifika uretilemedi."
      chmod 600 "$KEY"; chmod 644 "$CERT"
    fi
  fi
fi

# --- 5. yapilandirma ---------------------------------------------------------
SCHEME="http"; [ "$TLS" = "1" ] && SCHEME="https"
SRV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; [ -n "$SRV_IP" ] || SRV_IP="SUNUCU-IP"
if [ -n "$DOMAIN" ]; then PUBLIC_URL="${SCHEME}://${DOMAIN}:${PORT}/"; else PUBLIC_URL="${SCHEME}://${SRV_IP}:${PORT}/"; fi

EXISTING_HASH=""
if [ -f "${INSTALL_DIR}/config/config.json" ]; then
  EXISTING_HASH="$("$PYBIN" -c "import json;print(json.load(open('${INSTALL_DIR}/config/config.json')).get('auth',{}).get('password_hash',''))" 2>/dev/null || true)"
fi
GEN_PASSWORD=""
if [ -z "${AGFO_FW_PASSWORD:-}" ] && [ -z "$EXISTING_HASH" ]; then
  GEN_PASSWORD="$("$PYBIN" -c 'import secrets,string;a=string.ascii_letters+string.digits;print("".join(secrets.choice(a) for _ in range(20)))')"
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
AGFO_FW_PASSWORD="${AGFO_FW_PASSWORD:-$GEN_PASSWORD}" \
AGFO_CFG_PORT="$PORT" AGFO_CFG_BIND="$BIND" AGFO_CFG_TLS="$TLS" \
AGFO_CFG_CERT="${CERT:-}" AGFO_CFG_KEY="${KEY:-}" AGFO_CFG_ALLOW="$ALLOW_IPS" \
AGFO_CFG_PUBLIC="$PUBLIC_URL" AGFO_CFG_FRAME="${AGFO_FW_FRAME_ANCESTORS:-}" AGFO_CFG_FRAME_SET="$([ "${AGFO_FW_FRAME_ANCESTORS+x}" = "x" ] && echo 1 || echo 0)" \
AGFO_CFG_TOKEN="$LOGIN_TOKEN" AGFO_CFG_DIR="${INSTALL_DIR}/config" AGFO_CFG_APP="${INSTALL_DIR}/app" \
"$PYBIN" - <<'PYEOF'
import json, os, sys
app_dir = os.environ["AGFO_CFG_APP"]; cfg_dir = os.environ["AGFO_CFG_DIR"]
os.environ["AGFO_FW_CONFIG_DIR"] = cfg_dir
sys.path.insert(0, app_dir)
import store

path = os.path.join(cfg_dir, "config.json")
existing = {}
if os.path.exists(path):
    try:
        existing = json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        print("[agfo-firewall-ai] UYARI: eski config okunamadi (%s)" % exc)
cfg = store.deep_merge(store.DEFAULT_CONFIG, existing)
cfg["bind"] = os.environ["AGFO_CFG_BIND"]
cfg["port"] = int(os.environ["AGFO_CFG_PORT"])
cfg["public_url"] = os.environ.get("AGFO_CFG_PUBLIC") or ""
cfg["tls"]["enabled"] = os.environ["AGFO_CFG_TLS"] == "1"
if os.environ.get("AGFO_CFG_CERT"):
    cfg["tls"]["cert"] = os.environ["AGFO_CFG_CERT"]
    cfg["tls"]["key"] = os.environ["AGFO_CFG_KEY"]
cfg["allow_ips"] = [x.strip() for x in (os.environ.get("AGFO_CFG_ALLOW") or "").split(",") if x.strip()]
if os.environ.get("AGFO_CFG_FRAME_SET") == "1":
    cfg["frame_ancestors"] = [x.strip() for x in (os.environ.get("AGFO_CFG_FRAME") or "").split(",") if x.strip()]

cfg["auth"]["login_token"] = os.environ.get("AGFO_CFG_TOKEN") or cfg["auth"].get("login_token") or ""

pw = os.environ.get("AGFO_FW_PASSWORD") or ""
if pw:
    cfg["auth"]["password_hash"] = store.hash_password(pw)
    print("[agfo-firewall-ai] panel sifresi ayarlandi")
elif not cfg["auth"].get("password_hash"):
    raise SystemExit("[agfo-firewall-ai] HATA: sifre yok")
else:
    print("[agfo-firewall-ai] mevcut panel sifresi korunuyor")

with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
os.chmod(path, 0o600)
for name in ("providers.json", "proposals.json"):
    target = os.path.join(cfg_dir, name)
    if not os.path.exists(target):
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({} if name == "providers.json" else [], fh)
        os.chmod(target, 0o600)
PYEOF

# --- 6. servis ---------------------------------------------------------------
say "systemd servisi kuruluyor"
sed -e "s#@PYBIN@#${PYBIN}#g" -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" \
    "${SRC_DIR}/systemd/${APP_SLUG}.service" > "$UNIT_PATH"
chmod 644 "$UNIT_PATH"
SELF_SIGNED="${INSTALL_DIR}/config/tls/server.crt"
if [ "$TLS" = "1" ] && [ -n "${CERT:-}" ] && [ "$CERT" != "$SELF_SIGNED" ]; then
  sed -e "s#@INSTALL_DIR@#${INSTALL_DIR}#g" "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.service" \
      > "/etc/systemd/system/${APP_SLUG}-certwatch.service"
  cp -a "${SRC_DIR}/systemd/${APP_SLUG}-certwatch.timer" "/etc/systemd/system/${APP_SLUG}-certwatch.timer"
  chmod 644 "/etc/systemd/system/${APP_SLUG}-certwatch."*
  CERTWATCH=1
else
  systemctl disable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${APP_SLUG}-certwatch."*
  CERTWATCH=0
fi
systemctl daemon-reload
systemctl enable "${APP_SLUG}.service" >/dev/null 2>&1 || true
systemctl restart "${APP_SLUG}.service"
[ "$CERTWATCH" = "1" ] && systemctl enable --now "${APP_SLUG}-certwatch.timer" >/dev/null 2>&1 || true

# --- 7. guvenlik duvari ------------------------------------------------------
if [ "$SKIP_FW" != "1" ] && [ "$BIND" != "127.0.0.1" ]; then
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    say "firewalld: ${PORT}/tcp aciliyor"
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    # firewalld reload'u kendi tablosunu bosaltir; bouncer kurallarini tazeleyelim.
    systemctl restart crowdsec-firewall-bouncer >/dev/null 2>&1 || true
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

CS_STATE="kurulu degil"
have_cscli && CS_STATE="$(cscli version 2>/dev/null | head -1 | tr -d '\n')"
BOUNCER_STATE="yok"
systemctl list-units --type=service --state=running 2>/dev/null | grep -q 'firewall-bouncer' && BOUNCER_STATE="calisiyor"

echo
echo "============================================================"
echo " ${APP_NAME} ${APP_VERSION} kuruldu"
echo "============================================================"
echo " Panel      : ${PUBLIC_URL}"
echo " Menu linki : ${PUBLIC_URL}?t=${LOGIN_TOKEN}"
echo "              (jeton sifresiz giris saglar; menu paketi bunu kendisi okur)"
if [ -n "$GEN_PASSWORD" ]; then
echo " Panel sifre: ${GEN_PASSWORD}"
echo " ! Bu sifreyi simdi kaydedin; bir daha gosterilmez."
elif [ -n "${AGFO_FW_PASSWORD:-}" ]; then
echo " Panel sifre: (AGFO_FW_PASSWORD ile verdiginiz deger)"
else
echo " Panel sifre: (onceki kurulumdan korundu)"
fi
echo " CrowdSec   : ${CS_STATE}"
echo " Bouncer    : ${BOUNCER_STATE}"
echo " Servis     : systemctl status ${APP_SLUG}"
echo " Gunluk     : journalctl -u ${APP_SLUG} -f"
echo " Ayarlar    : ${INSTALL_DIR}/config/config.json"
echo " Kaldirma   : bash ${INSTALL_DIR}/uninstall.sh"
echo
echo " SONRAKI ADIM: panele girip Saglayicilar sekmesinden bir AI"
echo " anahtari ekleyin, sonra AI Analizi sekmesinden calistirin."
echo "============================================================"
