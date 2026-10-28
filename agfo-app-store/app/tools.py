# -*- coding: utf-8 -*-
"""Runner ile kurulmus AGFO araclarini bulur ve yonetir.

Kesif: systemd'deki agfo-*.service birimleri + /opt/agfo-* kurulum dizinleri.
Yalnizca adi ^agfo-[a-z0-9-]+$ olan birimlere islem yapilir; komutlar kabuk
kullanmadan (argv) calisir. Bu panelin kendisi durdurulamaz/kaldirilamaz.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

import store

OPT_BASE = os.environ.get("AGFO_STORE_OPT_BASE", "/opt")
SELF_SLUG = "agfo-app-store"
SLUG_RE = re.compile(r"^agfo-[a-z0-9-]{2,60}$")
SYSTEMCTL = os.environ.get("AGFO_STORE_SYSTEMCTL", "systemctl")
JOURNALCTL = os.environ.get("AGFO_STORE_JOURNALCTL", "journalctl")

KNOWN = {
    "agfo-ssh-terminal": {"name": "AGFO SSH Terminal", "desc": "Tarayıcıdan root terminali"},
    "agfo-firewall-ai": {"name": "AGFO Firewall AI", "desc": "CrowdSec + AI öneri paneli"},
    "agfo-app-store": {"name": "AGFO App Store", "desc": "Bu panel"},
}


class ToolError(Exception):
    pass


def _run(argv, timeout=30):
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout, check=False)
    except FileNotFoundError:
        return 127, "komut yok: %s" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "zaman asimi"
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def _units():
    rc, out = _run([SYSTEMCTL, "list-unit-files", "--type=service", "--no-legend",
                    "--no-pager", "agfo-*"])
    names = set()
    if rc == 0:
        for line in out.splitlines():
            unit = line.split()[0] if line.split() else ""
            if unit.endswith(".service"):
                slug = unit[:-len(".service")]
                if SLUG_RE.match(slug) and not slug.endswith("-certwatch"):
                    names.add(slug)
    return names


def _show(slug):
    rc, out = _run([SYSTEMCTL, "show", slug + ".service", "--no-pager",
                    "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState",
                    "-p", "ActiveEnterTimestamp", "-p", "MainPID", "-p", "Description"])
    info = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    return info


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _config(slug):
    try:
        with open(os.path.join(OPT_BASE, slug, "config", "config.json"), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def discover():
    slugs = set(_units())
    if os.path.isdir(OPT_BASE):
        for name in os.listdir(OPT_BASE):
            if SLUG_RE.match(name) and os.path.isdir(os.path.join(OPT_BASE, name)):
                slugs.add(name)
    tools = []
    for slug in sorted(slugs):
        home = os.path.join(OPT_BASE, slug)
        cfg = _config(slug)
        info = _show(slug)
        url = (cfg.get("public_url") or "").strip()
        token = ((cfg.get("auth") or {}).get("login_token") or "").strip()
        meta = KNOWN.get(slug, {})
        tools.append({
            "slug": slug,
            "name": meta.get("name") or slug,
            "desc": meta.get("desc") or (info.get("Description") or ""),
            "version": _read(os.path.join(home, "VERSION")) or "?",
            "installed_dir": home if os.path.isdir(home) else "",
            "service": bool(info.get("UnitFileState")) and info.get("UnitFileState") != "",
            "active": info.get("ActiveState", ""),
            "sub": info.get("SubState", ""),
            "enabled": info.get("UnitFileState", ""),
            "since": info.get("ActiveEnterTimestamp", ""),
            "port": cfg.get("port"),
            "url": url,
            "open_url": (url.rstrip("/") + "/?t=" + token) if (url and token) else url,
            "uninstall": os.path.isfile(os.path.join(home, "uninstall.sh")),
            "self": slug == SELF_SLUG,
        })
    return tools


def _check_slug(slug):
    if not SLUG_RE.match(slug or ""):
        raise ToolError("Gecersiz arac adi")
    if slug not in {t["slug"] for t in discover()}:
        raise ToolError("Arac bulunamadi: %s" % slug)


def action(slug, what):
    _check_slug(slug)
    if what not in ("restart", "stop", "start"):
        raise ToolError("Gecersiz islem")
    if slug == SELF_SLUG and what == "stop":
        raise ToolError("Bu panel kendini durduramaz.")
    if slug == SELF_SLUG and what == "restart":
        # Yanit gonderilebilsin diye yeniden baslatmayi birkac saniye ertele.
        rc, out = _run(["systemd-run", "--on-active=3", "--unit", "agfo-app-store-selfrestart-%d" % int(time.time()),
                        SYSTEMCTL, "restart", SELF_SLUG + ".service"])
        store.audit("tool_action", {"tool": slug, "action": what, "rc": rc})
        if rc != 0:
            raise ToolError("Yeniden baslatma planlanamadi: %s" % out[-200:])
        return {"ok": True, "message": "Panel 3 saniye icinde yeniden baslayacak."}
    rc, out = _run([SYSTEMCTL, what, slug + ".service"], timeout=60)
    store.audit("tool_action", {"tool": slug, "action": what, "rc": rc})
    if rc != 0:
        raise ToolError("%s basarisiz: %s" % (what, out[-300:]))
    return {"ok": True, "message": "%s: %s tamam" % (slug, what)}


def logs(slug, lines=150):
    _check_slug(slug)
    lines = max(20, min(int(lines or 150), 1000))
    rc, out = _run([JOURNALCTL, "-u", slug + ".service", "-n", str(lines),
                    "--no-pager", "-o", "short-iso"], timeout=30)
    return out if out else "(gunluk bos)"


def uninstall(slug, confirm):
    _check_slug(slug)
    if slug == SELF_SLUG:
        raise ToolError("Bu panel kendini kaldiramaz; Runner'dan uninstall.sh calistirin.")
    if (confirm or "").strip() != slug:
        raise ToolError("Onay icin arac adini aynen yazin: %s" % slug)
    script = os.path.join(OPT_BASE, slug, "uninstall.sh")
    if not os.path.isfile(script):
        raise ToolError("Bu aracin kaldirma betigi yok")
    st = os.stat(script)
    if st.st_uid != 0 or (st.st_mode & 0o022):
        raise ToolError("Kaldirma betigi guvenli degil (root'a ait olmali, baskalari yazamamali)")
    bash = shutil.which("bash") or "/bin/bash"
    rc, out = _run([bash, script], timeout=600)
    store.audit("tool_uninstall", {"tool": slug, "rc": rc})
    if rc != 0:
        raise ToolError("Kaldirma basarisiz (%d): %s" % (rc, out[-400:]))
    return {"ok": True, "output": out[-4000:]}
