#!/usr/bin/env bash
# AGFO SSH Terminal menu girdisini geri alir: her dosyanin EN YENI yedegini
# yerine koyar ve CyberPanel'i yeniden baslatir.
set -euo pipefail
say() { printf '[agfo-ssh-menu] %s\n' "$*"; }
[ "$(id -u)" = "0" ] || { echo "[agfo-ssh-menu] HATA: root gerekli" >&2; exit 1; }

COUNT="$(AGFO_MENU_ROOT="${AGFO_MENU_ROOT:-/usr/local/CyberCP}" python3 - <<'PYEOF'
import os, re, shutil
root = os.environ["AGFO_MENU_ROOT"]
best = {}
for dirpath, dirnames, files in os.walk(root):
    for name in files:
        m = re.match(r"^(.*)\.agfo-bak-(\d{8}-\d{6})$", name)
        if not m:
            continue
        orig = os.path.join(dirpath, m.group(1))
        ts = m.group(2)
        if orig not in best or ts > best[orig][0]:
            best[orig] = (ts, os.path.join(dirpath, name))
for orig in sorted(best):
    ts, bak = best[orig]
    shutil.copy2(bak, orig)
    print("[agfo-ssh-menu] geri yuklendi (%s): %s" % (ts, orig))
print("COUNT=%d" % len(best))
PYEOF
)"
echo "$COUNT" | grep -v '^COUNT=' || true
N="$(echo "$COUNT" | sed -n 's/^COUNT=//p')"
if [ "${N:-0}" = "0" ]; then
  say "yedek bulunamadi; geri alinacak bir sey yok."
  exit 0
fi
if systemctl list-unit-files 2>/dev/null | grep -q '^lscpd'; then
  say "lscpd yeniden baslatiliyor"
  systemctl restart lscpd || say "UYARI: lscpd yeniden baslatilamadi"
fi
say "$N dosya geri yuklendi."
