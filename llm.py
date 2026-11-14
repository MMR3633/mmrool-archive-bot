import json
import logging
import os
import time

log = logging.getLogger("archive.llm")

MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
URL = "https://api.anthropic.com/v1/messages"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
STATE = {"down_until": 0.0}


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or OLLAMA_URL) and time.time() >= STATE["down_until"]


def strong():
    """Сильная модель (по API): ей можно доверить пересказ фактов. Локальная маленькая путает факты."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def ask(prompt, system="", max_tokens=900, temperature=0.4, history=None):
    """Один ответ модели. history: [(вопрос, ответ)] прошлых реплик разговора. None, если мозг недоступен."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return await ask_anthropic(prompt, system, max_tokens, history)
    if OLLAMA_URL and time.time() >= STATE["down_until"]:
        return await ask_ollama(prompt, system, max_tokens, temperature, history)
    return None


def messages(prompt, history):
    out = []
    for q, a in history or []:
        out += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    return out + [{"role": "user", "content": prompt}]


async def ask_anthropic(prompt, system, max_tokens, history):
    import aiohttp
    body = {"model": MODEL, "max_tokens": max_tokens, "system": system, "messages": messages(prompt, history)}
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            async with s.post(URL, headers=headers, data=json.dumps(body)) as r:
                data = await r.json()
        if r.status != 200:
            log.warning("LLM ответил %s: %s", r.status, str(data)[:200])
            return None
        return "".join(part.get("text", "") for part in data.get("content", [])).strip() or None
    except Exception as e:
        log.warning("LLM недоступен: %s", e)
        return None


async def ask_ollama(prompt, system, max_tokens, temperature, history):
    """Локальная модель через Ollama. Упала: минуту не дёргаем, работаем на правилах."""
    import aiohttp
    body = {"model": OLLAMA_MODEL, "stream": False, "keep_alive": -1,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages(prompt, history),
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as s:
            async with s.post(OLLAMA_URL.rstrip("/") + "/api/chat", json=body) as r:
                data = await r.json(content_type=None)
        if r.status != 200:
            log.warning("локальный мозг ответил %s: %s", r.status, str(data)[:200])
            return None
        return (data.get("message") or {}).get("content", "").strip() or None
    except Exception as e:
        STATE["down_until"] = time.time() + 60
        log.warning("локальный мозг недоступен: %s", e)
        return None


async def ask_json(prompt, system=""):
    text = await ask(prompt, system + "\nОтвечай только валидным JSON без пояснений.", temperature=0)
    if not text:
        return None
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [-1])
    if start < 0:
        return None
    try:
        return json.loads(text[start:text.rfind("}" if text[start] == "{" else "]") + 1])
    except ValueError:
        return None


def transcript(rows, owner_id, limit=400):
    lines = []
    for r in rows[-limit:]:
        who = "Я" if r["sender_id"] == owner_id else (r["sender_name"] or "Собеседник")
        text = (r["text"] or (f"[{r['media_type']}]" if r["media_type"] else "")).replace("\n", " ")
        lines.append(f"[{r['date'][:16]}] {who}: {text[:400]}")
    return "\n".join(lines)
