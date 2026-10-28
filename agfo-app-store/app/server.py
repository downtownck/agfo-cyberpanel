#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGFO App Store - CyberPanel icin modern uygulama magazasi.

* Harici Python bagimliligi yoktur (yalnizca standart kutuphane).
* Siteyi, veritabanini ve SSL'i CyberPanel'in kendi komut satiriyla olusturur.
* Her uygulama catalog/<id>.json dosyasindaki bir tariften kurulur.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog
import installer
import store

APP_NAME = "AGFO App Store"
APP_VERSION = "1.0.2"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
COOKIE_NAME = "agfo_store"

log = logging.getLogger("agfo-app-store")
CFG = store.CFG

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}



# ---------------------------------------------------------------------------
# oturumlar
# ---------------------------------------------------------------------------

class SessionStore(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def create(self, ip):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        ttl = int(CFG.get("auth", "session_ttl", default=43200) or 43200)
        with self.lock:
            self.items[token] = {"ip": ip, "csrf": csrf, "expires": time.time() + ttl}
        return token, csrf

    def get(self, token):
        if not token:
            return None
        with self.lock:
            item = self.items.get(token)
            if not item:
                return None
            if item["expires"] < time.time():
                self.items.pop(token, None)
                return None
            return item

    def touch(self, token):
        ttl = int(CFG.get("auth", "session_ttl", default=43200) or 43200)
        with self.lock:
            if token in self.items:
                self.items[token]["expires"] = time.time() + ttl

    def drop(self, token):
        with self.lock:
            self.items.pop(token, None)


SESSIONS = SessionStore()


class LoginGuard(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.fails = {}

    def locked_for(self, ip):
        with self.lock:
            rec = self.fails.get(ip)
            if not rec:
                return 0
            remaining = rec.get("until", 0) - time.time()
            return int(remaining) if remaining > 0 else 0

    def record_fail(self, ip):
        with self.lock:
            rec = self.fails.setdefault(ip, {"count": 0, "until": 0})
            rec["count"] += 1
            if rec["count"] >= 6:
                rec["until"] = time.time() + 900
                rec["count"] = 0

    def clear(self, ip):
        with self.lock:
            self.fails.pop(ip, None)


GUARD = LoginGuard()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AGFO-App-Store/" + APP_VERSION
    sys_version = ""

    def log_message(self, fmt, *args):
        log.info("%s %s", self.client_address[0], fmt % args)

    # --- yardimcilar ---
    def client_ip(self):
        return self.client_address[0]

    def ip_allowed(self):
        allow = CFG.get("allow_ips", default=[]) or []
        if not allow:
            return True
        ip = self.client_ip()
        for entry in allow:
            entry = str(entry).strip()
            if not entry:
                continue
            if entry == ip or (entry.endswith("*") and ip.startswith(entry[:-1])):
                return True
        return False

    def cookies(self):
        raw = self.headers.get("Cookie") or ""
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                out[key.strip()] = unquote(value.strip())
        return out

    def session(self):
        token = self.cookies().get(COOKIE_NAME)
        sess = SESSIONS.get(token)
        if sess:
            SESSIONS.touch(token)
            sess["_token"] = token
        return sess

    def body_json(self, limit=256 * 1024):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def secure_cookie(self):
        return bool(CFG.get("tls", "enabled", default=True))

    def send_common(self, extra=None):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        ancestors = [str(a).strip() for a in (CFG.get("frame_ancestors", default=[]) or []) if str(a).strip()]
        if ancestors:
            frame_rule = "frame-ancestors 'self' " + " ".join(ancestors)
        else:
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            frame_rule = "frame-ancestors 'self'"
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "base-uri 'none'; form-action 'none'; " + frame_rule)
        if self.secure_cookie():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for key, value in (extra or {}).items():
            self.send_header(key, value)

    def reply(self, code, payload, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_common(extra)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except Exception:
            pass

    def fail(self, code, message):
        self.reply(code, {"ok": False, "error": message})

    def require_session(self):
        sess = self.session()
        if not sess:
            self.fail(401, "auth_required")
            return None
        return sess

    def check_csrf(self, sess):
        token = self.headers.get("X-AGFO-CSRF") or ""
        if not token or not hmac.compare_digest(token, sess.get("csrf", "")):
            self.fail(403, "csrf")
            return False
        return True

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            return urlparse(origin).netloc == (self.headers.get("Host") or "").strip()
        except Exception:
            return False

    # --- yonlendirme ---
    def do_GET(self):
        if not self.ip_allowed():
            return self.fail(403, "ip_not_allowed")
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path == "/healthz":
            return self.reply(200, {"ok": True, "app": APP_NAME, "version": APP_VERSION})
        if path == "/api/state":
            return self.api_state()
        if path in ("/", "/index.html"):
            if self.try_token_login(urlparse(self.path)):
                return
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])

        sess = self.require_session()
        if not sess:
            return
        try:
            if path == "/api/catalog":
                return self.reply(200, {"ok": True, "apps": catalog.public_list(),
                                        "categories": catalog.categories()})
            if path == "/api/jobs":
                return self.reply(200, {"ok": True, "jobs": store.load_jobs()[::-1][:50]})
            if path == "/api/installs":
                return self.reply(200, {"ok": True, "installs": store.load_installs()[::-1]})
            if path == "/api/audit":
                return self.reply(200, {"ok": True, "entries": store.read_audit(300)})
            if path.startswith("/api/job/"):
                job_id = path.rsplit("/", 1)[-1]
                if not re.match(r"^[a-f0-9]{8,32}$", job_id):
                    return self.fail(400, "gecersiz is kimligi")
                record = store.get_job(job_id)
                if not record:
                    return self.fail(404, "is bulunamadi")
                offset = 0
                try:
                    offset = int((query.get("offset") or ["0"])[0])
                except ValueError:
                    offset = 0
                runtime = installer.get_runtime_job(job_id)
                lines, total = (runtime.tail(offset) if runtime else ([], 0))
                return self.reply(200, {"ok": True, "job": record,
                                        "lines": lines, "total": total})
        except Exception as exc:
            log.exception("GET %s", path)
            return self.fail(500, str(exc))
        return self.fail(404, "not_found")

    def do_POST(self):
        if not self.ip_allowed():
            return self.fail(403, "ip_not_allowed")
        if not self.same_origin():
            return self.fail(403, "bad_origin")
        path = urlparse(self.path).path
        if path == "/api/login":
            return self.api_login()
        sess = self.require_session()
        if not sess:
            return
        if not self.check_csrf(sess):
            return
        try:
            if path == "/api/logout":
                SESSIONS.drop(sess.get("_token"))
                same_site = str(CFG.get("cookie_samesite", default="Strict") or "Strict")
                return self.reply(200, {"ok": True}, extra={
                    "Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=%s%s" % (
                        COOKIE_NAME, same_site, "; Secure" if self.secure_cookie() else "")})
            if path == "/api/password":
                return self.api_password()
            if path == "/api/install":
                return self.api_install()
            if path == "/api/uninstall":
                return self.api_uninstall()
            if path == "/api/verify":
                return self.reply(200, {"ok": True, "results": installer.verify_catalog()})
            if path == "/api/settings":
                return self.api_settings()
        except installer.InstallError as exc:
            return self.fail(400, str(exc))
        except ValueError as exc:
            return self.fail(400, str(exc))
        except Exception as exc:
            log.exception("POST %s", path)
            return self.fail(500, str(exc))
        return self.fail(404, "not_found")

    # --- otomatik giris jetonu ---
    def try_token_login(self, parsed):
        """?t=<jeton> ile sifresiz giris; basarili ise temiz adrese yonlendirir."""
        query = parse_qs(parsed.query)
        token = (query.get("t") or [""])[0].strip()
        if not token:
            return False
        if not CFG.get("auth", "token_login", default=True):
            return False
        stored = CFG.get("auth", "login_token", default="") or ""
        ip = self.client_ip()
        if not stored or GUARD.locked_for(ip) > 0:
            return False
        if not hmac.compare_digest(token, stored):
            GUARD.record_fail(ip)
            log.warning("gecersiz giris jetonu: %s", ip)
            return False
        GUARD.clear(ip)
        sess_token, csrf = SESSIONS.create(ip)
        same_site = str(CFG.get("cookie_samesite", default="Strict") or "Strict")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Strict"
        secure = self.secure_cookie() or same_site == "None"
        cookie = "%s=%s; Path=/; HttpOnly; SameSite=%s; Max-Age=%d%s" % (
            COOKIE_NAME, sess_token, same_site,
            int(CFG.get("auth", "session_ttl", default=43200) or 43200),
            "; Secure" if secure else "")
        # Jetonu adresten dusur, diger parametreleri (ornek: open=root) koru.
        rest = [(k, v) for k, vals in query.items() if k != "t" for v in vals]
        target = parsed.path or "/"
        if rest:
            target += "?" + urlencode(rest)
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_common()
        self.end_headers()
        log.info("jeton ile giris: %s", ip)
        return True

    # --- statik ---
    def serve_static(self, rel):
        rel = rel.split("?")[0].lstrip("/")
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            return self.fail(404, "not_found")
        try:
            with open(target, "rb") as fh:
                data = fh.read()
        except Exception:
            return self.fail(500, "read_error")
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(target)[1].lower(),
                                                  "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800" if rel.startswith("vendor/") else "no-cache")
        self.send_common()
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    # --- kimlik ---
    def api_state(self):
        sess = self.session()
        base = {
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "authenticated": bool(sess),
            "hostname": socket.gethostname(),
            "tls": bool(CFG.get("tls", "enabled", default=True)),
            "password_set": bool(CFG.get("auth", "password_hash", default="")),
        }
        if sess:
            base.update({
                "csrf": sess.get("csrf"),
                "public_url": CFG.get("public_url", default="") or "",
                "your_ip": self.client_ip(),
                "cyberpanel": {
                    "cli": bool(installer.CyberPanel(lambda m: None).cli()) if self._cli_ok() else False,
                    "default_php": CFG.get("cyberpanel", "default_php", default="8.2"),
                    "default_package": CFG.get("cyberpanel", "default_package", default="Default"),
                    "issue_ssl": bool(CFG.get("cyberpanel", "issue_ssl", default=True)),
                },
                "app_count": len(catalog.load()),
                "install_count": len(store.load_installs()),
            })
        return self.reply(200, base)

    def _cli_ok(self):
        try:
            installer.CyberPanel(lambda m: None).cli()
            return True
        except Exception:
            return False

    def api_login(self):
        ip = self.client_ip()
        locked = GUARD.locked_for(ip)
        if locked > 0:
            return self.reply(429, {"ok": False, "error": "locked", "retry_after": locked})
        data = self.body_json(limit=8192)
        stored = CFG.get("auth", "password_hash", default="") or ""
        if not stored:
            return self.fail(500, "no_password_configured")
        time.sleep(0.25)
        if not store.verify_password(data.get("password") or "", stored):
            GUARD.record_fail(ip)
            log.warning("basarisiz giris: %s", ip)
            return self.fail(401, "bad_password")
        GUARD.clear(ip)
        token, csrf = SESSIONS.create(ip)
        same_site = str(CFG.get("cookie_samesite", default="Strict") or "Strict")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Strict"
        secure = self.secure_cookie() or same_site == "None"
        cookie = "%s=%s; Path=/; HttpOnly; SameSite=%s; Max-Age=%d%s" % (
            COOKIE_NAME, token, same_site,
            int(CFG.get("auth", "session_ttl", default=43200) or 43200),
            "; Secure" if secure else "")
        store.audit("login", {"ip": ip})
        return self.reply(200, {"ok": True, "csrf": csrf}, extra={"Set-Cookie": cookie})

    def api_password(self):
        data = self.body_json(limit=8192)
        if not store.verify_password(data.get("current") or "",
                                     CFG.get("auth", "password_hash", default="") or ""):
            return self.fail(401, "bad_password")
        new = data.get("new") or ""
        if len(new) < 10:
            return self.fail(400, "too_short")
        CFG.set(["auth", "password_hash"], store.hash_password(new))
        store.audit("password_change", {})
        return self.reply(200, {"ok": True})

    # --- kurulum ---
    def api_install(self):
        data = self.body_json()
        app_id = (data.get("app") or "").strip()
        params = data.get("params") or {}
        if not isinstance(params, dict):
            return self.fail(400, "gecersiz parametreler")
        app = catalog.get(app_id)
        if not app:
            return self.fail(404, "uygulama bulunamadi")
        job_id = installer.start_install(app_id, params)
        store.audit("install_start", {"app": app_id, "domain": params.get("domain")})
        return self.reply(200, {"ok": True, "job": job_id})

    def api_uninstall(self):
        data = self.body_json()
        # Gelmeyen alanlar gonderilmez: varsayilanlar (yedek al, DB sil) motorda.
        params = {k: data[k] for k in ("domain", "path", "confirm", "drop_db", "backup", "delete_site") if k in data}
        job_id = installer.start_uninstall(params)
        store.audit("uninstall_start", {"domain": params.get("domain"), "path": params.get("path"),
                                        "drop_db": bool(params.get("drop_db")),
                                        "delete_site": bool(params.get("delete_site")),
                                        "backup": bool(params.get("backup"))})
        return self.reply(200, {"ok": True, "job": job_id})

    def api_settings(self):
        data = self.body_json()
        cp = data.get("cyberpanel") or {}
        if "default_php" in cp:
            value = str(cp["default_php"]).strip()
            if not re.match(r"^\d\.\d$", value):
                return self.fail(400, "gecersiz PHP surumu")
            CFG.set(["cyberpanel", "default_php"], value)
        if "default_package" in cp:
            value = str(cp["default_package"]).strip()[:40]
            if value and not re.match(r"^[A-Za-z0-9 _-]+$", value):
                return self.fail(400, "gecersiz paket adi")
            CFG.set(["cyberpanel", "default_package"], value or "Default")
        if "default_owner" in cp:
            value = str(cp["default_owner"]).strip()[:40]
            if value and not re.match(r"^[A-Za-z0-9_.-]+$", value):
                return self.fail(400, "gecersiz sahip adi")
            CFG.set(["cyberpanel", "default_owner"], value or "admin")
        if "issue_ssl" in cp:
            CFG.set(["cyberpanel", "issue_ssl"], bool(cp["issue_ssl"]))
        store.audit("settings_update", {"keys": list(cp.keys())})
        return self.reply(200, {"ok": True, "cyberpanel": CFG.get("cyberpanel", default={})})

# ---------------------------------------------------------------------------
# sunucu
# ---------------------------------------------------------------------------

class ThreadedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ssl.SSLError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        log.exception("istek hatasi %s", client_address)


def build_tls_context():
    cert = CFG.get("tls", "cert", default="") or os.path.join(store.CONFIG_DIR, "tls", "server.crt")
    key = CFG.get("tls", "key", default="") or os.path.join(store.CONFIG_DIR, "tls", "server.key")
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        raise RuntimeError("TLS acik ama sertifika yok: %s / %s" % (cert, key))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    bind = os.environ.get("AGFO_STORE_BIND") or CFG.get("bind", default="0.0.0.0")
    port = int(os.environ.get("AGFO_STORE_PORT") or CFG.get("port", default=8824))
    if not CFG.get("auth", "password_hash", default=""):
        log.error("config.json icinde auth.password_hash yok; kurulum betigini calistirin.")
        sys.exit(2)
    if ":" in bind:
        ThreadedServer.address_family = socket.AF_INET6
    httpd = ThreadedServer((bind, port), Handler)
    scheme = "http"
    if CFG.get("tls", "enabled", default=True):
        httpd.socket = build_tls_context().wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    stale = store.recover_stale_jobs()
    if stale:
        log.warning("%d yarim kalmis is hata olarak kapatildi", stale)
    try:
        installer.CyberPanel(lambda m: None).cli()
    except Exception:
        log.warning("cyberpanel komutu bulunamadi; panel acilir ama kurulum yapamaz.")
    log.info("%s %s dinlemede: %s://%s:%d", APP_NAME, APP_VERSION, scheme, bind, port)

    import signal

    def shutdown(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        log.info("durduruldu")


if __name__ == "__main__":
    main()
