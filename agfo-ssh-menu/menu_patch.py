#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CyberPanel kenar menusune AGFO SSH Terminal girdisi ekler. (1.2.0)

Yontem: mevcut "AGFO Root Terminal" girdinizi sablonda bulur ve onu cevreleyen
blogu kopyalar. Uc strateji sirayla denenir:
  1) <li> ... </li>
  2) <a> ... </a>
  3) etiketi iceren tek satir
Hicbiri olmazsa dosyaya dokunmaz ve o bolumu ekrana basar.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time

ROOT_DIRS = [d for d in (os.environ.get("AGFO_MENU_ROOT") or "/usr/local/CyberCP").split(",") if d.strip()]
NEEDLE = os.environ.get("AGFO_MENU_ANCHOR", "AGFO Root Terminal")
NEW_LABEL = os.environ.get("AGFO_MENU_LABEL", "AGFO SSH Terminal")
NEW_URL = os.environ.get("AGFO_MENU_URL", "")
DUMP = os.environ.get("AGFO_MENU_DUMP", "0") == "1"
NEW_TITLE = os.environ.get("AGFO_MENU_TITLE", NEW_LABEL)
WINDOW = 40
STAMP = time.strftime("%Y%m%d-%H%M%S")


def say(msg):
    print("[agfo-ssh-menu] %s" % msg)


def dump_context(path, lines, idx, span=25):
    lo = max(0, idx - span)
    hi = min(len(lines), idx + span + 1)
    say("--- %s  (satir %d-%d) ---" % (path, lo + 1, hi))
    for i in range(lo, hi):
        mark = ">>" if i == idx else "  "
        print("%s %5d | %s" % (mark, i + 1, lines[i].rstrip("\n")))
    say("--- bolum sonu ---")


def find_files():
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
                if NEEDLE in text:
                    hits.append(path)
    return hits


def bounds(lines, idx, open_pat, close_pat):
    """Etiket satirini saran open/close etiketlerini bul."""
    start = None
    for i in range(idx, max(-1, idx - WINDOW), -1):
        if re.search(open_pat, lines[i]):
            start = i
            break
    if start is None:
        return None, None
    end = None
    for i in range(idx, min(len(lines), idx + WINDOW)):
        if re.search(close_pat, lines[i]) and i >= idx:
            end = i
            break
    if end is None:
        return None, None
    return start, end


def li_parent_above(lines, start):
    """Blogun hemen ustunde acik bir <li> var mi (klon <li> ile sarilmali mi)."""
    for i in range(start - 1, max(-1, start - 6), -1):
        line = lines[i]
        if "</li>" in line:
            return False
        if "<li" in line:
            return True
    return False


def pick_block(lines, idx):
    """En KUCUK saran blogu secer: (start, end, strateji, li_ile_sar).

    Boylece alt menu barindiran dev bir <li> yanlislikla kopyalanmaz.
    """
    # 1) <li> blogu: siniflari ve yapiyi birebir korur.
    #    Alt menu (<ul>) barindiriyorsa ust menu ogesidir, kopyalanmaz.
    start, end = bounds(lines, idx, r"<li\b", r"</li>")
    if start is not None and (end - start) <= 12:
        block = "".join(lines[start:end + 1])
        if "href" in block and "<ul" not in block:
            return start, end, "<li>", False

    # 2) <a> blogu; ustunde acik bir <li> varsa klon <li> ile sarilir.
    start, end = bounds(lines, idx, r"<a\b", r"</a>")
    if start is not None and (end - start) <= 8 and "href" in "".join(lines[start:end + 1]):
        return start, end, "<a>", li_parent_above(lines, start)

    # 3) son care: etiketi iceren tek satir
    if "href" in lines[idx]:
        return idx, idx, "tek satir", False

    return None, None, None, False


def set_href_and_title(text):
    """Bloktaki adresi ve ipucu metnini bizimkilerle degistirir."""
    out, n = re.subn(r'href\s*=\s*"[^"]*"', 'href="%s"' % NEW_URL, text, count=1)
    if n == 0:
        out, n = re.subn(r"href\s*=\s*'[^']*'", "href='%s'" % NEW_URL, text, count=1)
    if n == 0:
        return None, "blokta href bulunamadi"
    # Kopyalanan girdinin ipucu (title) bizim girdimiz icin yaniltici olur.
    out = re.sub(r'title\s*=\s*"[^"]*"', 'title="%s"' % NEW_TITLE, out, count=1)
    out = re.sub(r"title\s*=\s*'[^']*'", "title='%s'" % NEW_TITLE, out, count=1)
    if "target=" not in out:
        out = re.sub(r"<a\s", '<a target="_blank" rel="noopener" ', out, count=1)
    return out, None


def make_new_block(block_text):
    return set_href_and_title(block_text.replace(NEEDLE, NEW_LABEL))


def main():
    if not NEW_URL:
        say("HATA: AGFO_MENU_URL verilmedi.")
        return 2
    say("surum        : 1.2.0")
    say("aranan kalip : %s" % NEEDLE)
    say("eklenecek    : %s -> %s" % (NEW_LABEL, NEW_URL))

    files = find_files()
    if not files:
        say("CyberPanel sablonlarinda '%s' bulunamadi." % NEEDLE)
        say("Menuyu sablon disinda bir yontemle eklediyseniz girdiyi elle ekleyin.")
        return 0

    changed = 0
    for path in files:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        if any(NEW_LABEL in ln for ln in lines):
            # Girdi zaten var: adres degistiyse (ornek: IP -> alan adi) guncelle.
            i = next(i for i, ln in enumerate(lines) if NEW_LABEL in ln)
            start, end, how, _wrap = pick_block(lines, i)
            if start is None:
                say("zaten ekli (blok cozulemedi, dokunulmadi): %s" % path)
                if DUMP:
                    dump_context(path, lines, i)
                continue
            current = "".join(lines[start:end + 1])
            updated, err = set_href_and_title(current)
            if err or updated == current:
                say("zaten guncel: %s" % path)
                continue
            backup = "%s.agfo-bak-%s" % (path, STAMP)
            shutil.copy2(path, backup)
            lines[start:end + 1] = [updated]
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(lines)
            changed += 1
            say("mevcut girdi guncellendi: %s" % path)
            say("  yedek: %s" % backup)
            say("  yeni adres: %s" % NEW_URL)
            continue
        idx = next((i for i, ln in enumerate(lines) if NEEDLE in ln), None)
        if idx is None:
            continue

        start, end, how, wrap_li = pick_block(lines, idx)
        if start is None:
            say("ATLANDI: '%s' etrafinda kopyalanabilir bir blok bulunamadi." % NEEDLE)
            say("Asagidaki bolumu bana iletin, kesin yamayi ona gore hazirlayayim:")
            dump_context(path, lines, idx)
            continue

        new_text, err = make_new_block("".join(lines[start:end + 1]))
        if err:
            say("ATLANDI (%s): %s" % (err, path))
            dump_context(path, lines, idx)
            continue

        if wrap_li:
            indent = re.match(r"[ \t]*", lines[start]).group(0)
            new_text = "%s<li>\n%s%s</li>\n" % (indent, new_text if new_text.endswith("\n") else new_text + "\n", indent)
            how += " (<li> ile sarildi)"

        backup = "%s.agfo-bak-%s" % (path, STAMP)
        shutil.copy2(path, backup)
        lines[end + 1:end + 1] = [new_text]
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        changed += 1
        say("eklendi (%s kalibi): %s" % (how, path))
        say("  yedek: %s" % backup)
        say("  eklenen blok:")
        for ln in new_text.rstrip("\n").split("\n"):
            print("    | %s" % ln)
        if DUMP:
            dump_context(path, lines, idx)

    if changed == 0:
        say("degisiklik yapilmadi.")
    else:
        say("%d dosya guncellendi." % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
