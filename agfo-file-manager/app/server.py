# -*- coding: utf-8 -*-
"""AGFO File Manager - on panel.

Tiny File Manager (PHP) sunucuda 127.0.0.1 uzerinde root olarak calisir; bu
panel onun onunde durur ve tek giris kapisidir:

  * TLS, sifre ya da menu jetonu ile giris, IP kisiti, kaba kuvvet kilidi
  * yalnizca "/" ve "/index.php" arka uca iletilir; arka uc, bu panelin
    ekledigi gizli anahtar olmadan istek kabul etmez (sunucudaki baska
    kullanicilar 127.0.0.1 uzerinden root dosya yoneticisine ulasamaz)
  * dosya yukleme/indirme bellege alinmadan akitilir
  * arayuz dosyalari (bootstrap, ace, ...) yerelden sunulur; harici CDN yok

Harici bagimlilik yoktur: yalnizca Python 3.8+ standart kutuphanesi.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import logging
import mimetypes
import os
import secrets
import signal
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, urlencode

APP_NAME = "AGFO File Manager"
APP_VERSION = "1.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
ASSET_DIR = os.path.join(BASE_DIR, "assets")
CONFIG_DIR = os.environ.get("AGFO_FM_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUDIT_PATH = os.path.join(CONFIG_DIR, "audit.log")
COOKIE_NAME = "agfo_fm"
KEY_HEADER = "X-AGFO-FM-Key"
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailers", "transfer-encoding", "upgrade", "content-length"}
PBKDF2_ITER = 240000
CHUNK = 256 * 1024

log = logging.getLogger("agfo-file-manager")

DEFAULT_CONFIG = {
    "bind": "0.0.0.0",
    "port": 8826,
    "public_url": "",
    "tls": {"enabled": True, "cert": "", "key": ""},
    "auth": {"password_hash": "", "login_token": "", "token_login": True, "session_ttl": 43200},
    "allow_ips": [],
    "backend": {"host": "127.0.0.1", "port": 18096, "key": ""},
    "cookie_samesite": "Strict",
}


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return deep_merge(DEFAULT_CONFIG, json.load(fh))
    except FileNotFoundError:
        return deep_merge(DEFAULT_CONFIG, {})


CFG = load_config()


def hash_password(password, iterations=PBKDF2_ITER, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, base64.b64encode(salt).decode(),
                                       base64.b64encode(digest).decode())


def verify_password(password, stored):
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                   base64.b64decode(salt), int(iters))
        return hmac.compare_digest(base64.b64encode(calc).decode(), digest)
    except Exception:
        return False


def audit(action, detail):
    line = json.dumps({"t": int(time.time()), "action": action, "detail": detail}, ensure_ascii=False)
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        os.chmod(AUDIT_PATH, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# oturumlar ve kaba kuvvet kilidi
# ---------------------------------------------------------------------------

class Sessions(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def ttl(self):
        return int(CFG["auth"].get("session_ttl") or 43200)

    def create(self, ip):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.items[token] = {"ip": ip, "expires": time.time() + self.ttl()}
        return token

    def valid(self, token):
        if not token:
            return False
        with self.lock:
            item = self.items.get(token)
            if not item or item["expires"] < time.time():
                self.items.pop(token, None)
                return False
            item["expires"] = time.time() + self.ttl()
            return True

    def drop(self, token):
        with self.lock:
            self.items.pop(token, None)


class Guard(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.fails = {}

    def locked(self, ip):
        with self.lock:
            rec = self.fails.get(ip) or {}
            return max(0, int(rec.get("until", 0) - time.time()))

    def fail(self, ip):
        with self.lock:
            rec = self.fails.setdefault(ip, {"count": 0, "until": 0})
            rec["count"] += 1
            if rec["count"] >= 6:
                rec["until"], rec["count"] = time.time() + 900, 0

    def clear(self, ip):
        with self.lock:
            self.fails.pop(ip, None)


SESSIONS = Sessions()
GUARD = Guard()


LOGIN_PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AGFO File Manager</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0f14;
font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#e6edf3}
.card{width:340px;background:#121a24;border:1px solid #263241;border-radius:14px;padding:26px}
h1{font-size:17px;margin:0 0 4px}p{margin:0 0 18px;color:#8b97a7;font-size:12.5px}
input{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:8px;border:1px solid #263241;
background:#0b1016;color:inherit;font:inherit}button{margin-top:12px;width:100%;padding:10px;border:0;
border-radius:8px;background:#2dd4bf;color:#04201c;font-weight:600;cursor:pointer}
.err{color:#ffb4b4;font-size:12.5px;margin-top:10px;min-height:18px}b{color:#2dd4bf}
</style></head><body><form class="card" method="post" action="/agfo/login">
<h1><b>AGFO</b> File Manager</h1><p>Root yetkili dosya yöneticisi. Panel şifresiyle girin.</p>
<input type="password" name="password" placeholder="Şifre" autofocus autocomplete="current-password">
<button type="submit">Giriş</button><div class="err">{ERR}</div></form></body></html>"""


def login_page(error):
    import html as _html
    return LOGIN_PAGE.replace("{ERR}", _html.escape(error))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AGFO-File-Manager/" + APP_VERSION
    sys_version = ""

    def log_message(self, fmt, *args):
        log.info("%s %s", self.client_address[0], fmt % args)

    # --- yardimcilar ---
    def ip(self):
        return self.client_address[0]

    def ip_allowed(self):
        allow = [str(a).strip() for a in (CFG.get("allow_ips") or []) if str(a).strip()]
        if not allow:
            return True
        ip = self.ip()
        return any(a == ip or (a.endswith("*") and ip.startswith(a[:-1])) for a in allow)

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() == name:
                    return unquote(v.strip())
        return None

    def authed(self):
        return SESSIONS.valid(self.cookie(COOKIE_NAME))

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True          # form gonderimlerinde bazi tarayicilar Origin koymaz
        host = (self.headers.get("Host") or "").lower()
        return urlparse(origin).netloc.lower() == host

    def secure(self):
        return bool(CFG["tls"].get("enabled"))

    def cookie_header(self, value, max_age):
        return "%s=%s; Path=/; HttpOnly; SameSite=%s; Max-Age=%d%s" % (
            COOKIE_NAME, value, CFG.get("cookie_samesite") or "Strict", max_age,
            "; Secure" if self.secure() else "")

    def security_headers(self, html=False):
        self.send_header("X-Content-Type-Options", "nosniff")
        # "same-origin": ayni sitedeki form gonderimlerinde tarayici Origin'i
        # gercek degeriyle yollar ("no-referrer" Origin: null yaptiriyordu).
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        if self.secure():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if html:
            # TFM satir ici betik kullanir; yine de baska kaynaklara baglanti kapali.
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                             "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
                             "media-src 'self' blob:; frame-src 'self'; object-src 'none'; "
                             "base-uri 'self'; form-action 'self'; frame-ancestors 'self'")

    def simple(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.security_headers(html=ctype.startswith("text/html"))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def redirect(self, location, extra=None):
        hdr = {"Location": location}
        hdr.update(extra or {})
        self.simple(302, "", extra=hdr)

    def drain(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        while length > 0:
            chunk = self.rfile.read(min(CHUNK, length))
            if not chunk:
                break
            length -= len(chunk)

    # --- yonlendirme ---
    def handle_any(self):
        if not self.ip_allowed():
            self.drain()
            return self.simple(403, "ip_not_allowed")
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            return self.simple(200, json.dumps({"ok": True, "app": APP_NAME, "version": APP_VERSION}),
                               "application/json")
        if path.startswith("/fm-assets/"):
            return self.serve_asset(path[len("/fm-assets/"):])
        if path == "/agfo/login":
            return self.login()
        if path == "/agfo/logout":
            self.drain()
            SESSIONS.drop(self.cookie(COOKIE_NAME))
            return self.redirect("/agfo/login", {"Set-Cookie": self.cookie_header("", 0)})

        if path in ("/", "/index.php") and self.command == "GET" and self.try_token(parsed):
            return
        if not self.authed():
            self.drain()
            if self.command == "GET":
                return self.redirect("/agfo/login")
            return self.simple(401, "auth_required")
        if path not in ("/", "/index.php"):
            self.drain()
            return self.simple(404, "not found")
        if self.command not in ("GET", "HEAD") and not self.same_origin():
            self.drain()
            return self.simple(403, "bad_origin")
        return self.proxy()

    def try_token(self, parsed):
        query = parse_qs(parsed.query)
        given = (query.get("t") or [""])[0]
        if not given:
            return False
        stored = CFG["auth"].get("login_token") or ""
        ip = self.ip()
        if not CFG["auth"].get("token_login", True) or not stored or GUARD.locked(ip):
            return False
        if not hmac.compare_digest(given, stored):
            GUARD.fail(ip)
            audit("token_fail", {"ip": ip})
            return False
        GUARD.clear(ip)
        token = SESSIONS.create(ip)
        audit("token_login", {"ip": ip})
        rest = {k: v for k, v in query.items() if k != "t"}
        target = "/" + ("?" + urlencode(rest, doseq=True) if rest else "")
        self.redirect(target, {"Set-Cookie": self.cookie_header(token, SESSIONS.ttl())})
        return True

    def login(self):
        if self.command == "GET":
            return self.simple(200, login_page(""), "text/html; charset=utf-8")
        if self.command != "POST":
            return self.simple(405, "method not allowed")
        ip = self.ip()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 4096:
            self.close_connection = True
            return self.simple(413, "too large")
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        password = (parse_qs(raw).get("password") or [""])[0]
        wait = GUARD.locked(ip)
        if wait:
            return self.simple(429, login_page("Çok fazla deneme. %d dk bekleyin." % (wait // 60 + 1)),
                               "text/html; charset=utf-8")
        if not self.same_origin():
            return self.simple(403, "bad_origin")
        if not verify_password(password, CFG["auth"].get("password_hash") or ""):
            GUARD.fail(ip)
            audit("login_fail", {"ip": ip})
            return self.simple(401, login_page("Şifre hatalı."), "text/html; charset=utf-8")
        GUARD.clear(ip)
        token = SESSIONS.create(ip)
        audit("login", {"ip": ip})
        return self.redirect("/", {"Set-Cookie": self.cookie_header(token, SESSIONS.ttl())})

    def serve_asset(self, rel):
        self.drain()
        rel = unquote(rel).lstrip("/")
        target = os.path.normpath(os.path.join(ASSET_DIR, rel))
        if not target.startswith(ASSET_DIR + os.sep) or not os.path.isfile(target):
            return self.simple(404, "not found")
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        size = os.path.getsize(target)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.security_headers()
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(target, "rb") as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # --- ters vekil ---
    def proxy(self):
        be = CFG["backend"]
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            return self.simple(411, "length required")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.simple(400, "bad length")
        conn = http.client.HTTPConnection(be.get("host", "127.0.0.1"), int(be.get("port", 18096)), timeout=3600)
        try:
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for key, value in self.headers.items():
                low = key.lower()
                if low in HOP or low in ("x-agfo-fm-key", "x-forwarded-proto", "x-forwarded-for", "x-real-ip"):
                    continue
                if low == "cookie":
                    # Panel oturum cerezi arka uca gitmez.
                    kept = [c for c in value.split(";") if c.split("=", 1)[0].strip() != COOKIE_NAME]
                    if not kept:
                        continue
                    value = ";".join(kept).strip()
                conn.putheader(key, value)
            conn.putheader(KEY_HEADER, be.get("key", ""))
            conn.putheader("X-Forwarded-Proto", "https" if self.secure() else "http")
            conn.putheader("X-Forwarded-For", self.ip())
            if length:
                conn.putheader("Content-Length", str(length))
            conn.endheaders()
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    break
                conn.send(chunk)
                remaining -= len(chunk)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            log.warning("arka uc hatasi: %s", exc)
            self.close_connection = True
            return self.simple(502, "Dosya yoneticisi arka ucu yanit vermiyor (agfo-file-manager-php servisi).")

        ctype = resp.getheader("Content-Type", "") or ""
        is_html = ctype.startswith("text/html")
        self.send_response(resp.status, resp.reason)
        for key, value in resp.getheaders():
            low = key.lower()
            if low in HOP or low in ("x-powered-by", "content-security-policy", "x-frame-options"):
                continue
            if low == "location":
                value = self.fix_location(value)
            self.send_header(key, value)
        self.security_headers(html=is_html)

        if is_html:
            body = resp.read(8 * 1024 * 1024)
            body = self.inject(body)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            conn.close()
            return
        size = resp.getheader("Content-Length")
        if size is not None:
            self.send_header("Content-Length", size)
        else:
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        try:
            if self.command != "HEAD":
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        finally:
            conn.close()

    def fix_location(self, value):
        """Arka uc http://127.0.0.1:18096/... diye yonlendirirse panel adresine cevir."""
        parsed = urlparse(value)
        if parsed.netloc and parsed.hostname in ("127.0.0.1", "localhost"):
            return parsed.path + ("?" + parsed.query if parsed.query else "")
        if parsed.scheme == "http" and self.secure():
            return "https" + value[4:]
        return value

    def inject(self, body):
        bar = (b'<a href="/agfo/logout" style="position:fixed;right:14px;bottom:12px;z-index:9999;'
               b'background:#121a24;color:#e6edf3;border:1px solid #263241;border-radius:8px;padding:5px 11px;'
               b'font:12px system-ui,sans-serif;text-decoration:none;opacity:.85">AGFO &middot; '
               b'\xc3\x87\xc4\xb1k\xc4\xb1\xc5\x9f</a>')
        idx = body.rfind(b"</body>")
        return body[:idx] + bar + body[idx:] if idx >= 0 else body

    do_GET = handle_any
    do_HEAD = handle_any
    do_POST = handle_any
    do_PUT = handle_any
    do_DELETE = handle_any

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ssl.SSLError, socket.timeout):
            self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def tls_context():
    cert = CFG["tls"].get("cert") or os.path.join(CONFIG_DIR, "tls", "server.crt")
    key = CFG["tls"].get("key") or os.path.join(CONFIG_DIR, "tls", "server.key")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not CFG["auth"].get("password_hash"):
        log.error("config.json icinde auth.password_hash yok; kurulum betigini calistirin.")
        sys.exit(2)
    if not CFG["backend"].get("key"):
        log.error("config.json icinde backend.key yok; kurulum betigini calistirin.")
        sys.exit(2)
    bind = os.environ.get("AGFO_FM_BIND") or CFG.get("bind") or "0.0.0.0"
    port = int(os.environ.get("AGFO_FM_PORT") or CFG.get("port") or 8826)
    if ":" in bind:
        Server.address_family = socket.AF_INET6
    httpd = Server((bind, port), Handler)
    scheme = "http"
    if CFG["tls"].get("enabled"):
        httpd.socket = tls_context().wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    log.info("%s %s dinlemede: %s://%s:%d (arka uc %s:%s)", APP_NAME, APP_VERSION, scheme, bind, port,
             CFG["backend"].get("host"), CFG["backend"].get("port"))

    def stop(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    httpd.serve_forever()
    log.info("durduruldu")


if __name__ == "__main__":
    main()
