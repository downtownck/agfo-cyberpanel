# -*- coding: utf-8 -*-
"""CyberPanel kenar menusu editoru (AGFO TOOLS grubu).

CyberPanel sablonlarinda AGFO girdilerinin bulundugu grubu (art arda gelen
menu girdileri) bulur, listeler ve tek seferde yeniden yazar: ad, adres, ikon,
yeni sekme, sira, ekleme, silme. Her yazimdan once yedek alir (agfo-ssh-menu
paketinin restore.sh'i ile ayni bicim), yazdiktan sonra dosyayi yeniden
okuyup dogrular; tutmazsa yedegi geri koyar.

Grubun disindaki hicbir satira dokunulmaz. Degistirilmeyen girdilerin
metni bayt bayt korunur (Django etiketli adresler dahil).
"""
import glob
import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit

ROOT_DIRS = [d for d in (os.environ.get("AGFO_STORE_MENU_ROOT") or "/usr/local/CyberCP").split(",") if d.strip()]
PANEL_CERTS = [p for p in (os.environ.get("AGFO_STORE_PANEL_CERT"),
                           "/usr/local/lscp/conf/cert.pem", "/usr/local/lscp/conf/server.crt") if p]
OPT_GLOB = os.environ.get("AGFO_STORE_OPT_GLOB", "/opt/agfo-*")
SYSTEMCTL = os.environ.get("AGFO_STORE_SYSTEMCTL", "systemctl")
RESTART = os.environ.get("AGFO_STORE_MENU_RESTART", "1") == "1"
WINDOW = 40
MAX_ENTRIES = 40

# Bilinen AGFO panelleri: menu etiketi, ikon, ek sorgu.
PANELS = {
    "agfo-ssh-terminal": ("AGFO SSH Terminal", "fa-terminal", "open=root"),
    "agfo-file-manager": ("AGFO File Manager", "fa-folder-open", ""),
    "agfo-app-store": ("AGFO App Store", "fa-store", ""),
    "agfo-firewall-ai": ("AGFO Firewall AI", "fa-shield-alt", ""),
}
SEED_LABELS = [v[0] for v in PANELS.values()] + ["Package Runner", "AGFO Root Terminal", "AGFO SafeGuard"]

ICONS = ["fa-terminal", "fa-folder-open", "fa-store", "fa-shield-alt", "fa-box", "fa-cog", "fa-cogs",
         "fa-database", "fa-server", "fa-globe", "fa-link", "fa-external-link-alt", "fa-chart-line",
         "fa-tools", "fa-wrench", "fa-lock", "fa-key", "fa-envelope", "fa-cloud", "fa-code",
         "fa-file-alt", "fa-users", "fa-user-shield", "fa-robot", "fa-bolt", "fa-hdd", "fa-sync",
         "fa-bell", "fa-book", "fa-star", "fa-home", "fa-desktop", "fa-network-wired", "fa-fire"]

ICON_RE = re.compile(r"^fa-[a-z0-9-]{1,40}$")
LABEL_BAD = re.compile(r"[<>\"'&{}%\\\n\r\t]")
HREF_RE = re.compile(r"^(https?://[^\s\"'<>{}\\]+|/[^\s\"'<>{}\\]*)$")
ICON_IN_TEXT = re.compile(r"\bfa-(?!fw\b|lg\b|xs\b|sm\b|[1-9]x\b|spin\b|pulse\b|solid\b|regular\b|brands\b)[a-z0-9-]+")


class MenuError(Exception):
    pass


# ---------------------------------------------------------------------------
# blok cozumleme (agfo-ssh-menu/menu_patch.py ile ayni kurallar)
# ---------------------------------------------------------------------------

def _bounds(lines, idx, open_pat, close_pat):
    start = None
    for i in range(idx, max(-1, idx - WINDOW), -1):
        if re.search(open_pat, lines[i]):
            start = i
            break
    if start is None:
        return None, None
    for i in range(idx, min(len(lines), idx + WINDOW)):
        if re.search(close_pat, lines[i]):
            return start, i
    return None, None


def _pick_block(lines, idx):
    start, end = _bounds(lines, idx, r"<li\b", r"</li>")
    if start is not None and (end - start) <= 12:
        block = "".join(lines[start:end + 1])
        if "href" in block and "<ul" not in block:
            return start, end
    start, end = _bounds(lines, idx, r"<a\b", r"</a>")
    if start is not None and (end - start) <= 8 and "href" in "".join(lines[start:end + 1]):
        return start, end
    if "href" in lines[idx]:
        return idx, idx
    return None, None


def _block_at(lines, i):
    """i. satirda baslayan bir menu girdisi varsa (start, end)."""
    if i < 0 or i >= len(lines) or not re.match(r"\s*<(li|a)\b", lines[i]):
        return None
    for j in range(i, min(len(lines), i + 12)):
        if "href" in lines[j]:
            s, e = _pick_block(lines, j)
            if s == i:
                return s, e
            return None
    return None


def _block_ending(lines, i):
    """i. satirda biten bir menu girdisi varsa (start, end)."""
    if i < 0 or not re.search(r"</(li|a)>\s*$", lines[i]):
        return None
    for j in range(i, max(-1, i - 12), -1):
        if "href" in lines[j]:
            s, e = _pick_block(lines, j)
            if e == i:
                return s, e
            return None
    return None


def _describe(text):
    title = re.search(r'title\s*=\s*"([^"]*)"', text) or re.search(r"title\s*=\s*'([^']*)'", text)
    inner = re.sub(r"<[^>]+>", " ", text)
    inner = re.sub(r"\s+", " ", inner).strip()
    label = inner or (title.group(1).strip() if title else "")
    href = re.search(r'href\s*=\s*"([^"]*)"', text) or re.search(r"href\s*=\s*'([^']*)'", text)
    icon = ICON_IN_TEXT.search(text)
    return {
        "label": label,
        "href": href.group(1) if href else "",
        "icon": icon.group(0) if icon else "",
        "newtab": bool(re.search(r'target\s*=\s*["\']_blank["\']', text)),
    }


def _labels_known():
    return list(dict.fromkeys(SEED_LABELS + _state().get("labels", [])))


def parse_group(lines, labels=None):
    """AGFO grubunu bul: (start, end, [girdi...]) ya da None."""
    labels = labels or _labels_known()
    seed = None
    for i, line in enumerate(lines):
        if any(lb in line for lb in labels) and "href" in "".join(lines[max(0, i - 3):i + 4]):
            s, e = _pick_block(lines, i)
            if s is not None:
                seed = (s, e)
                break
    if not seed:
        return None
    blocks = [seed]
    # geriye
    i = seed[0] - 1
    while True:
        j = i
        while j >= 0 and not lines[j].strip():
            j -= 1
        b = _block_ending(lines, j)
        if not b or b[1] >= blocks[0][0]:
            break
        blocks.insert(0, b)
        i = b[0] - 1
    # ileriye
    i = blocks[-1][1] + 1
    while True:
        j = i
        while j < len(lines) and not lines[j].strip():
            j += 1
        b = _block_at(lines, j)
        if not b or b[0] <= blocks[-1][1]:
            break
        blocks.append(b)
        i = b[1] + 1
    entries = []
    for s, e in blocks:
        text = "".join(lines[s:e + 1])
        d = _describe(text)
        d["text"] = text
        entries.append(d)
    return blocks[0][0], blocks[-1][1], entries


# ---------------------------------------------------------------------------
# dosyalar, durum
# ---------------------------------------------------------------------------

def _state_path():
    from store import CONFIG_DIR  # noqa: WPS433 (dongusel ice aktarmayi onler)
    return os.path.join(CONFIG_DIR, "menu-state.json")


def _state():
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_state(st):
    path = _state_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _files():
    labels = _labels_known()
    hits = []
    for root in ROOT_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__", "static")]
            for name in filenames:
                if not name.endswith((".html", ".htm")):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                if any(lb in text for lb in labels):
                    hits.append(path)
    return sorted(hits)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.readlines()


def _public(entry):
    return {k: entry[k] for k in ("label", "href", "icon", "newtab")}


# ---------------------------------------------------------------------------
# panel adresleri (oneri)
# ---------------------------------------------------------------------------

def _cert_names(path):
    if not path or not os.path.isfile(path):
        return []
    try:
        out = subprocess.run(["openssl", "x509", "-in", path, "-noout", "-ext", "subjectAltName"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10).stdout.decode()
    except Exception:
        return []
    return [p.strip()[4:].lower() for p in out.replace("\n", ",").split(",") if p.strip().startswith("DNS:")]


def _covers(names, host):
    host = host.lower()
    return any(n == host or (n.startswith("*.") and host.count(".") == n.count(".") and host.endswith(n[1:]))
               for n in names)


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _panel_domain():
    for p in PANEL_CERTS:
        for n in _cert_names(p):
            if not n.startswith("*."):
                return n
    return ""


def suggestions():
    """Kurulu AGFO panelleri icin onerilen menu girdileri."""
    dom = _panel_domain()
    out = []
    for d in sorted(glob.glob(OPT_GLOB)):
        slug = os.path.basename(d)
        if slug not in PANELS or not os.path.isfile(os.path.join(d, "app", "server.py")):
            continue
        cfg_path = os.path.join(d, "config", "config.json")
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception:
            continue
        label, icon, extra = PANELS[slug]
        tls = cfg.get("tls") or {}
        scheme = "https" if tls.get("enabled", True) else "http"
        port = cfg.get("port")
        pub = (cfg.get("public_url") or "").strip()
        host = urlsplit(pub).hostname if pub else ""
        note = ""
        if (not host or _is_ip(host)) and dom and scheme == "https":
            if _covers(_cert_names(tls.get("cert")), dom):
                pub = "%s://%s:%s/" % (scheme, dom, port)
            else:
                note = ("Panel IP adresiyle yayınlanıyor ve sertifikası %s adını kapsamıyor. %s paketini "
                        "yeniden çalıştırın; alan adını ve sertifikayı kendisi bulur." % (dom, slug))
        if not pub:
            continue
        url = pub.rstrip("/") + "/"
        qs = []
        tok = (cfg.get("auth") or {}).get("login_token")
        if tok and (cfg.get("auth") or {}).get("token_login", True):
            qs.append("t=" + tok)
        if extra:
            qs.append(extra)
        if qs:
            url += "?" + "&".join(qs)
        out.append({"slug": slug, "label": label, "href": url, "icon": icon, "newtab": True, "note": note})
    return out


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def read():
    files = _files()
    found = []
    for path in files:
        g = parse_group(_read(path))
        if g:
            found.append((path, g))
    primary = max(found, key=lambda x: len(x[1][2])) if found else None
    return {
        "files": [p for p, _ in found],
        "entries": [_public(e) for e in primary[1][2]] if primary else [],
        "suggestions": suggestions(),
        "icons": ICONS,
        "backups": _backups(),
        "searched": ROOT_DIRS,
    }


def _validate(items, current):
    if not isinstance(items, list) or not items:
        raise MenuError("Menü boş olamaz (en az bir girdi kalmalı).")
    if len(items) > MAX_ENTRIES:
        raise MenuError("En fazla %d girdi olabilir." % MAX_ENTRIES)
    by_label = {e["label"]: e for e in current}
    seen, clean = set(), []
    for it in items:
        if not isinstance(it, dict):
            raise MenuError("Geçersiz girdi.")
        orig = str(it.get("orig") or "")
        if orig and orig not in by_label:
            raise MenuError("Menüde bulunamadı: %s (sayfayı yenileyin)." % orig)
        old = by_label.get(orig)
        label = str(it.get("label") or "").strip()
        href = str(it.get("href") or "").strip()
        icon = str(it.get("icon") or "").strip()
        if not label or len(label) > 60:
            raise MenuError("Ad 1-60 karakter olmalı.")
        if not (old and label == old["label"]) and LABEL_BAD.search(label):
            raise MenuError("Adda izin verilmeyen karakter var: %s" % label)
        if label in seen:
            raise MenuError("Aynı ad iki kez kullanılmış: %s" % label)
        seen.add(label)
        if not (old and href == old["href"]) and not HREF_RE.match(href):
            raise MenuError("%s: adres https://… ya da /yol biçiminde olmalı." % label)
        if icon and not (old and icon == old["icon"]) and not ICON_RE.match(icon):
            raise MenuError("Geçersiz ikon: %s" % icon)
        clean.append({"orig": orig, "label": label, "href": href, "icon": icon,
                      "newtab": bool(it.get("newtab"))})
    return clean


def _set_target(text, newtab):
    out = re.sub(r'\s+target\s*=\s*"[^"]*"', "", text)
    out = re.sub(r"\s+target\s*=\s*'[^']*'", "", out)
    out = re.sub(r'\s+rel\s*=\s*"[^"]*"', "", out)
    if newtab:
        out = re.sub(r"<a\s", '<a target="_blank" rel="noopener" ', out, count=1)
    return out


def _render(base, item):
    """Bir girdinin yeni metni; yalniz degisen ozellikler yazilir."""
    text = base["text"]
    if item["label"] != base["label"] and base["label"]:
        text = text.replace(base["label"], item["label"])
        text = re.sub(r'title\s*=\s*"[^"]*"', 'title="%s"' % item["label"], text, count=1)
    if item["href"] != base["href"]:
        new, n = re.subn(r'href\s*=\s*"[^"]*"', lambda _m: 'href="%s"' % item["href"], text, count=1)
        if n == 0:
            new, n = re.subn(r"href\s*=\s*'[^']*'", lambda _m: "href='%s'" % item["href"], text, count=1)
        if n == 0:
            raise MenuError("Adres yazılamadı: %s" % item["label"])
        text = new
    if item["icon"] and item["icon"] != base["icon"]:
        if base["icon"]:
            text = re.sub(r"\b%s\b" % re.escape(base["icon"]), item["icon"], text, count=1)
    if item["newtab"] != base["newtab"]:
        text = _set_target(text, item["newtab"])
    if not text.endswith("\n"):
        text += "\n"
    return text


def save(items):
    files = _files()
    plans = []
    for path in files:
        lines = _read(path)
        g = parse_group(lines)
        if g:
            plans.append((path, lines, g))
    if not plans:
        raise MenuError("CyberPanel şablonlarında AGFO menü grubu bulunamadı.")
    primary = max(plans, key=lambda x: len(x[2][2]))
    clean = _validate(items, primary[2][2])

    stamp = _new_stamp([p for p, _, _ in plans])
    written = []
    try:
        for path, lines, (start, end, entries) in plans:
            by_label = {e["label"]: e for e in entries}
            template = entries[0]
            out = []
            for it in clean:
                base = by_label.get(it["orig"])
                if base is None:
                    # yeni girdi ya da bu dosyada olmayan girdi: ilk girdinin kalibindan
                    base = dict(template)
                    seed = dict(it, orig=template["label"])
                    seed["newtab"] = it["newtab"]
                    text = _render(base, seed)
                    if not seed["icon"] and template["icon"]:
                        text = re.sub(r"\b%s\b" % re.escape(template["icon"]), "fa-link", text, count=1)
                    out.append(text)
                else:
                    out.append(_render(base, it))
            new_lines = lines[:start] + out + lines[end + 1:]
            if new_lines == lines:
                continue
            bak = "%s.agfo-bak-%s" % (path, stamp)
            shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
            written.append((path, bak))
            # dogrula
            labels = [it["label"] for it in clean]
            g2 = parse_group(_read(path), labels=labels + _labels_known())
            got = [(e["label"], e["href"], e["newtab"]) for e in g2[2]] if g2 else []
            want = [(it["label"], it["href"], it["newtab"]) for it in clean]
            if got != want:
                raise MenuError("Yazılan menü doğrulanamadı (%s); değişiklik geri alındı." % os.path.basename(path))
    except Exception:
        for path, bak in written:
            shutil.copy2(bak, path)
        raise

    st = _state()
    st["labels"] = sorted(set(st.get("labels", [])) | {it["label"] for it in clean})[:100]
    _save_state(st)
    restarted = _restart_panel() if written else False
    return {"changed": [p for p, _ in written], "restarted": restarted, "stamp": stamp}


def _new_stamp(paths):
    """Hicbir dosyada henuz kullanilmamis yedek damgasi (ayni saniyede iki
    kayit birbirinin yedegini ezmesin)."""
    t = time.time()
    while True:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(t))
        if not any(os.path.exists("%s.agfo-bak-%s" % (p, stamp)) for p in paths):
            return stamp
        t += 1


def _backups():
    stamps = {}
    for path in _files():
        for bak in glob.glob(glob.escape(path) + ".agfo-bak-*"):
            m = re.search(r"\.agfo-bak-(\d{8}-\d{6})$", bak)
            if m:
                stamps.setdefault(m.group(1), []).append(path)
    return [{"stamp": s, "files": len(stamps[s])} for s in sorted(stamps, reverse=True)[:10]]


def restore(stamp):
    if not re.match(r"^\d{8}-\d{6}$", stamp or ""):
        raise MenuError("Geçersiz yedek.")
    done = []
    files = _files()
    now = _new_stamp(files)
    for path in files:
        bak = "%s.agfo-bak-%s" % (path, stamp)
        if os.path.isfile(bak):
            shutil.copy2(path, "%s.agfo-bak-%s" % (path, now))
            shutil.copy2(bak, path)
            done.append(path)
    if not done:
        raise MenuError("Bu yedeğe ait dosya bulunamadı.")
    return {"restored": done, "restarted": _restart_panel()}


def _restart_panel():
    """CyberPanel sablonlari onbellekte; lscpd'yi birkac saniye sonra yeniden baslat."""
    if not RESTART:
        return False
    for argv in ([SYSTEMCTL.replace("systemctl", "systemd-run"), "--on-active=2", "--unit",
                  "agfo-menu-restart-%d" % int(time.time()), SYSTEMCTL, "restart", "lscpd"],
                 [SYSTEMCTL, "--no-block", "restart", "lscpd"]):
        try:
            if subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=20).returncode == 0:
                return True
        except Exception:
            continue
    return False
