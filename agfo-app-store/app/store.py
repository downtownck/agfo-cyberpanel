# -*- coding: utf-8 -*-
"""Yapilandirma, kurulum isleri ve denetim gunlugu deposu."""
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
CONFIG_DIR = os.environ.get("AGFO_STORE_CONFIG_DIR", os.path.join(ROOT_DIR, "config"))
CATALOG_DIR = os.environ.get("AGFO_STORE_CATALOG_DIR", os.path.join(BASE_DIR, "catalog"))
WORK_DIR = os.environ.get("AGFO_STORE_WORK_DIR", os.path.join(ROOT_DIR, "work"))
TOOLS_DIR = os.path.join(ROOT_DIR, "tools")

CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
JOBS_PATH = os.path.join(CONFIG_DIR, "jobs.json")
INSTALLS_PATH = os.path.join(CONFIG_DIR, "installs.json")
AUDIT_PATH = os.path.join(CONFIG_DIR, "audit.log")
KEYS_PATH = os.path.join(CONFIG_DIR, "providers.json")
OVERRIDES_PATH = os.path.join(CONFIG_DIR, "catalog-overrides.json")
PROPOSALS_PATH = os.path.join(CONFIG_DIR, "catalog-proposals.json")
# Firewall AI'ya girilmis anahtarlar burada da kullanilir (yeniden girmeye gerek yok).
SHARED_KEYS_PATHS = [p for p in os.environ.get(
    "AGFO_STORE_SHARED_KEYS", "/opt/agfo-firewall-ai/config/providers.json").split(",") if p]

DEFAULT_CONFIG = {
    "bind": "0.0.0.0",
    "port": 8824,
    "public_url": "",
    "tls": {"enabled": True, "cert": "", "key": ""},
    "auth": {"password_hash": "", "session_ttl": 43200,
             "login_token": "", "token_login": True},
    "allow_ips": [],
    "frame_ancestors": [],
    "cookie_samesite": "Strict",
    "cyberpanel": {
        "cli": "",                 # bos ise otomatik bulunur
        "default_owner": "admin",
        "default_package": "Default",
        "default_php": "8.2",
        "issue_ssl": True,
        "test_domain": "",                # saglik testi deneme kurulumlari icin
    },
    "limits": {"max_concurrent_jobs": 2, "job_log_lines": 4000, "download_timeout": 900},
    "network": {"allow_downloads": True, "github_token": ""},
    "ai": {"provider": "", "model": "", "send_logs": True},
}

_lock = threading.RLock()


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


class Config(object):
    def __init__(self):
        self.data = deep_merge(DEFAULT_CONFIG, _read_json(CONFIG_PATH, {}))

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


CFG = Config()

# --------------------------------------------------------------------------
# sifre
# --------------------------------------------------------------------------

PBKDF2_ITER = 240000


def hash_password(password, iterations=PBKDF2_ITER, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, base64.b64encode(salt).decode(),
                                       base64.b64encode(dk).decode())


def verify_password(password, stored):
    try:
        algo, iters, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:
        return False


# --------------------------------------------------------------------------
# kurulum isleri
# --------------------------------------------------------------------------

def load_jobs():
    data = _read_json(JOBS_PATH, [])
    return data if isinstance(data, list) else []


def save_jobs(items):
    with _lock:
        _atomic_write(JOBS_PATH, json.dumps(items[-200:], indent=2, ensure_ascii=False))


def add_job(job):
    with _lock:
        items = load_jobs()
        items.append(job)
        _atomic_write(JOBS_PATH, json.dumps(items[-200:], indent=2, ensure_ascii=False))
    return job


def update_job(job_id, **fields):
    with _lock:
        items = load_jobs()
        for item in items:
            if item.get("id") == job_id:
                item.update(fields)
                _atomic_write(JOBS_PATH, json.dumps(items[-200:], indent=2, ensure_ascii=False))
                return item
    return None


def recover_stale_jobs():
    """Servis baslarken 'queued/running' kalmis isleri hata olarak kapatir.

    Is parcaciklari surec icinde yasar; servis yeniden basladiysa bu isler
    artik hicbir yerde calismiyordur ve sonsuza dek 'calisiyor' gorunmemeli.
    """
    with _lock:
        items = load_jobs()
        changed = 0
        recovered = []
        for item in items:
            if item.get("status") in ("queued", "running"):
                recovered.append(dict(item))
                item["status"] = "error"
                item["finished"] = int(time.time())
                item["error"] = ("Servis yeniden basladigi icin is yarida kaldi. "
                                 "Site ve veritabani kismen olusmus olabilir; "
                                 "kontrol edip yeniden kurun.")
                changed += 1
        if changed:
            save_jobs(items)
        return recovered


def get_job(job_id):
    for item in load_jobs():
        if item.get("id") == job_id:
            return item
    return None


# --------------------------------------------------------------------------
# kurulu uygulamalar
# --------------------------------------------------------------------------

def load_installs():
    data = _read_json(INSTALLS_PATH, [])
    return data if isinstance(data, list) else []


def add_install(record):
    with _lock:
        items = load_installs()
        items = [i for i in items if not (i.get("domain") == record.get("domain")
                                          and i.get("path") == record.get("path"))]
        items.append(record)
        _atomic_write(INSTALLS_PATH, json.dumps(items[-500:], indent=2, ensure_ascii=False))
    return record


def remove_install(domain, path="/"):
    with _lock:
        items = [i for i in load_installs()
                 if not (i.get("domain") == domain and i.get("path") == path)]
        _atomic_write(INSTALLS_PATH, json.dumps(items, indent=2, ensure_ascii=False))
        return items


# --------------------------------------------------------------------------
# denetim gunlugu
# --------------------------------------------------------------------------

def audit(action, detail):
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                       "action": action, "detail": detail}, ensure_ascii=False)
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
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []
    out.reverse()
    return out


# --------------------------------------------------------------------------
# AI saglayici anahtarlari (providers.py bu arayuzu bekler)
# --------------------------------------------------------------------------

def _shared_keys():
    merged = {}
    for path in SHARED_KEYS_PATHS:
        data = _read_json(path, {})
        if isinstance(data, dict):
            for name, entry in data.items():
                if isinstance(entry, dict) and entry.get("key"):
                    merged[name] = dict(entry, _source=path)
    return merged


def load_keys():
    """Firewall AI anahtarlari + bu panele girilenler (bu panelinki onceliklidir)."""
    keys = _shared_keys()
    own = _read_json(KEYS_PATH, {})
    if isinstance(own, dict):
        for name, entry in own.items():
            if isinstance(entry, dict) and entry.get("key"):
                keys[name] = dict(entry, _source="local")
    return keys


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
    """Anahtarlarin kendisini asla dondurmez."""
    out = {}
    for name, entry in load_keys().items():
        raw = entry.get("key") or ""
        out[name] = {
            "configured": bool(raw),
            "hint": ("…" + raw[-4:]) if len(raw) >= 4 else "",
            "model": entry.get("model") or "",
            "source": "bu panel" if entry.get("_source") == "local" else "Firewall AI",
        }
    return out


# --------------------------------------------------------------------------
# katalog duzeltmeleri (AI onerisi -> onay -> burada saklanir)
# Paket dosyalarindaki tarifler yukseltmede ezilir; duzeltmeler config'te kalir.
# --------------------------------------------------------------------------

def load_overrides():
    data = _read_json(OVERRIDES_PATH, {})
    return data if isinstance(data, dict) else {}


def set_override(app_id, download, previous, note=""):
    with _lock:
        data = load_overrides()
        data[app_id] = {"download": download, "previous": previous,
                        "applied": int(time.time()), "note": note}
        _atomic_write(OVERRIDES_PATH, json.dumps(data, indent=2, ensure_ascii=False))


def clear_override(app_id):
    with _lock:
        data = load_overrides()
        removed = data.pop(app_id, None)
        _atomic_write(OVERRIDES_PATH, json.dumps(data, indent=2, ensure_ascii=False))
        return removed


def load_proposals():
    data = _read_json(PROPOSALS_PATH, {})
    return data if isinstance(data, dict) else {}


def save_proposal(app_id, proposal):
    with _lock:
        data = load_proposals()
        if proposal is None:
            data.pop(app_id, None)
        else:
            data[app_id] = proposal
        _atomic_write(PROPOSALS_PATH, json.dumps(data, indent=2, ensure_ascii=False))
