#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGFO SSH Terminal - web tabanli, PuTTY benzeri SSH terminali.

Tasarim notlari
---------------
* Harici Python bagimliligi YOKTUR. Sadece standart kutuphane kullanilir.
  (HTTP + WebSocket + TLS + PTY hepsi stdlib ile yazildi.)
* SSH baglantisi icin sistemdeki OpenSSH istemcisi ("ssh") gercek bir PTY
  icinde cagrilir. Boylece host key dogrulamasi, anahtar/agent destegi,
  ~/.ssh/config, ProxyJump gibi her sey OpenSSH'in kendi davranisiyla calisir;
  sifre istemi dogrudan terminalde cikar (PuTTY davranisi).
* Python 3.6+ ile uyumludur (CyberPanel sunucularindaki sistem Python'u
  3.11'in altinda olabilir).
"""

from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import hmac
import json
import logging
import os
import pty
import re
import secrets
import select
import shlex
import signal
import socket
import ssl
import struct
import subprocess
import sys
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

APP_NAME = "AGFO SSH Terminal"
APP_VERSION = "1.2.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
CONFIG_DIR = os.environ.get("AGFO_SSH_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
PROFILES_PATH = os.path.join(CONFIG_DIR, "profiles.json")
KEYS_DIR = os.path.join(CONFIG_DIR, "keys")

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

log = logging.getLogger("agfo-ssh-terminal")

# ---------------------------------------------------------------------------
# Yapilandirma
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "bind": "0.0.0.0",
    "port": 8822,
    "tls": {"enabled": True, "cert": "", "key": ""},
    "auth": {"password_hash": "", "session_ttl": 43200},
    "allow_ips": [],
    # Panele disaridan erisilen adres (menu linki bunu kullanir)
    "public_url": "",
    # CyberPanel gibi baska bir adresin paneli cerceve (iframe) icinde
    # gosterebilmesi icin o adresi buraya ekleyin:
    # "frame_ancestors": ["https://62.83.69.214:8090"]
    "frame_ancestors": [],
    # Panel baska bir ALAN ADI altindan cerceveleniyorsa "None" yapin (TLS sart).
    # Ayni host'un baska bir portundan cerceveleme icin "Strict" yeterlidir.
    "cookie_samesite": "Strict",
    "limits": {
        "max_sessions": 24,
        "max_key_upload_kb": 64,
        "idle_timeout": 0,
        "login_max_fail": 6,
        "login_lock_seconds": 900,
    },
    "session_log": {"enabled": False, "dir": "/var/log/agfo-ssh-terminal/sessions"},
    "defaults": {
        "term": "xterm-256color",
        "keepalive": 30,
        "connect_timeout": 15,
        "host_key_policy": "accept-new",
        "local_shell": "",
        "scrollback": 5000,
        "font_size": 14,
        "theme": "agfo-dark",
    },
}


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        raw = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except Exception as exc:  # bozuk config servisi dusurmesin
                log.error("config.json okunamadi (%s), varsayilanlar kullaniliyor", exc)
                raw = {}
        with self.lock:
            self.data = deep_merge(DEFAULT_CONFIG, raw)
        return self.data

    def get(self, *path, **kw):
        default = kw.get("default")
        with self.lock:
            node = self.data
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return node

    def save(self):
        with self.lock:
            payload = json.dumps(self.data, indent=2, ensure_ascii=False)
        atomic_write(CONFIG_PATH, payload, mode=0o600)


def atomic_write(path, text, mode=0o640):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


CFG = Config()

# ---------------------------------------------------------------------------
# Sifre / oturum yonetimi
# ---------------------------------------------------------------------------

PBKDF2_ITER = 240000


def hash_password(password, iterations=PBKDF2_ITER, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password, stored):
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


class SessionStore(object):
    """Bellek ici oturum deposu. Servis yeniden baslayinca oturumlar duser."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def create(self, ip):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        ttl = int(CFG.get("auth", "session_ttl", default=43200) or 43200)
        with self.lock:
            self.items[token] = {
                "ip": ip,
                "csrf": csrf,
                "expires": time.time() + ttl,
                "created": time.time(),
            }
        return token, csrf

    def get(self, token):
        if not token:
            return None
        now = time.time()
        with self.lock:
            item = self.items.get(token)
            if not item:
                return None
            if item["expires"] < now:
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
    """IP basina kaba kuvvet korumasi."""

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
        limit = int(CFG.get("limits", "login_max_fail", default=6) or 6)
        lock_s = int(CFG.get("limits", "login_lock_seconds", default=900) or 900)
        with self.lock:
            rec = self.fails.setdefault(ip, {"count": 0, "until": 0})
            rec["count"] += 1
            if rec["count"] >= limit:
                rec["until"] = time.time() + lock_s
                rec["count"] = 0

    def clear(self, ip):
        with self.lock:
            self.fails.pop(ip, None)


GUARD = LoginGuard()

# ---------------------------------------------------------------------------
# Profiller ve anahtarlar
# ---------------------------------------------------------------------------

PROFILE_LOCK = threading.Lock()
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9 ._@\-()]{1,64}$")
SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
HOST_RE = re.compile(r"^[A-Za-z0-9._\-:\[\]]{1,255}$")
USER_RE = re.compile(r"^[A-Za-z0-9._\-\\$]{1,64}$")
OPT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,48}$")

# Ek seçeneklerde kabul edilen bayraklar (deger almayanlar)
ALLOWED_FLAGS = {"-C", "-4", "-6", "-A", "-T", "-q", "-v", "-vv", "-vvv"}
# "-o Key=Value" icin yasakli anahtarlar: komut calistirma / yerel dosya riski
BLOCKED_OPTIONS = {
    "permitlocalcommand",
    "localcommand",
    "proxycommand",
    "proxyusefdpass",
    "remotecommand",
    "include",
}


def load_profiles():
    with PROFILE_LOCK:
        if not os.path.exists(PROFILES_PATH):
            return []
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.error("profiles.json okunamadi: %s", exc)
            return []


def store_profiles(items):
    with PROFILE_LOCK:
        atomic_write(PROFILES_PATH, json.dumps(items, indent=2, ensure_ascii=False), 0o600)


def list_keys():
    out = []
    if not os.path.isdir(KEYS_DIR):
        return out
    for name in sorted(os.listdir(KEYS_DIR)):
        if name.endswith(".pub") or not SAFE_FILE_RE.match(name):
            continue
        path = os.path.join(KEYS_DIR, name)
        if os.path.isfile(path):
            out.append({"name": name, "size": os.path.getsize(path)})
    return out


def key_path(name):
    if not name:
        return ""
    if not SAFE_FILE_RE.match(name):
        raise ValueError("Gecersiz anahtar adi")
    path = os.path.join(KEYS_DIR, name)
    if not os.path.isfile(path):
        raise ValueError("Anahtar bulunamadi: %s" % name)
    return path


# ---------------------------------------------------------------------------
# PTY oturumu
# ---------------------------------------------------------------------------


class PtySession(object):
    """Bir alt sureci gercek bir PTY icinde calistirir ve iki yonlu tasir."""

    def __init__(self, argv, env, cols, rows, on_output, on_exit, log_path=None, cwd="/"):
        self.argv = argv
        self.env = env
        self.cols = max(20, min(int(cols or 80), 500))
        self.rows = max(5, min(int(rows or 24), 200))
        self.on_output = on_output
        self.on_exit = on_exit
        self.log_path = log_path
        self.cwd = cwd
        self.master_fd = None
        self.proc = None
        self.logfh = None
        self.alive = False
        self.last_io = time.time()
        self.bytes_in = 0
        self.bytes_out = 0
        self._wlock = threading.Lock()
        self._reader = None

    def start(self):
        master, slave = pty.openpty()
        try:
            self._set_winsize(master, self.rows, self.cols)
            self.proc = subprocess.Popen(
                self.argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                close_fds=True,
                cwd=self.cwd,
                env=self.env,
                preexec_fn=os.setsid,
            )
        finally:
            os.close(slave)
        self.master_fd = master
        self.alive = True
        if self.log_path:
            try:
                directory = os.path.dirname(self.log_path)
                if not os.path.isdir(directory):
                    os.makedirs(directory, 0o700)
                self.logfh = open(self.log_path, "ab", 0)
                os.chmod(self.log_path, 0o600)
                header = "=== %s | %s | %s ===\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    APP_NAME,
                    " ".join(self.argv),
                )
                self.logfh.write(header.encode("utf-8"))
            except Exception as exc:
                log.warning("oturum kaydi acilamadi: %s", exc)
                self.logfh = None
        self._reader = threading.Thread(target=self._read_loop, name="pty-read", daemon=True)
        self._reader.start()

    @staticmethod
    def _set_winsize(fd, rows, cols):
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass

    def _read_loop(self):
        fd = self.master_fd
        while self.alive:
            try:
                ready, _, _ = select.select([fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    data = b""
                elif exc.errno == errno.EINTR:
                    continue
                else:
                    data = b""
            if not data:
                break
            self.last_io = time.time()
            self.bytes_out += len(data)
            if self.logfh:
                try:
                    self.logfh.write(data)
                except Exception:
                    pass
            try:
                self.on_output(data)
            except Exception:
                break
        code = None
        if self.proc is not None:
            try:
                code = self.proc.wait(timeout=5)
            except Exception:
                code = None
        self.alive = False
        self._cleanup()
        try:
            self.on_exit(code)
        except Exception:
            pass

    def write(self, data):
        if not self.alive or self.master_fd is None:
            return
        with self._wlock:
            try:
                total = 0
                while total < len(data):
                    total += os.write(self.master_fd, data[total:])
                self.bytes_in += total
                self.last_io = time.time()
            except OSError:
                self.alive = False

    def resize(self, cols, rows):
        self.cols = max(20, min(int(cols or 80), 500))
        self.rows = max(5, min(int(rows or 24), 200))
        if self.master_fd is not None:
            self._set_winsize(self.master_fd, self.rows, self.cols)
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGWINCH)
            except Exception:
                pass

    def send_signal(self, signame):
        mapping = {
            "INT": signal.SIGINT,
            "TERM": signal.SIGTERM,
            "HUP": signal.SIGHUP,
            "QUIT": signal.SIGQUIT,
            "KILL": signal.SIGKILL,
        }
        sig = mapping.get((signame or "").upper())
        if sig and self.proc is not None:
            try:
                os.killpg(os.getpgid(self.proc.pid), sig)
            except Exception:
                pass

    def close(self):
        self.alive = False
        if self.proc is not None and self.proc.poll() is None:
            for sig in (signal.SIGHUP, signal.SIGTERM):
                try:
                    os.killpg(os.getpgid(self.proc.pid), sig)
                except Exception:
                    break
                try:
                    self.proc.wait(timeout=2)
                    break
                except Exception:
                    continue
            if self.proc.poll() is None:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self._cleanup()

    def _cleanup(self):
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None
        if self.logfh:
            try:
                self.logfh.close()
            except Exception:
                pass
            self.logfh = None


SESSION_COUNT_LOCK = threading.Lock()
ACTIVE_SESSIONS = {"n": 0}


def session_slot_acquire():
    limit = int(CFG.get("limits", "max_sessions", default=24) or 24)
    with SESSION_COUNT_LOCK:
        if ACTIVE_SESSIONS["n"] >= limit:
            return False
        ACTIVE_SESSIONS["n"] += 1
        return True


def session_slot_release():
    with SESSION_COUNT_LOCK:
        ACTIVE_SESSIONS["n"] = max(0, ACTIVE_SESSIONS["n"] - 1)


# ---------------------------------------------------------------------------
# SSH komut satiri uretimi
# ---------------------------------------------------------------------------


def which(binary):
    for directory in (os.environ.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin").split(os.pathsep):
        candidate = os.path.join(directory, binary)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def sanitize_extra(extra):
    """Kullanicinin verdigi ek ssh seceneklerini beyaz listeye gore suzer."""
    if not extra:
        return []
    try:
        tokens = shlex.split(extra)
    except ValueError:
        raise ValueError("Ek secenekler ayristirilamadi (tirnak hatasi)")
    out = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ALLOWED_FLAGS:
            out.append(tok)
            i += 1
            continue
        if tok == "-o":
            if i + 1 >= len(tokens):
                raise ValueError("-o sonrasinda Anahtar=Deger bekleniyor")
            pair = tokens[i + 1]
            if "=" not in pair:
                raise ValueError("Gecersiz -o degeri: %s" % pair)
            key, value = pair.split("=", 1)
            if not OPT_KEY_RE.match(key):
                raise ValueError("Gecersiz -o anahtari: %s" % key)
            if key.lower() in BLOCKED_OPTIONS:
                raise ValueError("Bu -o anahtari guvenlik nedeniyle engelli: %s" % key)
            if "\n" in value or "\r" in value:
                raise ValueError("Gecersiz -o degeri")
            out.extend(["-o", "%s=%s" % (key, value)])
            i += 2
            continue
        raise ValueError("Izin verilmeyen ek secenek: %s" % tok)
    return out


def build_ssh_argv(req):
    ssh_bin = which("ssh")
    if not ssh_bin:
        raise ValueError("Sunucuda 'ssh' istemcisi bulunamadi (openssh-clients kurulu mu?)")

    host = (req.get("host") or "").strip()
    if not host or not HOST_RE.match(host):
        raise ValueError("Gecersiz host")
    port = int(req.get("port") or 22)
    if port < 1 or port > 65535:
        raise ValueError("Gecersiz port")
    user = (req.get("user") or "").strip()
    if user and not USER_RE.match(user):
        raise ValueError("Gecersiz kullanici adi")

    policy = (req.get("host_key_policy") or CFG.get("defaults", "host_key_policy", default="accept-new"))
    if policy not in ("yes", "accept-new", "no"):
        policy = "accept-new"
    keepalive = int(req.get("keepalive") or CFG.get("defaults", "keepalive", default=30) or 30)
    keepalive = max(0, min(keepalive, 600))
    timeout = int(req.get("connect_timeout") or CFG.get("defaults", "connect_timeout", default=15) or 15)
    timeout = max(3, min(timeout, 120))

    argv = [ssh_bin, "-tt", "-p", str(port)]
    argv += ["-o", "StrictHostKeyChecking=%s" % policy]
    argv += ["-o", "ServerAliveInterval=%d" % keepalive, "-o", "ServerAliveCountMax=3"]
    argv += ["-o", "ConnectTimeout=%d" % timeout]
    argv += ["-o", "NumberOfPasswordPrompts=3"]
    argv += ["-o", "PermitLocalCommand=no"]
    argv += ["-o", "ControlMaster=no"]
    if not req.get("agent"):
        argv += ["-o", "IdentityAgent=none"]
    if req.get("compression"):
        argv += ["-C"]

    identity = (req.get("identity") or "").strip()
    if identity:
        argv += ["-i", key_path(identity), "-o", "IdentitiesOnly=yes"]

    jump = (req.get("jump") or "").strip()
    if jump:
        if not re.match(r"^[A-Za-z0-9._@\-:\[\],]{1,255}$", jump):
            raise ValueError("Gecersiz ProxyJump degeri")
        argv += ["-J", jump]

    argv += sanitize_extra(req.get("extra"))

    if user:
        argv += ["-l", user]
    argv += ["--", host]

    command = (req.get("command") or "").strip()
    if command:
        if "\n" in command or "\r" in command:
            raise ValueError("Uzak komut tek satir olmali")
        argv.append(command)
    return argv


def build_local_argv(req):
    shell = (CFG.get("defaults", "local_shell", default="") or "").strip()
    if not shell:
        for candidate in ("/bin/bash", "/usr/bin/bash", "/bin/sh"):
            if os.path.isfile(candidate):
                shell = candidate
                break
    if not shell or not os.path.isfile(shell):
        raise ValueError("Yerel kabuk bulunamadi")
    return [shell, "-l"]


def build_env(req):
    term = (req.get("term") or CFG.get("defaults", "term", default="xterm-256color")) or "xterm-256color"
    if not re.match(r"^[A-Za-z0-9._\-]{1,32}$", term):
        term = "xterm-256color"
    home = os.path.expanduser("~")
    env = {
        "TERM": term,
        "HOME": home,
        "USER": os.environ.get("USER", "root"),
        "LOGNAME": os.environ.get("LOGNAME", "root"),
        "SHELL": os.environ.get("SHELL", "/bin/bash"),
        "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "LC_ALL": os.environ.get("LC_ALL") or "C.UTF-8",
        "COLORTERM": "truecolor",
        "AGFO_SSH_TERMINAL": APP_VERSION,
        "SSH_ASKPASS_REQUIRE": "never",
    }
    if os.environ.get("SSH_AUTH_SOCK") and req.get("agent"):
        env["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
    return env


# ---------------------------------------------------------------------------
# WebSocket cercevesi
# ---------------------------------------------------------------------------

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_FRAME = 4 * 1024 * 1024


class WSClosed(Exception):
    pass


class WSConn(object):
    def __init__(self, handler):
        self.handler = handler
        self.rfile = handler.rfile
        self.wfile = handler.wfile
        self.lock = threading.Lock()
        self.closed = False

    # --- okuma ---
    def _read_exact(self, n):
        data = self.rfile.read(n)
        if data is None or len(data) < n:
            raise WSClosed()
        return data

    def recv(self):
        """Bir mesaj dondur: (opcode, bytes). Parcali mesajlari birlestirir."""
        frags = bytearray()
        frag_op = None
        while True:
            head = self._read_exact(2)
            b1, b2 = head[0], head[1]
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > MAX_FRAME:
                raise WSClosed()
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length) if length else b""
            if mask:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))

            if opcode == OP_CLOSE:
                raise WSClosed()
            if opcode == OP_PING:
                self.send(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CONT:
                if frag_op is None:
                    raise WSClosed()
                frags += payload
                if fin:
                    return frag_op, bytes(frags)
                continue
            # yeni veri cercevesi
            if not fin:
                frag_op = opcode
                frags = bytearray(payload)
                continue
            return opcode, payload

    # --- yazma ---
    def send(self, opcode, payload=b""):
        if self.closed:
            return
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += struct.pack("!H", n)
        else:
            header.append(127)
            header += struct.pack("!Q", n)
        with self.lock:
            if self.closed:
                return
            try:
                self.wfile.write(bytes(header) + payload)
                self.wfile.flush()
            except Exception:
                self.closed = True

    def send_json(self, obj):
        self.send(OP_TEXT, json.dumps(obj, ensure_ascii=False))

    def send_bin(self, data):
        self.send(OP_BIN, data)

    def close(self, code=1000, reason="bye"):
        if self.closed:
            return
        try:
            self.send(OP_CLOSE, struct.pack("!H", code) + reason.encode("utf-8")[:120])
        except Exception:
            pass
        self.closed = True

    def shutdown(self):
        """Okuma dongusunu da serbest birakmak icin soketi kapat."""
        self.closed = True
        try:
            self.handler.connection.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP sunucu
# ---------------------------------------------------------------------------

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json",
}

COOKIE_NAME = "agfo_sshterm"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AGFO-SSH-Terminal/" + APP_VERSION
    sys_version = ""

    # --- yardimcilar ---
    def log_message(self, fmt, *args):
        log.info("%s %s", self.client_address[0], fmt % args)

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
            if entry == ip:
                return True
            if entry.endswith("*") and ip.startswith(entry[:-1]):
                return True
        return False

    def cookies(self):
        raw = self.headers.get("Cookie") or ""
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = unquote(v.strip())
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
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
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
            # X-Frame-Options birden fazla adres ifade edemez; liste verildiginde
            # yalnizca CSP frame-ancestors kullanilir (modern tarayicilarda gecerli).
            frame_rule = "frame-ancestors 'self' " + " ".join(ancestors)
        else:
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            frame_rule = "frame-ancestors 'self'"
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self'; "
            "base-uri 'none'; form-action 'none'; " + frame_rule,
        )
        if self.secure_cookie():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in (extra or {}).items():
            self.send_header(k, v)

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

    def require_session(self):
        sess = self.session()
        if not sess:
            self.reply(401, {"ok": False, "error": "auth_required"})
            return None
        return sess

    def check_csrf(self, sess):
        token = self.headers.get("X-AGFO-CSRF") or ""
        if not token or not hmac.compare_digest(token, sess.get("csrf", "")):
            self.reply(403, {"ok": False, "error": "csrf"})
            return False
        return True

    def same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True  # tarayici disi istemciler (ornek: test betikleri)
        host = (self.headers.get("Host") or "").strip()
        try:
            parsed = urlparse(origin)
        except Exception:
            return False
        return parsed.netloc == host

    # --- yonlendirme ---
    def do_GET(self):
        if not self.ip_allowed():
            return self.reply(403, {"ok": False, "error": "ip_not_allowed"})
        path = urlparse(self.path).path
        if path == "/healthz":
            return self.reply(200, {"ok": True, "app": APP_NAME, "version": APP_VERSION})
        if path == "/ws":
            return self.handle_ws()
        if path == "/api/state":
            return self.api_state()
        if path == "/api/keys":
            sess = self.require_session()
            if sess:
                self.reply(200, {"ok": True, "keys": list_keys()})
            return
        if path in ("/", "/index.html"):
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])
        return self.reply(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not self.ip_allowed():
            return self.reply(403, {"ok": False, "error": "ip_not_allowed"})
        if not self.same_origin():
            return self.reply(403, {"ok": False, "error": "bad_origin"})
        path = urlparse(self.path).path
        if path == "/api/login":
            return self.api_login()
        sess = self.require_session()
        if not sess:
            return
        if not self.check_csrf(sess):
            return
        if path == "/api/logout":
            SESSIONS.drop(sess.get("_token"))
            same_site = str(CFG.get("cookie_samesite", default="Strict") or "Strict")
            if same_site not in ("Strict", "Lax", "None"):
                same_site = "Strict"
            return self.reply(200, {"ok": True}, extra={
                "Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=%s%s" % (
                    COOKIE_NAME, same_site, "; Secure" if (self.secure_cookie() or same_site == "None") else "")
            })
        if path == "/api/profiles":
            return self.api_profiles()
        if path == "/api/keys":
            return self.api_keys_write()
        if path == "/api/password":
            return self.api_password()
        return self.reply(404, {"ok": False, "error": "not_found"})

    # --- statik ---
    def serve_static(self, rel):
        rel = rel.split("?")[0].lstrip("/")
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            return self.reply(404, {"ok": False, "error": "not_found"})
        ext = os.path.splitext(target)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(target, "rb") as fh:
                data = fh.read()
        except Exception:
            return self.reply(500, {"ok": False, "error": "read_error"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if rel.startswith("vendor/"):
            self.send_header("Cache-Control", "public, max-age=604800")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.send_common()
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    # --- API ---
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
                "profiles": load_profiles(),
                "keys": list_keys(),
                "defaults": CFG.get("defaults", default={}),
                "session_log": bool(CFG.get("session_log", "enabled", default=False)),
                "ssh_available": bool(which("ssh")),
            "public_url": CFG.get("public_url", default="") or "",
                "active_sessions": ACTIVE_SESSIONS["n"],
                "max_sessions": CFG.get("limits", "max_sessions", default=24),
            })
        return self.reply(200, base)

    def api_login(self):
        ip = self.client_ip()
        locked = GUARD.locked_for(ip)
        if locked > 0:
            return self.reply(429, {"ok": False, "error": "locked", "retry_after": locked})
        data = self.body_json(limit=8192)
        password = data.get("password") or ""
        stored = CFG.get("auth", "password_hash", default="") or ""
        if not stored:
            return self.reply(500, {"ok": False, "error": "no_password_configured"})
        time.sleep(0.25)  # zamanlama saldirilarini kabaca yavaslat
        if not verify_password(password, stored):
            GUARD.record_fail(ip)
            log.warning("basarisiz giris denemesi: %s", ip)
            return self.reply(401, {"ok": False, "error": "bad_password"})
        GUARD.clear(ip)
        token, csrf = SESSIONS.create(ip)
        same_site = str(CFG.get("cookie_samesite", default="Strict") or "Strict")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Strict"
        secure = self.secure_cookie() or same_site == "None"
        cookie = "%s=%s; Path=/; HttpOnly; SameSite=%s; Max-Age=%d%s" % (
            COOKIE_NAME,
            token,
            same_site,
            int(CFG.get("auth", "session_ttl", default=43200) or 43200),
            "; Secure" if secure else "",
        )
        log.info("giris basarili: %s", ip)
        return self.reply(200, {"ok": True, "csrf": csrf}, extra={"Set-Cookie": cookie})

    def api_password(self):
        data = self.body_json(limit=8192)
        current = data.get("current") or ""
        new = data.get("new") or ""
        stored = CFG.get("auth", "password_hash", default="") or ""
        if not verify_password(current, stored):
            return self.reply(401, {"ok": False, "error": "bad_password"})
        if len(new) < 10:
            return self.reply(400, {"ok": False, "error": "too_short"})
        with CFG.lock:
            CFG.data["auth"]["password_hash"] = hash_password(new)
        CFG.save()
        return self.reply(200, {"ok": True})

    def api_profiles(self):
        data = self.body_json()
        action = data.get("action")
        items = load_profiles()
        if action == "save":
            prof = data.get("profile") or {}
            name = (prof.get("name") or "").strip()
            if not SAFE_NAME_RE.match(name):
                return self.reply(400, {"ok": False, "error": "bad_name"})
            clean = {
                "id": prof.get("id") or secrets.token_hex(8),
                "name": name,
                "mode": "local" if prof.get("mode") == "local" else "ssh",
                "host": (prof.get("host") or "").strip()[:255],
                "port": int(prof.get("port") or 22),
                "user": (prof.get("user") or "").strip()[:64],
                "identity": (prof.get("identity") or "").strip()[:64],
                "jump": (prof.get("jump") or "").strip()[:255],
                "extra": (prof.get("extra") or "").strip()[:512],
                "command": (prof.get("command") or "").strip()[:512],
                "agent": bool(prof.get("agent")),
                "compression": bool(prof.get("compression")),
                "keepalive": int(prof.get("keepalive") or 30),
                "host_key_policy": prof.get("host_key_policy") or "accept-new",
                "theme": (prof.get("theme") or "agfo-dark")[:32],
                "font_size": int(prof.get("font_size") or 14),
                "log": bool(prof.get("log")),
            }
            replaced = False
            for idx, existing in enumerate(items):
                if existing.get("id") == clean["id"]:
                    items[idx] = clean
                    replaced = True
                    break
            if not replaced:
                if len(items) >= 200:
                    return self.reply(400, {"ok": False, "error": "too_many_profiles"})
                items.append(clean)
            store_profiles(items)
            return self.reply(200, {"ok": True, "profiles": items, "saved": clean})
        if action == "delete":
            pid = data.get("id")
            items = [p for p in items if p.get("id") != pid]
            store_profiles(items)
            return self.reply(200, {"ok": True, "profiles": items})
        if action == "reorder":
            order = data.get("order") or []
            index = {p.get("id"): p for p in items}
            new_items = [index[i] for i in order if i in index]
            new_items += [p for p in items if p.get("id") not in order]
            store_profiles(new_items)
            return self.reply(200, {"ok": True, "profiles": new_items})
        return self.reply(400, {"ok": False, "error": "bad_action"})

    def api_keys_write(self):
        data = self.body_json(limit=512 * 1024)
        action = data.get("action")
        if not os.path.isdir(KEYS_DIR):
            os.makedirs(KEYS_DIR, 0o700)
        if action == "upload":
            name = (data.get("name") or "").strip()
            content = data.get("content") or ""
            if not SAFE_FILE_RE.match(name):
                return self.reply(400, {"ok": False, "error": "bad_name"})
            max_kb = int(CFG.get("limits", "max_key_upload_kb", default=64) or 64)
            if len(content.encode("utf-8")) > max_kb * 1024:
                return self.reply(400, {"ok": False, "error": "too_large"})
            if "PRIVATE KEY" not in content:
                return self.reply(400, {"ok": False, "error": "not_a_private_key"})
            if not content.endswith("\n"):
                content += "\n"
            path = os.path.join(KEYS_DIR, name)
            atomic_write(path, content, 0o600)
            return self.reply(200, {"ok": True, "keys": list_keys()})
        if action == "delete":
            name = (data.get("name") or "").strip()
            if not SAFE_FILE_RE.match(name):
                return self.reply(400, {"ok": False, "error": "bad_name"})
            path = os.path.join(KEYS_DIR, name)
            if os.path.isfile(path):
                os.unlink(path)
            return self.reply(200, {"ok": True, "keys": list_keys()})
        return self.reply(400, {"ok": False, "error": "bad_action"})

    # --- WebSocket ---
    def handle_ws(self):
        if (self.headers.get("Upgrade") or "").lower() != "websocket":
            return self.reply(400, {"ok": False, "error": "expected_websocket"})
        if not self.same_origin():
            return self.reply(403, {"ok": False, "error": "bad_origin"})
        sess = self.session()
        if not sess:
            return self.reply(401, {"ok": False, "error": "auth_required"})
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            return self.reply(400, {"ok": False, "error": "missing_key"})
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("utf-8")).digest()
        ).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.flush()
        except Exception:
            return
        ws = WSConn(self)
        TerminalBridge(ws, self.client_ip()).run()


class TerminalBridge(object):
    """WebSocket <-> PTY koprusu."""

    def __init__(self, ws, ip):
        self.ws = ws
        self.ip = ip
        self.sess = None
        self.slot = False
        self.stop = threading.Event()

    def run(self):
        pinger = threading.Thread(target=self._ping_loop, name="ws-ping", daemon=True)
        pinger.start()
        try:
            while True:
                opcode, payload = self.ws.recv()
                if opcode == OP_BIN:
                    if self.sess:
                        self.sess.write(payload)
                elif opcode == OP_TEXT:
                    self._control(payload)
        except WSClosed:
            pass
        except Exception as exc:
            log.debug("ws dongusu bitti: %s", exc)
        finally:
            self.stop.set()
            self._teardown()

    def _ping_loop(self):
        while not self.stop.wait(25):
            try:
                self.ws.send(OP_PING, b"agfo")
            except Exception:
                return
            idle = int(CFG.get("limits", "idle_timeout", default=0) or 0)
            if idle and self.sess and (time.time() - self.sess.last_io) > idle:
                self.ws.send_json({"t": "info", "msg": "Hareketsizlik nedeniyle oturum kapatildi."})
                self.stop.set()
                self._teardown()
                return

    def _control(self, payload):
        try:
            msg = json.loads(payload.decode("utf-8"))
        except Exception:
            return
        kind = msg.get("t")
        if kind == "open":
            self._open(msg)
        elif kind == "resize" and self.sess:
            self.sess.resize(msg.get("cols"), msg.get("rows"))
        elif kind == "signal" and self.sess:
            self.sess.send_signal(msg.get("sig"))
        elif kind == "ping":
            self.ws.send_json({"t": "pong", "ts": msg.get("ts")})
        elif kind == "close":
            self._teardown()

    def _open(self, msg):
        if self.sess is not None:
            self.ws.send_json({"t": "error", "msg": "Bu baglanti icin oturum zaten acik."})
            return
        if not session_slot_acquire():
            self.ws.send_json({"t": "error", "msg": "Esanli oturum sinirina ulasildi."})
            return
        self.slot = True
        mode = "local" if msg.get("mode") == "local" else "ssh"
        try:
            argv = build_local_argv(msg) if mode == "local" else build_ssh_argv(msg)
        except ValueError as exc:
            self.ws.send_json({"t": "error", "msg": str(exc)})
            session_slot_release()
            self.slot = False
            return
        except Exception as exc:
            self.ws.send_json({"t": "error", "msg": "Baglanti hazirlanamadi: %s" % exc})
            session_slot_release()
            self.slot = False
            return

        log_path = None
        if msg.get("log") and CFG.get("session_log", "enabled", default=False):
            directory = CFG.get("session_log", "dir", default="/var/log/agfo-ssh-terminal/sessions")
            label = re.sub(r"[^A-Za-z0-9._\-]", "_", (msg.get("host") or mode))[:40]
            log_path = os.path.join(
                directory, "%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), label)
            )

        self.sess = PtySession(
            argv=argv,
            env=build_env(msg),
            cols=msg.get("cols"),
            rows=msg.get("rows"),
            on_output=self._on_output,
            on_exit=self._on_exit,
            log_path=log_path,
        )
        try:
            self.sess.start()
        except Exception as exc:
            self.ws.send_json({"t": "error", "msg": "Surec baslatilamadi: %s" % exc})
            self.sess = None
            session_slot_release()
            self.slot = False
            return
        log.info(
            "oturum acildi ip=%s mode=%s hedef=%s", self.ip, mode, msg.get("host") or "local"
        )
        self.ws.send_json({
            "t": "ready",
            "mode": mode,
            "cmd": " ".join(shlex.quote(a) for a in argv),
            "log": log_path or "",
        })

    def _on_output(self, data):
        self.ws.send_bin(data)

    def _on_exit(self, code):
        try:
            self.ws.send_json({"t": "exit", "code": code})
        except Exception:
            pass
        if self.slot:
            session_slot_release()
            self.slot = False
        self.sess = None

    def _teardown(self):
        sess, self.sess = self.sess, None
        if sess:
            sess.close()
        if self.slot:
            session_slot_release()
            self.slot = False
        try:
            self.ws.close()
        except Exception:
            pass
        if self.stop.is_set():
            # Sunucu tarafindan kapatma (ornek: hareketsizlik): okuma dongusu
            # bloke kalmasin diye soketi de indir.
            self.ws.shutdown()


class ThreadedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ssl.SSLError, ConnectionResetError, BrokenPipeError, TimeoutError)):
            log.debug("baglanti hatasi %s: %s", client_address, exc)
            return
        log.exception("istek hatasi %s", client_address)


def build_tls_context():
    cert = CFG.get("tls", "cert", default="") or os.path.join(CONFIG_DIR, "tls", "server.crt")
    key = CFG.get("tls", "key", default="") or os.path.join(CONFIG_DIR, "tls", "server.key")
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        raise RuntimeError("TLS acik ama sertifika bulunamadi: %s / %s" % (cert, key))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    try:
        ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:!aNULL:!MD5")
    except ssl.SSLError:
        pass
    return ctx


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    bind = os.environ.get("AGFO_SSH_BIND") or CFG.get("bind", default="0.0.0.0")
    port = int(os.environ.get("AGFO_SSH_PORT") or CFG.get("port", default=8822))

    if not CFG.get("auth", "password_hash", default=""):
        log.error("config.json icinde auth.password_hash yok. Kurulum betigini calistirin.")
        sys.exit(2)

    if ":" in bind:
        ThreadedServer.address_family = socket.AF_INET6

    httpd = ThreadedServer((bind, port), Handler)
    scheme = "http"
    if CFG.get("tls", "enabled", default=True):
        ctx = build_tls_context()
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    if not which("ssh"):
        log.warning("'ssh' istemcisi PATH'te bulunamadi; yalnizca yerel kabuk calisir.")

    ancestors = CFG.get("frame_ancestors", default=[]) or []
    if ancestors:
        log.info("cerceveleme izinli adresler: %s", ", ".join(str(a) for a in ancestors))
    if str(CFG.get("cookie_samesite", default="Strict")) == "None" and not CFG.get("tls", "enabled", default=True):
        log.warning("cookie_samesite=None yalnizca HTTPS ile calisir; tarayici cerezi reddedecektir.")

    log.info("%s %s dinlemede: %s://%s:%d", APP_NAME, APP_VERSION, scheme, bind, port)

    def shutdown(signum, frame):
        log.info("kapatiliyor (signal %s)", signum)
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
