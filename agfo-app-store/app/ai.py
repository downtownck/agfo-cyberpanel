# -*- coding: utf-8 -*-
"""App Store'un AI islevleri.

Ilke (Firewall AI ile ayni): AI yalnizca ONERIR. Hicbir sey kendiliginden
uygulanmaz; katalog duzeltmesi once sunucudan yoklanir, sonra kullanici onaylar.
Gonderilen her metinden sifreler temizlenir.
"""
from __future__ import annotations

import glob
import json
import os
import re
import time

import catalog
import installer
import providers
import store

ALLOWED_FORMATS = ("zip", "tar.gz", "tgz", "tar.bz2")


class AIError(Exception):
    pass


def configured_provider():
    keys = store.load_keys()
    chosen = (store.CFG.get("ai", "provider", default="") or "").strip()
    if chosen and chosen in keys:
        return chosen
    for pid in providers.PROVIDERS:
        if pid in keys:
            return pid
    return None


def status():
    summary = store.key_summary()
    return {
        "provider": configured_provider() or "",
        "model": store.CFG.get("ai", "model", default="") or "",
        "keys": summary,
        "catalog": providers.catalog(),
    }


def _ask(system, user, max_chars=60000):
    provider = configured_provider()
    if not provider:
        raise AIError("Tanimli AI anahtari yok. Firewall AI'ya ya da Ayarlar > AI bolumune anahtar ekleyin.")
    model = (store.CFG.get("ai", "model", default="") or None)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user[:max_chars]}]
    try:
        text, used = providers.chat(provider, messages, model=model, temperature=0.1,
                                    timeout=120, json_mode=True)
    except providers.ProviderError as exc:
        raise AIError(str(exc))
    return _parse_json(text), provider, used


def _parse_json(text):
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise AIError("AI gecerli JSON dondurmedi: %s" % raw[:200])


def server_facts():
    php = sorted(os.path.basename(os.path.dirname(os.path.dirname(p))).replace("lsphp", "")
                 for p in glob.glob("/usr/local/lsws/lsphp*/bin/php"))
    return {"php_kurulu": [v[0] + "." + v[1:] for v in php if v.isdigit() and len(v) >= 2],
            "web_sunucu": "OpenLiteSpeed (CyberPanel)", "veritabani": "MariaDB"}


# ---------------------------------------------------------------------------
# 1) kurulum hatasi analizi
# ---------------------------------------------------------------------------

ANALYZE_SYSTEM = (
    "Sen CyberPanel, OpenLiteSpeed, lsphp ve MariaDB uzmanisin. Sana basarisiz bir uygulama "
    "kurulumunun gunlugu verilecek. Turkce, kisa ve uygulanabilir yanit ver. Gunlukte olmayan "
    "seyi uydurma; emin degilsen guveni 'dusuk' yaz. YALNIZCA su JSON'u dondur: "
    '{"ozet": "tek cumle", "neden": "kok neden", "adimlar": ["kullanicinin yapacagi adim", "..."], '
    '"katalog_sorunu": true/false (sorun indirme adresi ya da tarif kaynakliysa true), '
    '"guven": "yuksek|orta|dusuk"}'
)


def job_lines(job_id):
    runtime = installer.get_runtime_job(job_id)
    if runtime:
        return runtime.tail(0)[0]
    path = os.path.join(store.WORK_DIR, "%s.log" % job_id)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return []


def analyze_job(job_id):
    record = store.get_job(job_id)
    if not record:
        raise AIError("Is bulunamadi")
    if record.get("status") != "error":
        raise AIError("Yalnizca basarisiz isler analiz edilir")
    lines = job_lines(job_id)[-200:]
    secrets_ = []
    result = record.get("result") or {}
    for key in ("db_pass", "admin_pass"):
        if result.get(key):
            secrets_.append(result[key])
    log = installer.redact("\n".join(lines), secrets_)
    app = catalog.get(record.get("app") or "") or {}
    summary = {
        "uygulama": app.get("name") or record.get("app"),
        "kurulum_turu": app.get("install_mode"),
        "gereken_php": (app.get("requires") or {}).get("php"),
        "indirme": app.get("download"),
        "hedef": "%s%s" % (record.get("domain", ""), record.get("path", "")),
        "is_turu": record.get("kind", "install"),
        "hata": installer.redact(record.get("error", ""), secrets_),
        "sunucu": server_facts(),
    }
    user = "KURULUM BILGISI:\n%s\n\nGUNLUK (sifreler gizlendi):\n%s" % (
        json.dumps(summary, ensure_ascii=False, indent=1), log or "(gunluk yok)")
    data, provider, model = _ask(ANALYZE_SYSTEM, user)
    out = {
        "ozet": str(data.get("ozet", ""))[:400],
        "neden": str(data.get("neden", ""))[:1200],
        "adimlar": [str(x)[:500] for x in (data.get("adimlar") or [])][:8],
        "katalog_sorunu": bool(data.get("katalog_sorunu")),
        "guven": str(data.get("guven", ""))[:10],
        "provider": provider, "model": model, "app": record.get("app"),
    }
    store.audit("ai_analyze", {"job": job_id, "provider": provider, "model": model})
    return out


# ---------------------------------------------------------------------------
# 2) katalog onarimi: yeni indirme adresi onerisi
# ---------------------------------------------------------------------------

REPAIR_SYSTEM = (
    "Sen acik kaynak PHP uygulamalarinin resmi dagitim kanallarini bilen bir uzmansin. "
    "Bir uygulamanin indirme adresi artik calismiyor. Kurulabilir TAM paketin (vendor/ "
    "bagimliliklari dahil, derleme gerektirmeyen) resmi ve tercihen surum numarasi "
    "icermeyen 'son surum' adresini oner. GitHub'da paket varsa {\"github\": \"sahip/depo\", "
    "\"asset\": \"dosya adi icin regex\"} bicimini kullanabilirsin. Kaynak kod arsivi "
    "(Source code zip) ONERME. Bilmiyorsan uydurma, url'yi bos birak. YALNIZCA su JSON'u dondur: "
    '{"url": "https://...", "github": "", "asset": "", "format": "zip|tar.gz|tar.bz2", '
    '"strip": 0 veya 1 (arsiv tek ust klasorle basliyorsa 1), "only": "" , '
    '"surum_notu": "kisa", "aciklama": "neden bu adres", "kaynak_sayfa": "https://..."}'
)


def propose_download(app_id):
    app = catalog.get(app_id)
    if not app:
        raise AIError("Uygulama bulunamadi")
    current = dict(app.get("download") or {})
    probe = {}
    try:
        spec = installer.resolve_download(current, lambda m: None)
        ok, code, err = installer.probe_url(spec["url"])
        probe = {"ok": ok, "status": code, "error": err, "url": spec["url"]}
    except Exception as exc:
        probe = {"ok": False, "error": str(exc)[:200]}
    user = json.dumps({
        "uygulama": app["name"], "ana_sayfa": app.get("homepage"),
        "gereken_php": (app.get("requires") or {}).get("php"),
        "mevcut_indirme": current, "sunucudan_yoklama": probe,
        "bugun": time.strftime("%Y-%m-%d"),
    }, ensure_ascii=False, indent=1)
    data, provider, model = _ask(REPAIR_SYSTEM, user)

    fmt = str(data.get("format") or "").strip()
    if fmt not in ALLOWED_FORMATS:
        raise AIError("AI gecersiz arsiv bicimi onerdi: %s" % fmt)
    proposal = {"format": fmt, "strip": 1 if int(data.get("strip") or 0) else 0}
    if str(data.get("only") or "").strip():
        only = str(data["only"]).strip().strip("/")
        if not re.match(r"^[A-Za-z0-9._-]{1,60}$", only):
            raise AIError("Gecersiz 'only' degeri")
        proposal["only"] = only
    if str(data.get("github") or "").strip():
        repo = str(data["github"]).strip()
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
            raise AIError("Gecersiz GitHub deposu onerildi")
        proposal["github"] = repo
        proposal["asset"] = str(data.get("asset") or r"\.zip$")[:120]
        try:
            re.compile(proposal["asset"])
        except re.error:
            raise AIError("Gecersiz dosya deseni onerildi")
    else:
        url = str(data.get("url") or "").strip()
        if not url:
            raise AIError("AI bu uygulama icin guvenilir bir adres bilmedigini soyledi.")
        if not url.startswith("https://") or len(url) > 400 or re.search(r"\s", url):
            raise AIError("AI gecersiz adres onerdi: %s" % url[:120])
        proposal["url"] = url

    # Oneri, uygulanabilmesi icin once bu sunucudan yoklanir.
    check = {"ok": False, "status": 0, "error": "", "resolved": ""}
    try:
        resolved = installer.resolve_download(proposal, lambda m: None)
        check["resolved"] = resolved["url"]
        check["ok"], check["status"], check["error"] = installer.probe_url(resolved["url"])
    except Exception as exc:
        check["error"] = str(exc)[:200]

    item = {
        "app": app_id, "app_name": app["name"], "download": proposal,
        "current": current, "check": check, "created": int(time.time()),
        "note": str(data.get("surum_notu", ""))[:80],
        "explanation": str(data.get("aciklama", ""))[:600],
        "source_page": str(data.get("kaynak_sayfa", ""))[:300],
        "provider": provider, "model": model,
    }
    store.save_proposal(app_id, item)
    store.audit("ai_catalog_proposal", {"app": app_id, "ok": check["ok"], "provider": provider})
    return item


def apply_proposal(app_id):
    item = store.load_proposals().get(app_id)
    if not item:
        raise AIError("Bekleyen oneri yok")
    # Onay aninda yeniden yokla: arada adres dusmus olabilir.
    resolved = installer.resolve_download(item["download"], lambda m: None)
    ok, code, err = installer.probe_url(resolved["url"])
    if not ok:
        raise AIError("Onerilen adres su an erisilemiyor (HTTP %s %s); uygulanmadi." % (code, err))
    store.set_override(app_id, item["download"], item.get("current"),
                       note=item.get("note") or "AI onerisi")
    store.save_proposal(app_id, None)
    catalog.load(force=True)
    store.audit("catalog_override_apply", {"app": app_id, "url": resolved["url"]})
    return {"app": app_id, "url": resolved["url"]}
