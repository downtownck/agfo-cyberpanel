#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGFO Firewall AI - CrowdSec uzerine AI destekli yonetim paneli.

* Harici Python bagimliligi yoktur (yalnizca standart kutuphane).
* CrowdSec ile `cscli` uzerinden konusur.
* AI yalnizca ONERI uretir; her uygulama panelden onay ister ve denetim
  gunlugune yazilir.
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
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyst
import crowdsec
import providers
import store

APP_NAME = "AGFO Firewall AI"
APP_VERSION = "1.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
COOKIE_NAME = "agfo_fwai"

log = logging.getLogger("agfo-firewall-ai")
CFG = store.CFG

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

LAST_ANALYSIS = {"data": None}


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
    server_version = "AGFO-Firewall-AI/" + APP_VERSION
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
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])

        sess = self.require_session()
        if not sess:
            return
        try:
            if path == "/api/dashboard":
                return self.api_dashboard(query)
            if path == "/api/proposals":
                return self.reply(200, {"ok": True, "proposals": store.load_proposals()[::-1],
                                        "analysis": LAST_ANALYSIS["data"]})
            if path == "/api/audit":
                return self.reply(200, {"ok": True, "entries": store.read_audit(300)})
            if path == "/api/metrics":
                return self.reply(200, {"ok": True, "text": crowdsec.metrics_text()})
        except crowdsec.CrowdSecError as exc:
            return self.fail(503, str(exc))
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
            if path == "/api/providers":
                return self.api_providers()
            if path == "/api/analyze":
                return self.api_analyze()
            if path == "/api/proposal":
                return self.api_proposal(sess)
            if path == "/api/decisions":
                return self.api_decisions(sess)
            if path == "/api/settings":
                return self.api_settings()
        except crowdsec.CrowdSecError as exc:
            return self.fail(503, str(exc))
        except ValueError as exc:
            return self.fail(400, str(exc))
        except Exception as exc:
            log.exception("POST %s", path)
            return self.fail(500, str(exc))
        return self.fail(404, "not_found")

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
                "crowdsec": crowdsec.status(),
                "providers": providers.catalog(),
                "keys": store.key_summary(),
                "ai": CFG.get("ai", default={}),
                "guard": CFG.get("guard", default={}),
                "public_url": CFG.get("public_url", default="") or "",
                "your_ip": self.client_ip(),
            })
        return self.reply(200, base)

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

    # --- panolar ---
    def api_dashboard(self, query):
        since = (query.get("since") or ["24h"])[0]
        if not re.match(r"^\d{1,4}[hd]$", since):
            since = "24h"
        status = crowdsec.status()
        payload = {"ok": True, "crowdsec": status, "since": since}
        if status.get("installed"):
            payload["summary"] = crowdsec.summarize(since=since)
            payload["decisions"] = crowdsec.decisions(limit=200)
            payload["alerts"] = crowdsec.alerts(since=since, limit=60)
            payload["collections"] = crowdsec.collections()
        else:
            payload.update({"summary": {}, "decisions": [], "alerts": [], "collections": []})
        return self.reply(200, payload)

    # --- saglayicilar ---
    def api_providers(self):
        data = self.body_json()
        action = data.get("action")
        provider = (data.get("provider") or "").strip()
        if provider and provider not in providers.PROVIDERS:
            return self.fail(400, "bilinmeyen saglayici: %s" % provider)
        if action == "save":
            key = data.get("key")
            if key is not None:
                key = key.strip()
                if key and len(key) < 8:
                    return self.fail(400, "anahtar cok kisa")
            store.save_key(provider, key=key if key else None,
                           model=(data.get("model") or "").strip(),
                           base_url=(data.get("base_url") or "").strip())
            store.audit("provider_save", {"provider": provider})
            return self.reply(200, {"ok": True, "keys": store.key_summary()})
        if action == "delete":
            store.save_key(provider, remove=True)
            store.audit("provider_delete", {"provider": provider})
            return self.reply(200, {"ok": True, "keys": store.key_summary()})
        if action == "test":
            ok, message, models = providers.test_key(provider)
            return self.reply(200, {"ok": True, "result": ok, "message": message, "models": models})
        return self.fail(400, "bad_action")

    def api_settings(self):
        data = self.body_json()
        ai = data.get("ai") or {}
        if "provider" in ai:
            value = (ai.get("provider") or "").strip()
            if value and value not in providers.PROVIDERS:
                return self.fail(400, "bilinmeyen saglayici")
            CFG.set(["ai", "provider"], value)
        if "model" in ai:
            CFG.set(["ai", "model"], (ai.get("model") or "").strip()[:80])
        guard = data.get("guard") or {}
        if "protect_private_ranges" in guard:
            CFG.set(["guard", "protect_private_ranges"], bool(guard["protect_private_ranges"]))
        if "never_ban" in guard and isinstance(guard["never_ban"], list):
            cleaned = []
            for item in guard["never_ban"][:100]:
                item = str(item).strip()
                if not item:
                    continue
                try:
                    crowdsec.parse_target(item)
                except ValueError:
                    return self.fail(400, "gecersiz adres: %s" % item)
                cleaned.append(item)
            CFG.set(["guard", "never_ban"], cleaned)
        store.audit("settings_update", {"keys": list(data.keys())})
        return self.reply(200, {"ok": True, "ai": CFG.get("ai", default={}),
                                "guard": CFG.get("guard", default={})})

    # --- AI analizi ---
    def api_analyze(self):
        data = self.body_json()
        since = (data.get("since") or "24h").strip()
        if not re.match(r"^\d{1,4}[hd]$", since):
            since = "24h"
        provider = (data.get("provider") or CFG.get("ai", "provider", default="") or "").strip()
        if not provider:
            return self.fail(400, "once bir AI saglayici secin")
        model = (data.get("model") or "").strip() or None
        note = (data.get("note") or "").strip()

        summary = crowdsec.summarize(since=since)
        if not summary.get("alert_count"):
            return self.reply(200, {"ok": True, "empty": True,
                                    "message": "Bu pencerede CrowdSec uyarisi yok."})
        messages = analyst.build_messages(summary, extra_note=note)
        started = time.time()
        text, used_model = providers.chat(
            provider, messages, model=model,
            temperature=float(CFG.get("ai", "temperature", default=0.1) or 0.1),
            timeout=int(CFG.get("ai", "timeout", default=120) or 120))
        parsed = analyst.parse_response(text)
        analysis, items = analyst.to_proposals(parsed, {
            "provider": provider, "model": used_model, "window": since})
        analysis["elapsed"] = round(time.time() - started, 1)
        analysis["source"] = {"alerts": summary.get("alert_count"),
                              "ips": summary.get("unique_ips")}
        LAST_ANALYSIS["data"] = analysis
        if items:
            store.add_proposals(items)
        store.audit("analyze", {"provider": provider, "model": used_model,
                                "window": since, "proposals": len(items)})
        return self.reply(200, {"ok": True, "analysis": analysis, "proposals": items})

    # --- oneri uygulama ---
    def api_proposal(self, sess):
        data = self.body_json()
        pid = (data.get("id") or "").strip()
        decision = (data.get("decision") or "").strip()
        proposal = None
        for item in store.load_proposals():
            if item.get("id") == pid:
                proposal = item
                break
        if not proposal:
            return self.fail(404, "oneri bulunamadi")
        if proposal.get("status") != "pending":
            return self.fail(400, "bu oneri zaten islendi (%s)" % proposal.get("status"))

        if decision == "reject":
            store.update_proposal(pid, status="rejected", resolved=int(time.time()))
            store.audit("proposal_reject", {"id": pid, "action": proposal.get("action"),
                                            "value": proposal.get("value")})
            return self.reply(200, {"ok": True, "status": "rejected"})
        if decision != "apply":
            return self.fail(400, "bad_decision")

        action = proposal.get("action")
        actor_ip = sess.get("ip")
        try:
            if action in ("ban", "ban_range"):
                output = crowdsec.add_decision(
                    proposal.get("value"), duration=proposal.get("duration") or "24h",
                    reason="agfo-ai: " + (proposal.get("reason") or ""),
                    dtype="ban", actor_ip=actor_ip)
            elif action == "allow":
                value = proposal.get("value")
                crowdsec.parse_target(value)
                never = list(CFG.get("guard", "never_ban", default=[]) or [])
                if value not in never:
                    never.append(value)
                    CFG.set(["guard", "never_ban"], never)
                try:
                    crowdsec.delete_decision(value=value)
                except Exception:
                    pass
                output = "%s korumali listeye eklendi" % value
            elif action == "install_collection":
                name = proposal.get("value") or ""
                if not re.match(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$", name):
                    return self.fail(400, "gecersiz koleksiyon adi")
                rc, out, err = crowdsec.run(["collections", "install", name], timeout=120)
                if rc != 0:
                    return self.fail(400, (err or out or "koleksiyon kurulamadi").strip()[-300:])
                crowdsec.run(["hub", "update"], timeout=60)
                output = (out or "").strip()[-300:] or "kuruldu"
            else:  # note
                output = "bilgi notu okundu"
        except ValueError as exc:
            return self.fail(400, str(exc))

        store.update_proposal(pid, status="applied", resolved=int(time.time()),
                              result=str(output)[:400])
        store.audit("proposal_apply", {"id": pid, "action": action,
                                       "value": proposal.get("value"), "by_ip": actor_ip})
        return self.reply(200, {"ok": True, "status": "applied", "result": str(output)[:400]})

    # --- elle karar ---
    def api_decisions(self, sess):
        data = self.body_json()
        action = data.get("action")
        if action == "add":
            output = crowdsec.add_decision(
                (data.get("value") or "").strip(),
                duration=(data.get("duration") or "4h").strip(),
                reason=(data.get("reason") or "panel").strip(),
                dtype="ban", actor_ip=sess.get("ip"))
            return self.reply(200, {"ok": True, "result": str(output)[:400]})
        if action == "delete":
            output = crowdsec.delete_decision(
                value=(data.get("value") or "").strip() or None,
                decision_id=data.get("id"))
            return self.reply(200, {"ok": True, "result": str(output)[:400]})
        return self.fail(400, "bad_action")


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
    bind = os.environ.get("AGFO_FW_BIND") or CFG.get("bind", default="0.0.0.0")
    port = int(os.environ.get("AGFO_FW_PORT") or CFG.get("port", default=8823))
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
    if not crowdsec.cscli_path():
        log.warning("cscli bulunamadi; panel acilir ama CrowdSec verisi gosteremez.")
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
