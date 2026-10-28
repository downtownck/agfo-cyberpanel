#!/usr/bin/env python3
"""Bir AGFO panelinin menu adresini uretir.

Kullanim: panel_url.py <config.json> <panel_adi>
Cikti (stdout): https://alanadi:port/   (bos = adres uretilemedi)
Uyarilar stderr'e yazilir.

Panelin public_url'i bir IP adresiyse ya da bos ise, CyberPanel'in kendi
(8090) sertifikasindaki alan adini kullanir. Ancak bunu yalnizca panelin
kendi sertifikasi o alan adini kapsiyorsa yapar; kapsamiyorsa alan adina
gecmek de tarayici uyarisini gidermez, o yuzden ne yapilacagini soyler.
"""
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

PANEL_CERTS = [p for p in (os.environ.get("AGFO_MENU_PANEL_CERT"),
                           "/usr/local/lscp/conf/cert.pem",
                           "/usr/local/lscp/conf/server.crt") if p]


def warn(msg):
    sys.stderr.write("[agfo-ssh-menu] UYARI: %s\n" % msg)


def cert_names(path):
    """Sertifikadaki DNS adlari (SAN)."""
    if not path or not os.path.isfile(path):
        return []
    try:
        out = subprocess.run(["openssl", "x509", "-in", path, "-noout", "-ext", "subjectAltName"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10).stdout.decode()
    except Exception:
        return []
    names = []
    for part in out.replace("\n", ",").split(","):
        part = part.strip()
        if part.startswith("DNS:"):
            names.append(part[4:].strip().lower())
    return names


def covers(names, host):
    host = host.lower()
    for n in names:
        if n == host:
            return True
        if n.startswith("*.") and host.count(".") == n.count(".") and host.endswith(n[1:]):
            return True
    return False


def is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def cyberpanel_domain():
    forced = (os.environ.get("AGFO_MENU_DOMAIN") or "").strip().lower()
    if forced:
        return forced
    for p in PANEL_CERTS:
        for n in cert_names(p):
            if not n.startswith("*."):
                return n
    return ""


def main():
    cfg_path, label = sys.argv[1], sys.argv[2]
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    tls = cfg.get("tls") or {}
    scheme = "https" if tls.get("enabled", True) else "http"
    port = cfg.get("port")
    pub = (cfg.get("public_url") or "").strip()
    host = urlsplit(pub).hostname if pub else ""
    if pub and port is None:
        port = urlsplit(pub).port

    if not host or is_ip(host):
        dom = cyberpanel_domain()
        mine = cert_names(tls.get("cert"))
        if dom and scheme == "https" and covers(mine, dom):
            sys.stdout.write("%s://%s:%s/\n" % (scheme, dom, port))
            return
        if dom and scheme == "https":
            slug = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(cfg_path))))
            warn("%s IP adresiyle yayinlaniyor ve sertifikasi %s alan adini kapsamiyor; "
                 "tarayici 'guvenli degil' der. Duzeltmek icin %s paketini yeniden calistirin "
                 "(alan adini ve Let's Encrypt sertifikasini kendisi bulur), sonra bu menu paketini."
                 % (label, dom, slug))
        if not host:
            host = os.environ.get("AGFO_MENU_IP") or ""
            if not host:
                try:
                    host = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE,
                                          timeout=5).stdout.decode().split()[0]
                except Exception:
                    host = socket.gethostbyname(socket.gethostname())
            sys.stdout.write("%s://%s:%s/\n" % (scheme, host, port))
            return
    sys.stdout.write(pub.rstrip("/") + "/\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # menu kurulumunu bozmasin
        warn("adres uretilemedi (%s): %s" % (sys.argv[1] if len(sys.argv) > 1 else "?", exc))
