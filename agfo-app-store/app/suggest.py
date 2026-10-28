# -*- coding: utf-8 -*-
"""Kurulum penceresi icin akilli oneriler.

Sunucudaki siteleri, PHP surumlerini ve PHP eklentilerini okuyup bir uygulama icin
en uygun kurulum yerini (alan adi + alt dizin) ve PHP surumunu onerir.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
from urllib.parse import urlparse

import installer
import store

EMPTY_OK = {"index.html", ".well-known", "cgi-bin", ".htaccess", "favicon.ico"}


def installed_php():
    template = os.environ.get("AGFO_STORE_PHP_TEMPLATE", "/usr/local/lsws/lsphp{v}/bin/php")
    out = []
    for v in ("74", "80", "81", "82", "83", "84", "85"):
        if os.path.isfile(template.replace("{v}", v)):
            out.append(v[0] + "." + v[1:])
    return out


def php_options(app):
    """Her kurulu PHP icin: uygun mu, neden degil (aralik / eksik eklenti)."""
    opts = []
    for v in installed_php():
        in_range = installer.php_in_range(app, v)
        missing = installer.missing_extensions(app, v) if in_range else []
        reason = "" if in_range else "desteklenmiyor"
        if missing:
            reason = "eksik eklenti: " + ", ".join(missing)
        opts.append({"version": v, "ok": in_range and not missing, "in_range": in_range,
                     "missing": missing, "reason": reason,
                     "hint": installer.ext_hint(v, missing) if missing else ""})
    return opts


def best_php(app, opts=None):
    """Uygun surumlerin en yenisi; desteklenen ust sinira saygi gosterir."""
    opts = opts if opts is not None else php_options(app)
    good = [o["version"] for o in opts if o["ok"]]
    return good[-1] if good else None


def _server_ips():
    ips = set()
    try:
        out = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5).stdout.decode()
        ips.update(out.split())
    except Exception:
        pass
    ips.update({"127.0.0.1"})
    return ips


def dns_points_here(domain, ips=None):
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(domain, 80, proto=socket.IPPROTO_TCP)}
    except Exception:
        return False, []
    ips = ips if ips is not None else _server_ips()
    return bool(addrs & ips), sorted(addrs)


def main_domain():
    """Bu sunucunun ana alan adi: panel adresi > CyberPanel sertifikasi > en kisa site adi."""
    public = store.CFG.get("public_url", default="") or ""
    host = urlparse(public).hostname or ""
    if host and not re.match(r"^[\d.]+$", host):
        return host
    sites = [s["domain"] for s in list_sites()]
    return min(sites, key=len) if sites else ""


def list_sites():
    base = installer.HOME_BASE
    installs = store.load_installs()
    test = (store.CFG.get("cyberpanel", "test_domain", default="") or "").lower()
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for name in names:
        root = os.path.join(base, name, "public_html")
        if not installer.DOMAIN_RE.match(name) or not os.path.isdir(root):
            continue
        try:
            entries = set(os.listdir(root))
        except OSError:
            entries = set()
        apps = [{"app": i.get("app_name") or i.get("app"), "path": i.get("path", "/")}
                for i in installs if i.get("domain") == name]
        out.append({"domain": name, "php": installer.site_php_version(name) or "",
                    "root_empty": not (entries - EMPTY_OK),
                    "root_items": len(entries - EMPTY_OK), "apps": apps, "is_test": name == test})
    return out


def _slug(app):
    s = re.sub(r"[^a-z0-9]", "", app["id"].lower())[:20] or "app"
    return {"woocommerce": "magaza", "prestashop": "magaza", "opencart": "magaza",
            "roundcube": "webmail", "snappymail": "webmail", "phpmyadmin": "pma"}.get(s, s)


def for_app(app):
    opts = php_options(app)
    best = best_php(app, opts)
    sites = list_sites()
    main = main_domain()
    ips = _server_ips()
    slug = _slug(app)
    root_only = bool(app.get("root_only"))
    taken = {s["domain"] for s in sites}
    suggestions = []

    def site_php_plan(site):
        cur = site["php"]
        if not cur:
            return best, False, ""
        if installer.php_in_range(app, cur) and not installer.missing_extensions(app, cur):
            return cur, False, ""
        if best:
            why = "desteklemiyor" if not installer.php_in_range(app, cur) else "eklentisi eksik"
            return best, True, "Sitenin PHP %s sürümü bu uygulamayı %s; %s'e geçirilmesi gerekir (sitedeki diğer uygulamaları da etkiler)." % (cur, why, best)
        return None, False, "Bu sunucuda uygun PHP sürümü yok."

    # 1) yeni alt alan adi: uygulamaya ayri ev (her zaman en temiz secenek)
    if main:
        cand = "%s.%s" % (slug, main)
        n = 2
        while cand in taken:
            cand = "%s%d.%s" % (slug, n, main); n += 1
        ok_dns, addrs = dns_points_here(cand, ips)
        suggestions.append({
            "kind": "new_subdomain", "domain": cand, "path": "/", "php": best,
            "change_site_php": "", "dns_ok": ok_dns, "dns": addrs,
            "title": "Yeni alt alan adı",
            "note": ("DNS bu sunucuyu gösteriyor; SSL de alınır." if ok_dns else
                     "DNS kaydı henüz yok. CyberPanel'in DNS'ini kullanıyorsanız site açılınca eklenebilir; "
                     "değilse %s için bu sunucunun IP'sine A kaydı ekleyin (SSL ondan sonra alınır)." % cand),
            "viable": bool(best)})

    # 2) bos mevcut siteler (kok)
    for site in sites:
        if site["is_test"] or not site["root_empty"]:
            continue
        php, change, note = site_php_plan(site)
        suggestions.append({"kind": "existing_root", "domain": site["domain"], "path": "/", "php": php,
                            "change_site_php": php if change else "", "dns_ok": None,
                            "title": "Boş mevcut site",
                            "note": note or "Site boş; kök dizine kurulur (PHP %s)." % site["php"],
                            "viable": php is not None})

    # 3) dolu mevcut sitede alt dizin (kok ozel uygulamalarda yok)
    if not root_only:
        for site in sites:
            if site["is_test"] or site["root_empty"]:
                continue
            used = {a["path"].rstrip("/") for a in site["apps"]}
            path, n = "/" + slug, 2
            while path in used or os.path.exists(os.path.join(installer.HOME_BASE, site["domain"], "public_html", path.lstrip("/"))):
                path = "/%s%d" % (slug, n); n += 1
            php, change, note = site_php_plan(site)
            what = ", ".join(a["app"] for a in site["apps"][:2]) or "%d öğe" % site["root_items"]
            suggestions.append({"kind": "existing_subdir", "domain": site["domain"], "path": path, "php": php,
                                "change_site_php": php if change else "", "dns_ok": None,
                                "title": "Mevcut sitede alt dizin",
                                "note": note or "Kökte %s var; %s altına kurulur (PHP %s)." % (what, path, site["php"]),
                                "viable": php is not None})

    # siralama: uygulanabilir > PHP degisikligi gerektirmeyen > yeni alt alan adi (DNS hazirsa en ustte)
    def rank(s):
        return (not s["viable"], bool(s["change_site_php"]),
                {"new_subdomain": 0 if s.get("dns_ok") else 2, "existing_root": 1, "existing_subdir": 3}[s["kind"]])
    suggestions.sort(key=rank)
    if suggestions and suggestions[0]["viable"]:
        suggestions[0]["recommended"] = True

    email = (store.CFG.get("cyberpanel", "last_email", default="") or "").strip() or (
        ("admin@" + main) if main else "")
    return {"app": app["id"], "php": opts, "best_php": best, "sites": sites, "main_domain": main,
            "suggestions": suggestions[:8], "email": email, "root_only": root_only,
            "php_range": {"min": (app.get("requires") or {}).get("php", ""),
                          "max": (app.get("requires") or {}).get("php_max", "")}}
