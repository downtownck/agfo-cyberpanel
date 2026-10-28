# -*- coding: utf-8 -*-
"""Katalog saglik testi -- bu sunucuda, gercek paketlerle.

Iki katman:
  paket  : indir, arsivi ac, yapiyi denetle (kurulum dosyasi, vendor/, PHP surumu)
  deneme : test sitesine gercekten kur, sayfayi sunucu icinden cagir, iz birakmadan kaldir

Sonuclar config/catalog-health.json'a yazilir ve magazada etiket olarak gorunur.
"""
from __future__ import annotations

import glob
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

import catalog
import installer
import store

HEALTH_PATH = os.path.join(store.CONFIG_DIR, "catalog-health.json")
ERROR_MARKERS = re.compile(r"(Fatal error|Parse error|Uncaught [A-Z]\w+|Whoops, looks like|"
                           r"500 Internal Server Error|503 Service Unavailable|Composer detected issues)", re.I)
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# kayit
# ---------------------------------------------------------------------------

def load():
    try:
        with open(HEALTH_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_entry(app_id, layer, result):
    with _lock:
        data = load()
        entry = data.get(app_id) or {}
        entry[layer] = result
        data[app_id] = entry
        store._atomic_write(HEALTH_PATH, json.dumps(data, indent=2, ensure_ascii=False))


def badge(app_id, data=None):
    """Magaza karti icin tek etiket: verified | package_ok | warn | fail | untested."""
    entry = (data if data is not None else load()).get(app_id) or {}
    trial, package = entry.get("trial") or {}, entry.get("package") or {}
    if trial.get("status") == "ok":
        return "verified"
    if trial.get("status") == "fail" or package.get("status") == "fail":
        return "fail"
    if package.get("status") == "warn":
        return "warn"
    if package.get("status") == "ok":
        return "package_ok"
    return "untested"


# ---------------------------------------------------------------------------
# PHP yardimcilari
# ---------------------------------------------------------------------------

def installed_php():
    template = os.environ.get("AGFO_STORE_PHP_TEMPLATE", "/usr/local/lsws/lsphp{v}/bin/php")
    found = []
    for v in ("74", "80", "81", "82", "83", "84", "85"):
        if os.path.isfile(template.replace("{v}", v)):
            found.append(v[0] + "." + v[1:])
    return found


def composer_php_min(constraint):
    """'>=8.2', '^8.1', '~8.2.0', '8.1.* || ^8.2' -> en kucuk alt sinir ('8.1')."""
    nums = re.findall(r"(\d+)\.(\d+)", constraint or "")
    if not nums:
        return None
    return min(("%s.%s" % n for n in nums), key=lambda v: tuple(int(x) for x in v.split(".")))


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split(".")[:2])
    except ValueError:
        return (0, 0)


# ---------------------------------------------------------------------------
# 1) paket testi
# ---------------------------------------------------------------------------

def package_check(app, log=lambda m: None):
    started = time.time()
    result = {"status": "fail", "checks": [], "version": "", "url": "", "size_mb": 0,
              "files": 0, "php_detected": "", "tested": int(started)}
    checks = result["checks"]

    def add(ok, text, level=None):
        checks.append({"level": level or ("ok" if ok else "fail"), "text": text})

    work = tempfile.mkdtemp(prefix="agfo-health-", dir=store.WORK_DIR)
    try:
        spec = installer.resolve_download(app["download"], log)
        result["url"], result["version"] = spec["url"], spec.get("version", "")
        archive = os.path.join(work, "paket")
        installer.download(spec["url"], archive, log)
        result["size_mb"] = round(os.path.getsize(archive) / 1048576.0, 1)
        fmt = spec.get("format", "tar.gz")
        installer.check_archive(archive, fmt)
        add(True, "indirildi ve gecerli %s (%.1f MB)" % (fmt, result["size_mb"]))
        root = os.path.join(work, "kok")
        os.makedirs(root)
        installer.extract(archive, fmt, root, int(spec.get("strip", 0)), log,
                          spec.get("only", ""), spec.get("target", ""))
        count = sum(len(f) for _, _, f in os.walk(root))
        result["files"] = count
        if count == 0:
            add(False, "arsiv bos acildi (strip/only ayari yanlis olabilir)")
            return result
        add(True, "%d dosya acildi" % count)

        entries = sorted(os.listdir(root))
        folder = (app.get("web_root") or "").strip("/")
        public = bool(folder)
        if public:
            ok = os.path.isdir(os.path.join(root, folder)) and any(
                f.endswith(".php") for f in os.listdir(os.path.join(root, folder)))
            add(ok, "%s/ altinda PHP giris dosyasi var" % folder if ok else
                "%s/ klasoru ya da icinde PHP dosyasi YOK (web_root ya da strip hatali)" % folder)
        else:
            php_root = [e for e in entries if e.endswith(".php")]
            if php_root:
                add(True, "kokte PHP giris dosyasi var (%s)" % ", ".join(php_root[:3]))
            elif len(entries) == 1 and os.path.isdir(os.path.join(root, entries[0])):
                add(False, "kokte tek klasor var (%s): strip 1 olmali" % entries[0])
            else:
                add(False, "kokte PHP dosyasi yok; ilk ogeler: %s" % ", ".join(entries[:6]))

        finish = ((app.get("finish") or {}).get("path") or "/").split("?")[0]
        if finish not in ("", "/") and app.get("install_mode") != "cli":
            base = os.path.join(root, folder) if public else root
            rel = finish.strip("/")
            target = os.path.join(base, rel)
            exists = os.path.exists(target) or os.path.exists(target + ".php")
            if not exists and "/" in rel:       # app.php/install gibi on-denetleyici yollari
                exists = os.path.exists(os.path.join(base, rel.split("/")[0]))
            add(exists, "kurulum girisi %s %s" % (finish, "var" if exists else "YOK"),
                None if exists else "warn")

        cj = os.path.join(root, "composer.json")
        if os.path.isfile(cj):
            try:
                with open(cj, "r", encoding="utf-8") as fh:
                    comp = json.load(fh)
            except Exception:
                comp = {}
            req = comp.get("require") or {}
            deps = [k for k in req if k != "php" and not k.startswith("ext-") and not k.startswith("lib-")]
            if deps:
                vend = os.path.isfile(os.path.join(root, "vendor", "autoload.php"))
                add(vend, "Composer bagimliliklari paketle geliyor (vendor/)" if vend else
                    "vendor/ YOK: bu paket 'composer install' ister, derlenmeden calismaz")
            pmin = composer_php_min(req.get("php", ""))
            if pmin:
                result["php_detected"] = pmin
                want = (app.get("requires") or {}).get("php") or "0.0"
                if _ver(pmin) > _ver(want):
                    add(False, "paket PHP %s+ istiyor, tarifte %s yaziyor" % (pmin, want), "warn")
        want = (app.get("requires") or {}).get("php") or ""
        need = max([v for v in (want, result["php_detected"]) if v] or [""], key=_ver)
        have = installed_php()
        if need and have:
            ok = any(_ver(v) >= _ver(need) for v in have)
            add(ok, "sunucuda uygun PHP var (%s+; kurulu: %s)" % (need, ", ".join(have)) if ok else
                "sunucuda PHP %s+ yok (kurulu: %s)" % (need, ", ".join(have)))
        levels = [c["level"] for c in checks]
        result["status"] = "fail" if "fail" in levels else ("warn" if "warn" in levels else "ok")
        return result
    except installer.InstallError as exc:
        add(False, str(exc))
        return result
    except Exception as exc:
        add(False, "beklenmeyen hata: %s" % exc)
        return result
    finally:
        result["seconds"] = round(time.time() - started, 1)
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2) deneme kurulumu
# ---------------------------------------------------------------------------

def test_domain():
    return (store.CFG.get("cyberpanel", "test_domain", default="") or "").strip().lower()


def ensure_test_site(log):
    domain = test_domain()
    if not domain or not installer.DOMAIN_RE.match(domain):
        raise installer.InstallError("Ayarlar'da gecerli bir test alan adi tanimlayin (ornek: apptest.alanadi.com)")
    if os.path.isdir(installer.HOME_BASE + "/%s" % domain):
        return domain
    have = installed_php()
    php = "8.3" if "8.3" in have else (have[-1] if have else "8.2")
    cp = installer.CyberPanel(log)
    cp.create_website(domain, "admin@%s" % domain, php)
    log("test sitesi olusturuldu: %s (PHP %s)" % (domain, php))
    store.audit("health_test_site", {"domain": domain, "php": php})
    return domain


def _params_for(app, domain, path):
    params = {"domain": domain, "path": path, "email": "admin@%s" % domain,
              "title": "AGFO deneme"}
    for field in app.get("fields", []):
        fid, ftype = field["id"], field.get("type", "text")
        if field.get("default"):
            params[fid] = field["default"]
        elif ftype == "email":
            params[fid] = "admin@%s" % domain
        elif ftype == "password":
            params[fid] = installer.random_password(18)
        else:
            params[fid] = "agfotest"
    return params


def _wait_job(job_id, timeout=1800):
    end = time.time() + timeout
    while time.time() < end:
        rec = store.get_job(job_id) or {}
        if rec.get("status") in ("done", "error"):
            return rec
        time.sleep(2)
    return {"status": "error", "error": "zaman asimi"}


def _start_with_retry(fn, *args):
    end = time.time() + 600
    while True:
        try:
            return fn(*args)
        except installer.InstallError as exc:
            if "Ayni anda" in str(exc) and time.time() < end:
                time.sleep(5)
                continue
            raise


def http_check(domain, url_path, follow=True):
    curl = shutil.which("curl") or "curl"
    body = tempfile.NamedTemporaryFile(delete=False, dir=store.WORK_DIR)
    body.close()
    try:
        proc = subprocess.run(
            [curl, "-skL" if follow else "-sk", "--max-redirs", "6", "--max-time", "60",
             "--resolve", "%s:80:127.0.0.1" % domain, "--resolve", "%s:443:127.0.0.1" % domain,
             "-o", body.name, "-w", "%{http_code} %{url_effective}", "http://%s%s" % (domain, url_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        out = proc.stdout.decode("utf-8", "replace").strip().split(" ", 1)
        code = int(out[0]) if out and out[0].isdigit() else 0
        final = out[1] if len(out) > 1 else ""
        with open(body.name, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(400000)
    finally:
        os.unlink(body.name)
    marker = ERROR_MARKERS.search(text or "")
    ok = 200 <= code < 400 and not marker and len((text or "").strip()) > 0
    reason = ""
    if not ok:
        reason = ("HTTP %d" % code) if not (200 <= code < 400) else (
            "sayfada hata: %s" % marker.group(0) if marker else "bos sayfa")
    return ok, code, final, reason, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or ""))[:240]


def trial_install(app, log):
    started = time.time()
    result = {"status": "fail", "tested": int(started), "stage": "", "detail": "", "http": 0}
    domain = None
    restore_php = None
    path = "/agfo-test-%s-%s" % (app["id"], secrets.token_hex(2))
    if app.get("root_only"):
        result["status"] = "skip"
        result["detail"] = "yalniz alan adi kokune kurulabildigi icin deneme kurulumu yapilmadi"
        return result
    try:
        result["stage"] = "test sitesi"
        domain = ensure_test_site(log)
        # Uygulama test sitesinden yuksek PHP istiyorsa test sitesini gecici olarak yukselt.
        need = (app.get("requires") or {}).get("php") or ""
        current = installer.site_php_version(domain) or ""
        if need and current and _ver(need) > _ver(current):
            if need not in installed_php():
                result["detail"] = "sunucuda PHP %s yok; deneme yapilamadi" % need
                return result
            installer.CyberPanel(log).change_php(domain, need)
            restore_php = current
            log("test sitesi gecici olarak PHP %s yapildi" % need)
        result["stage"] = "kurulum"
        job_id = _start_with_retry(installer.start_install, app["id"], _params_for(app, domain, path))
        log("deneme kurulumu basladi: %s%s (is %s)" % (domain, path, job_id))
        rec = _wait_job(job_id)
        result["job"] = job_id
        if rec.get("status") != "done":
            result["detail"] = rec.get("error") or "kurulum basarisiz"
            return result
        finish = (rec.get("result") or {}).get("url", "")
        url_path = re.sub(r"^https?://[^/]+", "", finish) or path + "/"
        result["stage"] = "sayfa"
        ok, code, final, reason, snippet = http_check(domain, url_path)
        result.update({"http": code, "final_url": final, "snippet": snippet})
        if not ok:
            result["detail"] = "kuruldu ama sayfa calismiyor: %s" % reason
            return result
        # Korunmasi gereken klasorler gercekten disariya kapali mi?
        leaks = []
        docroot = installer.HOME_BASE + "/%s/public_html%s" % (domain, path)
        for d in app.get("deny") or []:
            d = d.strip("/")
            if d.endswith("*"):
                import glob as _glob
                found = sorted(_glob.glob(os.path.join(docroot, d)))
                if not found:
                    continue
                d = os.path.relpath(found[0], docroot)
            elif not os.path.exists(os.path.join(docroot, d)):
                continue
            # Klasorse sonuna / eklenir; dosyaysa (db.ini gibi) dogrudan istenir --
            # aksi halde acik bir dosya da 404 doner ve korunuyor sanilir.
            suffix = "/" if os.path.isdir(os.path.join(docroot, d)) else ""
            dok, dcode, _, _, _ = http_check(domain, "%s/%s%s" % (path, d, suffix), follow=False)
            if dcode not in (401, 403, 404):
                leaks.append("%s%s (HTTP %d)" % (d, suffix, dcode))
        if leaks:
            result["detail"] = "kuruldu ama korunmasi gereken klasorler acik: %s" % ", ".join(leaks)
            return result
        result["status"] = "ok"
        result["detail"] = "kuruldu, %s HTTP %d dondu" % (url_path, code) + (
            "; korunan klasorler kapali" if app.get("deny") else "")
        return result
    except installer.InstallError as exc:
        result["detail"] = str(exc)
        return result
    except Exception as exc:
        result["detail"] = "beklenmeyen hata: %s" % exc
        return result
    finally:
        # Ne olursa olsun deneme kurulumunu temizle.
        if domain and installer.find_install(domain, path):
            try:
                uid = _start_with_retry(installer.start_uninstall, {
                    "domain": domain, "path": path, "confirm": domain,
                    "drop_db": True, "backup": False, "delete_site": False})
                rec = _wait_job(uid, 900)
                log("deneme temizlendi" if rec.get("status") == "done" else
                    "UYARI: deneme temizlenemedi: %s" % rec.get("error"))
            except Exception as exc:
                log("UYARI: deneme temizlenemedi: %s" % exc)
        if domain and restore_php:
            try:
                installer.CyberPanel(log).change_php(domain, restore_php)
                log("test sitesi PHP %s'e geri alindi" % restore_php)
            except Exception as exc:
                log("UYARI: test sitesinin PHP surumu geri alinamadi: %s" % exc)
        result["seconds"] = round(time.time() - started, 1)


# ---------------------------------------------------------------------------
# toplu calistirma (is olarak, gunluklu)
# ---------------------------------------------------------------------------

RUN = {"job": None}


def start(mode, app_ids=None):
    if mode not in ("package", "trial"):
        raise installer.InstallError("Gecersiz test turu")
    current = RUN.get("job")
    if current and (store.get_job(current) or {}).get("status") in ("queued", "running"):
        raise installer.InstallError("Bir saglik testi zaten calisiyor")
    apps = catalog.load(force=True)
    if app_ids:
        wanted = set(app_ids)
        apps = [a for a in apps if a["id"] in wanted]
    if not apps:
        raise installer.InstallError("Test edilecek uygulama yok")
    if mode == "trial" and not test_domain():
        raise installer.InstallError("Once Ayarlar'da test alan adini tanimlayin")
    job = installer.Job({"id": "health", "name": "Saglik testi"}, {"mode": mode})
    installer.JOBS[job.id] = job
    store.add_job({"id": job.id, "kind": "health", "app": "health",
                   "app_name": "Sağlık testi (%s)" % ("paket" if mode == "package" else "deneme kurulumu"),
                   "domain": test_domain() if mode == "trial" else "", "path": "",
                   "status": "queued", "created": int(time.time()), "total": len(apps)})
    RUN["job"] = job.id
    threading.Thread(target=_run, args=(job, mode, apps), daemon=True, name="health").start()
    return job.id


def _run(job, mode, apps):
    store.update_job(job.id, status="running", started=int(time.time()))
    summary = {"ok": 0, "warn": 0, "fail": 0}
    try:
        for i, app in enumerate(apps, 1):
            job.log("[%d/%d] %s" % (i, len(apps), app["name"]))
            log = lambda m: job.log("    " + m)
            res = package_check(app, log) if mode == "package" else trial_install(app, log)
            _save_entry(app["id"], mode, res)
            summary[res["status"]] = summary.get(res["status"], 0) + 1
            if mode == "package":
                for c in res["checks"]:
                    job.log("    %s %s" % ({"ok": "✓", "warn": "!", "fail": "✕"}[c["level"]], c["text"]))
            else:
                job.log("    %s %s" % ("✓" if res["status"] == "ok" else "✕", res.get("detail", "")))
            store.update_job(job.id, progress=i)
        catalog.load(force=True)
        job.log("BITTI: %d sorunsuz, %d uyarili, %d basarisiz" % (summary["ok"], summary.get("warn", 0), summary["fail"]))
        store.update_job(job.id, status="done", finished=int(time.time()),
                         result=dict(summary, kind="health", mode=mode))
        store.audit("health_run", dict(summary, mode=mode, apps=len(apps)))
    except Exception as exc:
        job.log("BEKLENMEYEN HATA: %s" % exc)
        store.update_job(job.id, status="error", finished=int(time.time()), error=str(exc))


def cleanup_orphans(log=lambda m: None):
    """Yarida kalmis deneme kurulumlarini (test sitesi, /agfo-test-*) kaldirir."""
    domain = test_domain()
    if not domain:
        return 0
    count = 0
    for item in store.load_installs():
        if item.get("domain") == domain and str(item.get("path", "")).startswith("/agfo-test-"):
            try:
                uid = _start_with_retry(installer.start_uninstall, {
                    "domain": domain, "path": item["path"], "confirm": domain,
                    "drop_db": True, "backup": False, "delete_site": False})
                _wait_job(uid, 900)
                count += 1
                log("artik deneme kurulumu temizlendi: %s" % item["path"])
            except Exception as exc:
                log("artik deneme kurulumu temizlenemedi (%s): %s" % (item["path"], exc))
    return count
