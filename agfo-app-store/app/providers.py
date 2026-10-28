# -*- coding: utf-8 -*-
"""LLM saglayici katmani.

Uc noktalar AGFO AI Manager'daki `agfo_api_registry()` kaydiyla birebir ayni
tutulmustur; saglayici kodlari da ayni (Together.ai = llama_together).

Harici bagimlilik yoktur: istekler urllib ile yapilir.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

import store

# ---------------------------------------------------------------------------
# kayit
# ---------------------------------------------------------------------------

PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "chat": "https://api.openai.com/v1/chat/completions",
        "models": "https://api.openai.com/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": True,
        "token_field": "max_completion_tokens",
        "default_models": ["gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "chat": "https://openrouter.ai/api/v1/chat/completions",
        "models": "https://openrouter.ai/api/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": True,
        "token_field": "max_completion_tokens",
        "test_url": "https://openrouter.ai/api/v1/key",
        "default_models": ["openai/gpt-6-luna", "anthropic/claude-haiku-5-5"],
    },
    "groq": {
        "label": "Groq",
        "chat": "https://api.groq.com/openai/v1/chat/completions",
        "models": "https://api.groq.com/openai/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": True,
        "token_field": "max_tokens",
        "default_models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
    },
    "deepinfra": {
        "label": "DeepInfra",
        "chat": "https://api.deepinfra.com/v1/openai/chat/completions",
        "models": "https://api.deepinfra.com/v1/openai/models",
        "auth": "bearer", "shape": "openai", "json_mode": False,
        "token_field": "max_tokens",
        "default_models": ["deepseek-ai/DeepSeek-V4-Flash"],
    },
    "llama_together": {
        "label": "Together.ai",
        "chat": "https://api.together.xyz/v1/chat/completions",
        "models": "https://api.together.xyz/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": False,
        "token_field": "max_tokens",
        "default_models": ["Qwen/Qwen3.8-Flash", "zai-org/GLM-5.3-Flash"],
    },
    "claude": {
        "label": "Claude",
        "chat": "https://api.anthropic.com/v1/messages",
        "models": "https://api.anthropic.com/v1/models",
        "auth": "anthropic", "shape": "anthropic", "json_mode": False,
        "token_field": "max_tokens",
        "default_models": ["claude-haiku-5-5", "claude-sonnet-5-5"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "chat": "https://api.deepseek.com/chat/completions",
        "models": "https://api.deepseek.com/models",
        "auth": "bearer", "shape": "openai", "json_mode": True,
        "token_field": "max_tokens",
        "default_models": ["deepseek-flash", "deepseek-v4-pro"],
    },
    "nvidia": {
        "label": "NVIDIA NIM",
        "chat": "https://integrate.api.nvidia.com/v1/chat/completions",
        "models": "https://integrate.api.nvidia.com/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": False,
        "token_field": "max_tokens", "token_cap": 4096,
        "default_models": ["nvidia/nemotron-3.5-bolt-e4b", "openai/gpt-oss-120b"],
    },
    "minimax": {
        "label": "MiniMax",
        "chat": "https://api.minimax.io/v1/chat/completions",
        "models": "https://api.minimax.io/v1/models",
        "auth": "bearer", "shape": "openai", "json_mode": False,
        "token_field": "max_completion_tokens", "drop_n": True, "probe_chat": True,
        "default_models": ["MiniMax-M3.1-Flash", "MiniMax-M3"],
    },
    "gemini": {
        "label": "Gemini",
        "chat": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "models": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth": "query", "shape": "gemini", "json_mode": False,
        "token_field": "maxOutputTokens",
        "default_models": ["gemini-2.5-flash"],
    },
}

# OpenAI/OpenRouter'da bu modeller ornekleme alanlarini kabul etmez.
NO_SAMPLING_RE = re.compile(r"^(gpt-5|o\d+(-|$))")

MAX_OUTPUT_TOKENS = 2500


def catalog():
    return [{
        "id": pid,
        "label": meta["label"],
        "openai_compatible": meta["shape"] == "openai",
        "default_models": meta.get("default_models", []),
    } for pid, meta in sorted(PROVIDERS.items(), key=lambda kv: kv[1]["label"].lower())]


class ProviderError(Exception):
    pass


def _entry(provider):
    meta = PROVIDERS.get(provider)
    if not meta:
        raise ProviderError("Bilinmeyen saglayici: %s" % provider)
    saved = store.load_keys().get(provider) or {}
    key = (saved.get("key") or "").strip()
    if not key:
        raise ProviderError("%s icin API anahtari tanimli degil." % meta["label"])
    return meta, saved, key


def _request(url, headers, payload=None, timeout=120, method=None):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        return exc.code, body, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        raise ProviderError("Baglanti kurulamadi: %s" % getattr(exc, "reason", exc))
    except Exception as exc:
        raise ProviderError("Istek basarisiz: %s" % exc)


def _explain(status, body):
    detail = ""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            err = parsed.get("error") or parsed.get("message") or parsed
            if isinstance(err, dict):
                detail = err.get("message") or json.dumps(err, ensure_ascii=False)
            else:
                detail = str(err)
    except Exception:
        detail = (body or "")[:300]
    detail = re.sub(r"\s+", " ", detail or "")[:300]
    if status == 401 or status == 403:
        return "Anahtar reddedildi (%d): %s" % (status, detail)
    if status == 402:
        return "Bakiye/kredi yetersiz (402): %s" % detail
    if status == 429:
        return "Kota/hiz siniri (429): %s" % detail
    if status == 404:
        return "Model veya uc bulunamadi (404): %s" % detail
    if status == 202:
        return "Saglayici istegi kuyruga aldi (202); birkac saniye sonra tekrar deneyin."
    return "Saglayici hatasi (%d): %s" % (status, detail)


def _headers(meta, key, extra=None):
    headers = {"Content-Type": "application/json", "User-Agent": "AGFO-Firewall-AI/1.0"}
    if meta["auth"] == "bearer":
        headers["Authorization"] = "Bearer " + key
    elif meta["auth"] == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    headers.update(extra or {})
    return headers


def _resolve_model(provider, meta, saved, model):
    chosen = (model or saved.get("model") or "").strip()
    if chosen:
        return chosen
    defaults = meta.get("default_models") or []
    if defaults:
        return defaults[0]
    raise ProviderError("%s icin model secilmedi." % meta["label"])


# ---------------------------------------------------------------------------
# govde uretimi
# ---------------------------------------------------------------------------

def _openai_payload(meta, model, messages, temperature, json_mode):
    payload = {"model": model, "messages": messages}
    payload[meta.get("token_field", "max_tokens")] = min(
        MAX_OUTPUT_TOKENS, int(meta.get("token_cap") or MAX_OUTPUT_TOKENS))
    bare = model.split("/")[-1]
    if not NO_SAMPLING_RE.match(bare):
        payload["temperature"] = temperature
    if json_mode and meta.get("json_mode"):
        payload["response_format"] = {"type": "json_object"}
    if meta.get("drop_n"):
        payload.pop("n", None)
    return payload


def _anthropic_payload(meta, model, messages, temperature):
    system = ""
    converted = []
    for message in messages:
        if message.get("role") == "system":
            system += (message.get("content") or "") + "\n"
        else:
            converted.append({"role": message.get("role"), "content": message.get("content")})
    payload = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": converted,
        "temperature": temperature,
    }
    if system.strip():
        payload["system"] = system.strip()
    return payload


def _gemini_payload(meta, messages, temperature):
    system = ""
    contents = []
    for message in messages:
        if message.get("role") == "system":
            system += (message.get("content") or "") + "\n"
        else:
            contents.append({"role": "user" if message.get("role") == "user" else "model",
                             "parts": [{"text": message.get("content") or ""}]})
    payload = {"contents": contents,
               "generationConfig": {"temperature": temperature,
                                    "maxOutputTokens": MAX_OUTPUT_TOKENS}}
    if system.strip():
        payload["systemInstruction"] = {"parts": [{"text": system.strip()}]}
    return payload


def _extract(meta, body):
    try:
        data = json.loads(body)
    except ValueError:
        raise ProviderError("Saglayici gecersiz JSON dondurdu.")
    # OpenRouter uretim sirasinda olusan hatalari HTTP 200 govdesinde dondurebiliyor.
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        message = err.get("message") if isinstance(err, dict) else str(err)
        raise ProviderError("Saglayici hatasi: %s" % re.sub(r"\s+", " ", str(message))[:300])
    shape = meta["shape"]
    try:
        if shape == "openai":
            return data["choices"][0]["message"]["content"]
        if shape == "anthropic":
            parts = data.get("content") or []
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if shape == "gemini":
            cands = data.get("candidates") or []
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        pass
    raise ProviderError("Saglayici cevabindan metin cikarilamadi.")


# ---------------------------------------------------------------------------
# genel arayuz
# ---------------------------------------------------------------------------

def chat(provider, messages, model=None, temperature=0.1, timeout=120, json_mode=True):
    """(metin, kullanilan_model) dondurur."""
    meta, saved, key = _entry(provider)
    model = _resolve_model(provider, meta, saved, model)
    base = (saved.get("base_url") or "").strip()

    if meta["shape"] == "gemini":
        url = (base or meta["chat"]).replace("{model}", model) + "?key=" + urllib.parse.quote(key)
        payload = _gemini_payload(meta, messages, temperature)
        headers = {"Content-Type": "application/json"}
    elif meta["shape"] == "anthropic":
        url = base or meta["chat"]
        payload = _anthropic_payload(meta, model, messages, temperature)
        headers = _headers(meta, key)
    else:
        url = base or meta["chat"]
        payload = _openai_payload(meta, model, messages, temperature, json_mode)
        headers = _headers(meta, key)

    status, body, _ = _request(url, headers, payload, timeout=timeout)

    # Bazi saglayicilar response_format veya temperature kabul etmez; bir kez
    # bu alanlar olmadan tekrar dene.
    if status == 400 and isinstance(payload, dict):
        low = (body or "").lower()
        retry = dict(payload)
        changed = False
        if "response_format" in retry and "response_format" in low:
            retry.pop("response_format", None)
            changed = True
        if "temperature" in retry and "temperature" in low:
            retry.pop("temperature", None)
            changed = True
        if changed:
            status, body, _ = _request(url, headers, retry, timeout=timeout)

    if status != 200:
        raise ProviderError(_explain(status, body))
    text = _extract(meta, body)
    if not (text or "").strip():
        raise ProviderError("Saglayici bos cevap dondurdu.")
    return text, model


def test_key(provider):
    """(basarili, mesaj, model_listesi) dondurur."""
    try:
        meta, saved, key = _entry(provider)
    except ProviderError as exc:
        return False, str(exc), []
    if meta.get("probe_chat"):
        try:
            text, used = chat(provider, [{"role": "user", "content": "ping"}],
                              temperature=0.0, timeout=30, json_mode=False)
            return True, "anahtar calisiyor · %s yanit verdi" % used, []
        except ProviderError as exc:
            return False, str(exc), []
    url = meta.get("test_url") or meta.get("models") or ""
    base = (saved.get("base_url") or "").strip()
    if base:
        # Kendi ucunu veren kullanicilar icin: .../chat/completions -> .../models
        url = re.sub(r"/chat/completions/?$", "/models", base) or url
    if not url:
        return False, "Bu saglayici icin dogrulama ucu tanimli degil.", []
    headers = _headers(meta, key)
    if meta["auth"] == "query":
        url = url + "?key=" + urllib.parse.quote(key)
        headers = {"Content-Type": "application/json"}
    try:
        status, body, _ = _request(url, headers, None, timeout=30)
    except ProviderError as exc:
        return False, str(exc), []
    if status != 200:
        return False, _explain(status, body), []
    models = []
    try:
        data = json.loads(body)
        items = data.get("data") or data.get("models") or (data if isinstance(data, list) else [])
        for item in items:
            if isinstance(item, dict):
                name = item.get("id") or item.get("name") or ""
                if name:
                    models.append(str(name))
            elif isinstance(item, str):
                models.append(item)
    except Exception:
        pass
    if not models and isinstance(json.loads(body or "{}"), dict):
        # OpenRouter /key ucu model listesi dondurmez; anahtar gecerli demektir.
        return True, "anahtar calisiyor", []
    return True, "anahtar calisiyor · %d model goruldu" % len(models), models[:40]

