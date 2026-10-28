# -*- coding: utf-8 -*-
"""Uygulama katalogu: her uygulama catalog/<id>.json dosyasindaki bir tarif.

Tarif bicimi (ozet):
{
  "id": "wordpress", "name": "WordPress", "category": "cms",
  "tagline": "...", "description": "...", "homepage": "...", "license": "GPL-2.0",
  "badge": "WP",                      # arayuzde gosterilen kisa rozet
  "install_mode": "cli" | "web",      # cli = tamamen otomatik, web = kurulum sihirbazi acilir
  "database": true,
  "requires": {"php": "7.4", "extensions": ["mysqli"]},
  "download": {"url": "...", "format": "tar.gz|zip", "strip": 1},
  "fields": [{"id": "admin_user", "label": "...", "type": "text|password|email", "default": "..."}],
  "steps": [ {...} ],
  "finish": {"path": "/wp-admin/", "note": "..."}
}
"""
from __future__ import annotations

import json
import os
import re

import store

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
REQUIRED = ("id", "name", "category", "download")
CATEGORIES = {
    "cms": "İçerik yönetimi",
    "shop": "E-ticaret",
    "learning": "Eğitim",
    "crm": "CRM ve iş",
    "analytics": "Analitik",
    "collab": "İşbirliği",
    "forum": "Forum",
    "framework": "Çatı (framework)",
    "tools": "Araçlar",
}

_cache = {"items": None, "mtime": 0}


def _validate(data, path):
    for key in REQUIRED:
        if key not in data:
            raise ValueError("%s: '%s' alani eksik" % (os.path.basename(path), key))
    if not ID_RE.match(str(data["id"])):
        raise ValueError("%s: gecersiz id" % os.path.basename(path))
    if data.get("install_mode", "web") not in ("cli", "web"):
        raise ValueError("%s: install_mode cli veya web olmali" % data["id"])
    download = data.get("download") or {}
    if download.get("github"):
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", str(download["github"])):
            raise ValueError("%s: gecersiz github deposu" % data["id"])
    elif not str(download.get("url", "")).startswith("https://"):
        raise ValueError("%s: indirme adresi https olmali" % data["id"])
    if download.get("format") not in ("tar.gz", "tgz", "zip", "tar.bz2"):
        raise ValueError("%s: desteklenmeyen arsiv bicimi" % data["id"])
    return data


def load(force=False):
    """Katalogu diskten okur; dosyalar degismediyse onbellekten doner."""
    directory = store.CATALOG_DIR
    if not os.path.isdir(directory):
        return []
    newest = 0
    for name in os.listdir(directory):
        if name.endswith(".json"):
            try:
                newest = max(newest, os.path.getmtime(os.path.join(directory, name)))
            except OSError:
                pass
    try:
        newest = max(newest, os.path.getmtime(store.OVERRIDES_PATH))
    except OSError:
        pass
    if not force and _cache["items"] is not None and newest <= _cache["mtime"]:
        return _cache["items"]
    overrides = store.load_overrides()

    items, errors = [], []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data = _validate(data, path)
            fix = overrides.get(data["id"])
            if isinstance(fix, dict) and isinstance(fix.get("download"), dict):
                patched = dict(data, download=fix["download"])
                try:
                    data = _validate(patched, path)
                    data["download_override"] = True
                except ValueError as exc:
                    errors.append("duzeltme gecersiz (%s): %s" % (data["id"], exc))
            items.append(data)
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        store.audit("catalog_error", {"errors": errors[:10]})
    items.sort(key=lambda d: (d.get("category", ""), d.get("name", "").lower()))
    _cache["items"] = items
    _cache["mtime"] = newest
    return items


def get(app_id):
    for item in load():
        if item.get("id") == app_id:
            return item
    return None


def public_list():
    """Arayuze gonderilecek sade liste (adimlar haric)."""
    out = []
    for item in load():
        out.append({
            "id": item["id"],
            "name": item["name"],
            "badge": item.get("badge") or item["name"][:2].upper(),
            "category": item.get("category"),
            "category_label": CATEGORIES.get(item.get("category"), item.get("category")),
            "tagline": item.get("tagline", ""),
            "description": item.get("description", ""),
            "homepage": item.get("homepage", ""),
            "license": item.get("license", ""),
            "install_mode": item.get("install_mode", "web"),
            "database": bool(item.get("database", True)),
            "requires": item.get("requires", {}),
            "fields": item.get("fields", []),
            "tags": item.get("tags", []),
            "version_note": item.get("version_note", ""),
            "download_override": bool(item.get("download_override")),
        })
    return out


def categories():
    used = {}
    for item in load():
        key = item.get("category", "tools")
        used[key] = used.get(key, 0) + 1
    return [{"id": k, "label": CATEGORIES.get(k, k), "count": v}
            for k, v in sorted(used.items(), key=lambda kv: CATEGORIES.get(kv[0], kv[0]))]
