# -*- coding: utf-8 -*-
"""Olay ozetini AI'ya sorup yapilandirilmis oneri uretir.

AI yalnizca ONERI uretir; hicbir sey kendiliginden uygulanmaz. Uygulama
panelden onay verildiginde crowdsec.py uzerinden yapilir.
"""
from __future__ import annotations

import json
import re
import secrets
import time

ALLOWED_ACTIONS = ("ban", "ban_range", "allow", "install_collection", "note")

SYSTEM_PROMPT = (
    "Sen bir sunucu guvenligi analistisin. Girdi olarak bir CrowdSec saldiri ozeti "
    "alirsin ve YALNIZCA gecerli bir JSON nesnesi dondurursun. Aciklama, markdown, "
    "kod bloğu isareti ekleme. Cevaplarin Turkce olmali.\n\n"
    "Sunucu: CyberPanel + OpenLiteSpeed uzerinde WordPress siteleri barindiran bir "
    "Ubuntu sunucusu. Yanlis pozitif maliyetlidir: mesru ziyaretci, arama motoru "
    "botu (Googlebot, Bingbot), uptime izleyici veya odeme saglayicisi gibi "
    "goründügünde engelleme onerme, bunun yerine 'note' kullan.\n\n"
    "Donecegin JSON semasi:\n"
    "{\n"
    '  "summary": "2-4 cumlelik Turkce durum ozeti",\n'
    '  "risk": "low|medium|high",\n'
    '  "findings": [{"title": "kisa baslik", "detail": "aciklama", "ips": ["1.2.3.4"]}],\n'
    '  "proposals": [{\n'
    '     "action": "ban|ban_range|allow|install_collection|note",\n'
    '     "value": "IP, CIDR veya hub koleksiyon adi (note icin bos)",\n'
    '     "duration": "ban icin sure: 4h, 24h, 7d",\n'
    '     "reason": "CrowdSec kaydina yazilacak kisa sebep",\n'
    '     "why": "bu onerinin Turkce gerekcesi",\n'
    '     "confidence": 0.0\n'
    "  }]\n"
    "}\n\n"
    "Kurallar: en fazla 10 oneri. Yalnizca ozette gecen IP'leri kullan, IP uydurma. "
    "Genis araliklari (/24'ten genis) onerme. Zaten engellenmis IP icin tekrar ban onerme, "
    "gerekiyorsa sureyi uzatmayi 'note' ile anlat. Emin degilsen confidence degerini dusur."
)


def build_messages(summary, extra_note=""):
    payload = {
        "pencere": summary.get("window"),
        "uyari_sayisi": summary.get("alert_count"),
        "benzersiz_ip": summary.get("unique_ips"),
        "senaryolar": summary.get("scenarios", [])[:25],
        "ulkeler": summary.get("countries", [])[:15],
        "en_cok_uyari_veren_ipler": [
            {
                "ip": r.get("ip"),
                "uyari": r.get("count"),
                "olay": r.get("events"),
                "ulke": r.get("country"),
                "as": r.get("as_name"),
                "senaryolar": sorted(r.get("scenarios", {}).items(), key=lambda kv: -kv[1])[:5],
                "halihazirda_engelli": r.get("banned"),
                "son_gorulme": r.get("last"),
            }
            for r in (summary.get("top_ips") or [])[:40]
        ],
    }
    user = "CrowdSec ozeti:\n" + json.dumps(payload, ensure_ascii=False, indent=1)
    if extra_note:
        user += "\n\nYoneticinin notu: " + str(extra_note)[:800]
    user += "\n\nYalnizca JSON dondur."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_response(text):
    """Model ciktisindan JSON nesnesini cikarir."""
    if not text:
        raise ValueError("Model bos cevap dondurdu")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except ValueError:
            pass
    raise ValueError("Model cevabi JSON olarak cozumlenemedi")


def _clean_text(value, limit=600):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def to_proposals(parsed, meta):
    """Model ciktisini panelin kullandigi oneri kayitlarina cevirir."""
    items = []
    raw = parsed.get("proposals")
    if not isinstance(raw, list):
        raw = []
    for entry in raw[:10]:
        if not isinstance(entry, dict):
            continue
        action = (entry.get("action") or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            continue
        value = _clean_text(entry.get("value"), 200)
        if action in ("ban", "ban_range", "allow", "install_collection") and not value:
            continue
        try:
            confidence = float(entry.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        items.append({
            "id": secrets.token_hex(8),
            "created": int(time.time()),
            "status": "pending",
            "action": action,
            "value": value,
            "duration": _clean_text(entry.get("duration") or "24h", 10),
            "reason": _clean_text(entry.get("reason") or "agfo-firewall-ai", 200),
            "why": _clean_text(entry.get("why"), 800),
            "confidence": max(0.0, min(1.0, confidence)),
            "provider": meta.get("provider", ""),
            "model": meta.get("model", ""),
            "window": meta.get("window", ""),
        })
    analysis = {
        "summary": _clean_text(parsed.get("summary"), 1500),
        "risk": (parsed.get("risk") or "").strip().lower() or "unknown",
        "findings": [],
        "provider": meta.get("provider", ""),
        "model": meta.get("model", ""),
        "window": meta.get("window", ""),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "proposal_count": len(items),
    }
    for finding in (parsed.get("findings") or [])[:12]:
        if not isinstance(finding, dict):
            continue
        ips = finding.get("ips")
        analysis["findings"].append({
            "title": _clean_text(finding.get("title"), 160),
            "detail": _clean_text(finding.get("detail"), 900),
            "ips": [_clean_text(x, 60) for x in (ips if isinstance(ips, list) else [])][:12],
        })
    return analysis, items
