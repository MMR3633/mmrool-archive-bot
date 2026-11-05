import json
import logging
import os

log = logging.getLogger("archive.llm")

MODEL = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
URL = "https://api.anthropic.com/v1/messages"


def enabled():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def ask(prompt, system="", max_tokens=900):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import aiohttp
    body = {"model": MODEL, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
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


async def ask_json(prompt, system=""):
    text = await ask(prompt, system + "\nОтвечай только валидным JSON без пояснений.")
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
