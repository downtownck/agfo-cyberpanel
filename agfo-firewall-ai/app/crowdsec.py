# -*- coding: utf-8 -*-
"""CrowdSec ile konusan ince katman.

Her sey `cscli` uzerinden yurutulur: surum farklarina dayanikli, ek kimlik
dogrulama gerektirmez (servis root calisir). Kabuk kullanilmaz; argumanlar
liste olarak gecirilir.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import time

import store

DURATION_RE = re.compile(r"^\d{1,5}(s|m|h|d)$")
TYPES = ("ban", "captcha")

# Korunan aglar. Python'un is_private tanimi dokumantasyon araliklarini
# (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) da kapsadigi icin burada
# gercekten korunmasi gereken araliklari acikca sayiyoruz.
PROTECTED_NETS = [ipaddress.ip_network(x) for x in (
    u"0.0.0.0/8",        # tanimsiz
    u"10.0.0.0/8",       # RFC1918
    u"172.16.0.0/12",    # RFC1918
    u"192.168.0.0/16",   # RFC1918
    u"127.0.0.0/8",      # loopback
    u"169.254.0.0/16",   # link-local
    u"100.64.0.0/10",    # CGNAT - cok sayida mesru kullanici paylasir
    u"::1/128",
    u"fc00::/7",
    u"fe80::/10",
)]


def cscli_path():
    configured = store.CFG.get("crowdsec", "cscli", default="") or ""
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    for candidate in ("/usr/bin/cscli", "/usr/local/bin/cscli", "/usr/sbin/cscli"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("cscli")


class CrowdSecError(Exception):
    pass


def run(args, timeout=25):
    """cscli <args> calistirir; (rc, stdout, stderr) dondurur."""
    binary = cscli_path()
    if not binary:
        raise CrowdSecError("cscli bulunamadi; CrowdSec kurulu mu?")
    try:
        proc = subprocess.run(
            [binary] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CrowdSecError("cscli zaman asimina ugradi: %s" % " ".join(args))
    except OSError as exc:
        raise CrowdSecError("cscli calistirilamadi: %s" % exc)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def run_json(args, timeout=25, default=None):
    """`-o json` ile calistirir ve cozumler. Bos cikti icin default doner."""
    rc, out, err = run(list(args) + ["-o", "json"], timeout=timeout)
    text = (out or "").strip()
    if rc != 0 and not text:
        raise CrowdSecError((err or out or "cscli hatasi").strip().split("\n")[-1])
    if not text or text in ("null", "[]"):
        return [] if default is None else default
    try:
        return json.loads(text)
    except ValueError:
        # Bazi surumler JSON'dan once uyari satiri basabiliyor.
        start = min([i for i in (text.find("["), text.find("{")) if i >= 0] or [-1])
        if start >= 0:
            try:
                return json.loads(text[start:])
            except ValueError:
                pass
        raise CrowdSecError("cscli JSON ciktisi cozumlenemedi")


# ---------------------------------------------------------------------------
# durum
# ---------------------------------------------------------------------------

def systemd_active(unit):
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def version():
    try:
        rc, out, err = run(["version"], timeout=10)
        text = (out or err or "").strip()
        match = re.search(r"version:?\s*v?([0-9][^\s,]*)", text, re.I)
        return match.group(1) if match else (text.split("\n")[0][:60] if text else "")
    except CrowdSecError:
        return ""


def status():
    """Panelin ust kisminda gosterilen ozet durum."""
    installed = bool(cscli_path())
    info = {
        "installed": installed,
        "version": version() if installed else "",
        "agent_running": systemd_active("crowdsec"),
        "bouncer_running": False,
        "bouncers": [],
        "machines": 0,
        "error": "",
    }
    if not installed:
        info["error"] = "CrowdSec kurulu degil."
        return info
    for unit in ("crowdsec-firewall-bouncer", "crowdsec-firewall-bouncer.service",
                 "cs-firewall-bouncer"):
        if systemd_active(unit):
            info["bouncer_running"] = True
            break
    try:
        bouncers = run_json(["bouncers", "list"], default=[]) or []
        info["bouncers"] = [{
            "name": b.get("name"),
            "type": b.get("type") or "",
            "last_pull": b.get("last_pull") or "",
            "revoked": bool(b.get("revoked")),
        } for b in bouncers if isinstance(b, dict)]
    except CrowdSecError as exc:
        info["error"] = str(exc)
    try:
        machines = run_json(["machines", "list"], default=[]) or []
        info["machines"] = len(machines)
    except CrowdSecError:
        pass
    return info


# ---------------------------------------------------------------------------
# uyarilar ve kararlar
# ---------------------------------------------------------------------------

def alerts(since="24h", limit=200):
    args = ["alerts", "list", "--limit", str(int(limit))]
    if since:
        args += ["--since", since]
    data = run_json(args, default=[]) or []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        source = item.get("source") or {}
        decisions = item.get("decisions") or []
        out.append({
            "id": item.get("id"),
            "created_at": item.get("created_at") or "",
            "scenario": item.get("scenario") or "",
            "message": item.get("message") or "",
            "events_count": item.get("events_count") or 0,
            "ip": source.get("value") or source.get("ip") or "",
            "country": source.get("cn") or "",
            "as_name": source.get("as_name") or "",
            "scope": source.get("scope") or "",
            "decisions": [{
                "type": d.get("type"), "duration": d.get("duration"),
                "scope": d.get("scope"), "value": d.get("value"),
            } for d in decisions if isinstance(d, dict)],
        })
    return out


def decisions(limit=300):
    data = run_json(["decisions", "list", "--limit", str(int(limit))], default=[]) or []
    out = []
    # cscli decisions list JSON'u surume gore ya duz liste ya da alert sarmali doner.
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if "decisions" in entry and isinstance(entry["decisions"], list):
            source = entry.get("source") or {}
            for d in entry["decisions"]:
                out.append(_decision_row(d, entry, source))
        else:
            out.append(_decision_row(entry, entry, entry.get("source") or {}))
    return out


def _decision_row(d, parent, source):
    return {
        "id": d.get("id") or parent.get("id"),
        "value": d.get("value") or source.get("value") or "",
        "scope": d.get("scope") or source.get("scope") or "Ip",
        "type": d.get("type") or "ban",
        "reason": d.get("scenario") or parent.get("scenario") or "",
        "origin": d.get("origin") or "",
        "duration": d.get("duration") or "",
        "until": d.get("until") or parent.get("until") or "",
        "country": source.get("cn") or "",
        "as_name": source.get("as_name") or "",
        "created_at": parent.get("created_at") or "",
    }


def metrics_text():
    try:
        rc, out, err = run(["metrics"], timeout=25)
        return (out or err or "").strip()
    except CrowdSecError as exc:
        return str(exc)


def collections():
    try:
        data = run_json(["collections", "list"], default={})
    except CrowdSecError:
        return []
    items = data.get("collections") if isinstance(data, dict) else data
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append({
                "name": item.get("name") or "",
                "status": item.get("status") or "",
                "version": item.get("local_version") or item.get("version") or "",
            })
    return out


# ---------------------------------------------------------------------------
# guvenlik suzgeci
# ---------------------------------------------------------------------------

def parse_target(value):
    """IP veya CIDR dogrular; (ip_network, scope) dondurur."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Bos adres")
    try:
        if "/" in value:
            net = ipaddress.ip_network(value, strict=False)
            return net, "Range"
        net = ipaddress.ip_network(u"%s/%d" % (value, 32 if ":" not in value else 128), strict=False)
        return net, "Ip"
    except ValueError:
        raise ValueError("Gecersiz IP veya CIDR: %s" % value)


def local_addresses():
    addrs = set()
    try:
        proc = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=10, check=False)
        for part in proc.stdout.decode("utf-8", "replace").split():
            addrs.add(part.strip())
    except Exception:
        pass
    addrs.add("127.0.0.1")
    addrs.add("::1")
    return addrs


def guard_check(value, actor_ip=None):
    """Engellenmesi tehlikeli adresleri reddeder. Hata mesaji dondurur ya da None."""
    net, scope = parse_target(value)
    never = set(store.CFG.get("guard", "never_ban", default=[]) or [])
    never |= local_addresses()
    if actor_ip:
        never.add(actor_ip)
    for item in never:
        try:
            candidate = ipaddress.ip_address(item.split("/")[0])
        except ValueError:
            continue
        if candidate in net:
            return "%s adresi korumali listede (%s); engellenemez." % (item, value)
    if store.CFG.get("guard", "protect_private_ranges", default=True):
        for protected in PROTECTED_NETS:
            if protected.version != net.version:
                continue
            if net.overlaps(protected):
                return ("%s korunan ag araligina giriyor (%s); engellenmesi kapali."
                        % (value, protected))
    if net.num_addresses > 65536:
        return "%s cok genis bir aralik (%d adres); reddedildi." % (value, net.num_addresses)
    return None


def normalize_duration(duration):
    duration = (duration or "").strip().lower()
    if not DURATION_RE.match(duration):
        raise ValueError("Sure bicimi gecersiz (ornek: 4h, 24h, 7d): %s" % duration)
    amount = int(duration[:-1])
    unit = duration[-1]
    hours = {"s": amount / 3600.0, "m": amount / 60.0, "h": amount, "d": amount * 24}[unit]
    limit = float(store.CFG.get("guard", "max_ban_duration_hours", default=720) or 720)
    if hours > limit:
        raise ValueError("Sure ust sinirin uzerinde (en fazla %g saat)." % limit)
    return duration


# ---------------------------------------------------------------------------
# karar uygulama
# ---------------------------------------------------------------------------

def add_decision(value, duration="4h", reason="agfo-firewall-ai", dtype="ban", actor_ip=None):
    if dtype not in TYPES:
        raise ValueError("Desteklenmeyen karar turu: %s" % dtype)
    duration = normalize_duration(duration)
    problem = guard_check(value, actor_ip=actor_ip)
    if problem:
        raise ValueError(problem)
    net, scope = parse_target(value)
    reason = re.sub(r"[\r\n]", " ", (reason or "agfo-firewall-ai"))[:200]
    args = ["decisions", "add", "--duration", duration, "--reason", reason, "--type", dtype]
    if scope == "Range":
        args += ["--range", str(net)]
    else:
        args += ["--ip", str(net.network_address)]
    rc, out, err = run(args, timeout=30)
    if rc != 0:
        raise CrowdSecError((err or out or "karar eklenemedi").strip().split("\n")[-1])
    store.audit("decision_add", {"value": value, "duration": duration,
                                 "reason": reason, "type": dtype})
    return (out or err or "").strip()


def delete_decision(value=None, decision_id=None):
    args = ["decisions", "delete"]
    if decision_id:
        args += ["--id", str(decision_id)]
    elif value:
        net, scope = parse_target(value)
        if scope == "Range":
            args += ["--range", str(net)]
        else:
            args += ["--ip", str(net.network_address)]
    else:
        raise ValueError("Silinecek karar belirtilmedi")
    rc, out, err = run(args, timeout=30)
    if rc != 0:
        raise CrowdSecError((err or out or "karar silinemedi").strip().split("\n")[-1])
    store.audit("decision_delete", {"value": value, "id": decision_id})
    return (out or err or "").strip()


def summarize(since="24h", limit=300):
    """AI'ya verilecek sikistirilmis ozet."""
    data = alerts(since=since, limit=limit)
    by_ip = {}
    by_scenario = {}
    by_country = {}
    for item in data:
        ip = item.get("ip") or "?"
        rec = by_ip.setdefault(ip, {
            "ip": ip, "count": 0, "scenarios": {}, "country": item.get("country") or "",
            "as_name": item.get("as_name") or "", "first": item.get("created_at"),
            "last": item.get("created_at"), "events": 0, "banned": False,
        })
        rec["count"] += 1
        rec["events"] += int(item.get("events_count") or 0)
        rec["last"] = item.get("created_at") or rec["last"]
        scenario = item.get("scenario") or "?"
        rec["scenarios"][scenario] = rec["scenarios"].get(scenario, 0) + 1
        if item.get("decisions"):
            rec["banned"] = True
        by_scenario[scenario] = by_scenario.get(scenario, 0) + 1
        country = item.get("country") or "?"
        by_country[country] = by_country.get(country, 0) + 1
    top_ips = sorted(by_ip.values(), key=lambda r: (-r["count"], r["ip"]))
    return {
        "window": since,
        "alert_count": len(data),
        "unique_ips": len(by_ip),
        "top_ips": top_ips,
        "scenarios": sorted(by_scenario.items(), key=lambda kv: -kv[1]),
        "countries": sorted(by_country.items(), key=lambda kv: -kv[1]),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
