#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CyberPanel kenar menusunu duzenler. (1.5.0)

Yapabildikleri:
  * Menu girdisi EKLER  - mevcut bir girdinin kalibini kopyalayarak
  * Menu girdisi GUNCELLER - girdi zaten varsa adresini/ipucunu tazeler
  * Menu girdisi SILER  - artik istenmeyen girdileri kaldirir

Dokundugu her dosyanin yedegini birakir; hicbir kalip tutmazsa dosyaya
dokunmaz ve sablonun ilgili bolumunu ekrana basar.

Ortam degiskenleri:
  AGFO_MENU_ENTRIES   "Etiket|https://adres" satirlari (yeni satirla ayrilmis)
  AGFO_MENU_REMOVE    "Etiket1,Etiket2" - silinecek girdiler
  AGFO_MENU_ANCHOR    kalibi kopyalanacak girdi (bos ise otomatik secilir)
  AGFO_MENU_TARGET    self (ayni sekme, varsayilan) | blank (yeni sekme)
  AGFO_MENU_ROOT      sablon dizini (varsayilan /usr/local/CyberCP)
  AGFO_MENU_DUMP      1 = her dosyada ilgili bolumu de bas
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time

VERSION = "1.5.0"
ROOT_DIRS = [d for d in (os.environ.get("AGFO_MENU_ROOT") or "/usr/local/CyberCP").split(",") if d.strip()]
TARGET = (os.environ.get("AGFO_MENU_TARGET") or "self").strip().lower()
DUMP = os.environ.get("AGFO_MENU_DUMP", "0") == "1"
WINDOW = 40
STAMP = time.strftime("%Y%m%d-%H%M%S")

ANCHOR_CANDIDATES = [a.strip() for a in (os.environ.get("AGFO_MENU_ANCHOR") or "").split(",") if a.strip()]
ANCHOR_CANDIDATES += ["AGFO SSH Terminal", "Package Runner", "AGFO Root Terminal", "AGFO SafeGuard"]

REMOVE = [x.strip() for x in (os.environ.get("AGFO_MENU_REMOVE") or "").split(",") if x.strip()]

ENTRIES = []
for line in (os.environ.get("AGFO_MENU_ENTRIES") or "").split("\n"):
    line = line.strip()
    if not line or "|" not in line:
        continue
    label, url = line.split("|", 1)
    label, url = label.strip(), url.strip()
    if label and url:
        ENTRIES.append((label, url))


def say(msg):
    print("[agfo-ssh-menu] %s" % msg)


def dump_context(path, lines, idx, span=20):
    lo, hi = max(0, idx - span), min(len(lines), idx + span + 1)
    say("--- %s (satir %d-%d) ---" % (path, lo + 1, hi))
    for i in range(lo, hi):
        print("%s %5d | %s" % (">>" if i == idx else "  ", i + 1, lines[i].rstrip("\n")))
    say("--- bolum sonu ---")


# ---------------------------------------------------------------------------
# blok cozumleme
# ---------------------------------------------------------------------------

def bounds(lines, idx, open_pat, close_pat):
    start = None
    for i in range(idx, max(-1, idx - WINDOW), -1):
        if re.search(open_pat, lines[i]):
            start = i
            break
    if start is None:
        return None, None
    for i in range(idx, min(len(lines), idx + WINDOW)):
        if re.search(close_pat, lines[i]) and i >= idx:
            return start, i
    return None, None


def li_parent_above(lines, start):
    for i in range(start - 1, max(-1, start - 6), -1):
        if "</li>" in lines[i]:
            return False
        if "<li" in lines[i]:
            return True
    return False


def pick_block(lines, idx):
    """En kucuk saran blok: (start, end, strateji, li_ile_sar)."""
    start, end = bounds(lines, idx, r"<li\b", r"</li>")
    if start is not None and (end - start) <= 12:
        block = "".join(lines[start:end + 1])
        if "href" in block and "<ul" not in block:
            return start, end, "<li>", False
    start, end = bounds(lines, idx, r"<a\b", r"</a>")
    if start is not None and (end - start) <= 8 and "href" in "".join(lines[start:end + 1]):
        return start, end, "<a>", li_parent_above(lines, start)
    if "href" in lines[idx]:
        return idx, idx, "tek satir", False
    return None, None, None, False


def find_label(lines, label):
    for i, line in enumerate(lines):
        if label in line:
            return i
    return None


# Etikete gore ikon: kopyalanan girdinin ikonu yanlis kalmasin.
ICON_RULES = [
    ("firewall", "fa-shield-alt"),
    ("güvenlik", "fa-shield-alt"),
    ("terminal", "fa-terminal"),
    ("runner", "fa-box"),
    ("app store", "fa-store"),
    ("file manager", "fa-folder-open"),
    ("dosya", "fa-folder-open"),
    ("uygulama", "fa-store"),
]


def apply_icon(text, label):
    low = label.lower()
    for needle, icon in ICON_RULES:
        if needle in low:
            return re.sub(r'(class="[^"]*?)fa-[a-z0-9-]+', r"\1" + icon, text, count=1)
    return text


def apply_attrs(text, url, title):
    out, n = re.subn(r'href\s*=\s*"[^"]*"', 'href="%s"' % url, text, count=1)
    if n == 0:
        out, n = re.subn(r"href\s*=\s*'[^']*'", "href='%s'" % url, text, count=1)
    if n == 0:
        return None
    out = re.sub(r'title\s*=\s*"[^"]*"', 'title="%s"' % title, out, count=1)
    out = re.sub(r"title\s*=\s*'[^']*'", "title='%s'" % title, out, count=1)
    # hedef sekme
    out = re.sub(r'\s+target\s*=\s*"[^"]*"', "", out)
    out = re.sub(r"\s+target\s*=\s*'[^']*'", "", out)
    out = re.sub(r'\s+rel\s*=\s*"[^"]*"', "", out)
    if TARGET == "blank":
        out = re.sub(r"<a\s", '<a target="_blank" rel="noopener" ', out, count=1)
    return out


# ---------------------------------------------------------------------------
# dosya islemleri
# ---------------------------------------------------------------------------

def candidate_files():
    needles = [label for label, _ in ENTRIES] + REMOVE + ANCHOR_CANDIDATES
    hits = []
    for root in ROOT_DIRS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
            for name in filenames:
                if not name.endswith((".html", ".htm")):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except Exception:
                    continue
                if any(n in text for n in needles):
                    hits.append(path)
    return hits


class FileEditor(object):
    def __init__(self, path):
        self.path = path
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            self.lines = fh.readlines()
        self.changed = False
        self.backed_up = False

    def backup(self):
        if self.backed_up:
            return
        target = "%s.agfo-bak-%s" % (self.path, STAMP)
        shutil.copy2(self.path, target)
        say("  yedek: %s" % target)
        self.backed_up = True

    def save(self):
        if not self.changed:
            return
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.writelines(self.lines)

    # --- silme ---
    def remove(self, label):
        removed = 0
        while True:
            idx = find_label(self.lines, label)
            if idx is None:
                break
            start, end, how, _ = pick_block(self.lines, idx)
            if start is None:
                say("  ATLANDI (blok cozulemedi): %s" % label)
                if DUMP:
                    dump_context(self.path, self.lines, idx)
                break
            self.backup()
            del self.lines[start:end + 1]
            self.changed = True
            removed += 1
            if removed > 5:
                break
        if removed:
            say("  silindi: %s (%d girdi)" % (label, removed))
        return removed

    # --- ekleme / guncelleme ---
    def upsert(self, label, url, anchor_label):
        idx = find_label(self.lines, label)
        if idx is not None:
            start, end, how, _ = pick_block(self.lines, idx)
            if start is None:
                say("  ATLANDI (mevcut girdi cozulemedi): %s" % label)
                return False
            current = "".join(self.lines[start:end + 1])
            updated = apply_attrs(current, url, label)
            if updated is None or updated == current:
                say("  zaten guncel: %s" % label)
                return False
            self.backup()
            self.lines[start:end + 1] = [updated]
            self.changed = True
            say("  guncellendi: %s -> %s" % (label, url))
            return True

        aidx = find_label(self.lines, anchor_label)
        if aidx is None:
            return False
        start, end, how, wrap = pick_block(self.lines, aidx)
        if start is None:
            say("  ATLANDI (kalip cozulemedi): %s" % anchor_label)
            if DUMP:
                dump_context(self.path, self.lines, aidx)
            return False
        clone = "".join(self.lines[start:end + 1]).replace(anchor_label, label)
        clone = apply_icon(clone, label)
        clone = apply_attrs(clone, url, label)
        if clone is None:
            say("  ATLANDI (href bulunamadi): %s" % label)
            return False
        if wrap:
            indent = re.match(r"[ \t]*", self.lines[start]).group(0)
            clone = "%s<li>\n%s%s</li>\n" % (indent, clone if clone.endswith("\n") else clone + "\n", indent)
        self.backup()
        self.lines[end + 1:end + 1] = [clone]
        self.changed = True
        say("  eklendi (%s kalibi): %s -> %s" % (how, label, url))
        for line in clone.rstrip("\n").split("\n"):
            print("      | %s" % line)
        return True


def main():
    say("surum %s" % VERSION)
    if not ENTRIES and not REMOVE:
        say("yapilacak is yok (AGFO_MENU_ENTRIES / AGFO_MENU_REMOVE bos).")
        return 0
    for label, url in ENTRIES:
        say("eklenecek/guncellenecek: %s -> %s" % (label, url))
    for label in REMOVE:
        say("silinecek: %s" % label)
    say("hedef sekme: %s" % ("yeni sekme" if TARGET == "blank" else "ayni sekme"))

    files = candidate_files()
    if not files:
        say("CyberPanel sablonlarinda eslesen girdi bulunamadi.")
        return 0

    total = 0
    for path in files:
        editor = FileEditor(path)
        say("dosya: %s" % path)
        anchor = None
        for cand in ANCHOR_CANDIDATES:
            if cand in REMOVE:
                continue
            if find_label(editor.lines, cand) is not None:
                anchor = cand
                break
        if ENTRIES and not anchor:
            say("  kopyalanacak kalip yok; yalnizca silme yapilacak")
        for label, url in ENTRIES:
            if anchor:
                editor.upsert(label, url, anchor)
        for label in REMOVE:
            editor.remove(label)
        editor.save()
        if editor.changed:
            total += 1
        else:
            say("  degisiklik yok")
    say("%d dosya guncellendi." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
