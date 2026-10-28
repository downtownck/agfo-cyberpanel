# -*- coding: utf-8 -*-
"""Yapilandirma, saglayici anahtarlari, oneriler ve denetim gunlugu deposu.

Harici bagimlilik yoktur. Tum dosyalar 0600 izniyle yazilir.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
CONFIG_DIR = os.environ.get("AGFO_FW_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
KEYS_PATH = os.path.join(CONFIG_DIR, "providers.json")
PROPOSALS_PATH = os.path.join(CONFIG_DIR, "proposals.json")
AUDIT_PATH = os.path.join(CONFIG_DIR, "audit.log")

DEFAULT_CONFIG = {
    "bind": "0.0.0.0",
    "port": 8823,
    "public_url": "",
    "tls": {"enabled": True, "cert": "", "key": ""},
    "auth": {"password_hash": "", "session_ttl": 43200},
    "allow_ips": [],
    "frame_ancestors": [],
    "cookie_samesite": "Strict",
    "ai": {
        "provider": "",
        "model": "",
        "max_events": 120,
        "temperature": 0.1,
        "timeout": 120,
        "language": "tr",
    },
    "guard": {
        # Bu adresler hicbir kosulda engellenemez.
        "never_ban": ["127.0.0.1", "::1"],
        "protect_private_ranges": True,
        "max_ban_duration_hours": 720,
        "require_approval": True,
    },
    "report": {"enabled": True, "window_hours": 24},
    "crowdsec": {"cscli": "", "lapi_url": ""},
}

_lock = threading.RLock()


# --------------------------------------------------------------------------
# dosya yardimcilari
# --------------------------------------------------------------------------

def _atomic_write(path, text, mode=0o600):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o700)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _read_json(path, fallback):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return fallback


def deep_merge(base, override):
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------
# yapilandirma
# --------------------------------------------------------------------------

class Config(object):
    def __init__(self):
        self.data = deep_merge(DEFAULT_CONFIG, _read_json(CONFIG_PATH, {}))

    def reload(self):
        with _lock:
            self.data = deep_merge(DEFAULT_CONFIG, _read_json(CONFIG_PATH, {}))
        return self.data

    def get(self, *path, **kw):
        default = kw.get("default")
        with _lock:
            node = self.data
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    return default
                node = node[key]
            return node

    def set(self, path, value):
        with _lock:
            node = self.data
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = value
            _atomic_write(CONFIG_PATH, json.dumps(self.data, indent=2, ensure_ascii=False))

    def save(self):
        with _lock:
            _atomic_write(CONFIG_PATH, json.dumps(self.data, indent=2, ensure_ascii=False))


CFG = Config()


# --------------------------------------------------------------------------
# sifre
# --------------------------------------------------------------------------

PBKDF2_ITER = 240000


def hash_password(password, iterations=PBKDF2_ITER, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password, stored):
    try:
        algo, iters, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


# --------------------------------------------------------------------------
# saglayici anahtarlari
# --------------------------------------------------------------------------

def load_keys():
    """{"openai": {"key": "...", "model": "...", "base_url": "..."}}"""
    return _read_json(KEYS_PATH, {})


def save_key(provider, key=None, model=None, base_url=None, remove=False):
    with _lock:
        data = _read_json(KEYS_PATH, {})
        if remove:
            data.pop(provider, None)
        else:
            entry = data.get(provider, {})
            if key is not None:
                entry["key"] = key
            if model is not None:
                entry["model"] = model
            if base_url is not None:
                entry["base_url"] = base_url
            entry["updated"] = int(time.time())
            data[provider] = entry
        _atomic_write(KEYS_PATH, json.dumps(data, indent=2, ensure_ascii=False))
        return data


def key_summary():
    """Anahtarlari asla dondurmez; yalnizca tanimli mi, son 4 hanesi ne."""
    out = {}
    for name, entry in load_keys().items():
        raw = entry.get("key") or ""
        out[name] = {
            "configured": bool(raw),
            "hint": ("…" + raw[-4:]) if len(raw) >= 4 else "",
            "model": entry.get("model") or "",
            "base_url": entry.get("base_url") or "",
            "updated": entry.get("updated") or 0,
        }
    return out


# --------------------------------------------------------------------------
# oneriler
# --------------------------------------------------------------------------

def load_proposals():
    data = _read_json(PROPOSALS_PATH, [])
    return data if isinstance(data, list) else []


def save_proposals(items):
    with _lock:
        _atomic_write(PROPOSALS_PATH, json.dumps(items[-500:], indent=2, ensure_ascii=False))


def add_proposals(new_items):
    """Yeni onerileri ekler; ayni hedef icin bekleyen eski onerileri gecersiz kilar."""
    with _lock:
        items = load_proposals()
        incoming = {(i.get("action"), i.get("value")) for i in new_items}
        for item in items:
            if item.get("status") == "pending" and (item.get("action"), item.get("value")) in incoming:
                item["status"] = "superseded"
                item["resolved"] = int(time.time())
        items.extend(new_items)
        _atomic_write(PROPOSALS_PATH, json.dumps(items[-500:], indent=2, ensure_ascii=False))
        return items


def update_proposal(pid, **fields):
    with _lock:
        items = load_proposals()
        found = None
        for item in items:
            if item.get("id") == pid:
                item.update(fields)
                found = item
                break
        if found is not None:
            _atomic_write(PROPOSALS_PATH, json.dumps(items[-500:], indent=2, ensure_ascii=False))
        return found


# --------------------------------------------------------------------------
# denetim gunlugu
# --------------------------------------------------------------------------

def audit(action, detail, actor="panel"):
    line = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "actor": actor,
        "action": action,
        "detail": detail,
    }, ensure_ascii=False)
    with _lock:
        directory = os.path.dirname(AUDIT_PATH)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, 0o700)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        try:
            os.chmod(AUDIT_PATH, 0o600)
        except Exception:
            pass


def read_audit(limit=200):
    if not os.path.exists(AUDIT_PATH):
        return []
    out = []
    try:
        with open(AUDIT_PATH, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh.readlines()[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    out.reverse()
    return out
