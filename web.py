import os
import asyncio
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

import archive_bot as ab

SESSION_DAYS = 7
INIT_MAX_AGE = 7 * 24 * 3600
PAGE = Path(__file__).resolve().parent / "webapp" / "index.html"
CACHE_TYPES = {"photo": "image/jpeg", "video": "video/mp4", "video_note": "video/mp4", "voice": "audio/ogg",
               "audio": "audio/mpeg", "animation": "video/mp4"}
HEADERS = {
    "Content-Security-Policy": "frame-ancestors https://web.telegram.org https://*.telegram.org",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def check_init_data(init_data, token=None, now=None):
    token = token or ab.BOT_TOKEN
    pairs = dict(parse_qsl(init_data or "", keep_blank_values=True))
    received = pairs.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None
    if (now or time.time()) - int(pairs.get("auth_date", "0")) > INIT_MAX_AGE:
        return None
    try:
        return int(json.loads(pairs.get("user", "{}"))["id"])
    except (KeyError, ValueError, TypeError):
        return None


def session_key():
    return hmac.new(b"archive-session", ab.BOT_TOKEN.encode(), hashlib.sha256).digest()


def make_token(user_id, now=None):
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    body = f"{user_id}.{exp}"
    sig = hmac.new(session_key(), body.encode(), hashlib.sha256).digest()[:18]
    return f"{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def read_token(token, now=None):
    try:
        uid, exp, sig = token.split(".")
        good = hmac.new(session_key(), f"{uid}.{exp}".encode(), hashlib.sha256).digest()[:18]
        if not hmac.compare_digest(base64.urlsafe_b64encode(good).decode().rstrip("="), sig):
            return None
        if int(exp) < (now or time.time()):
            return None
        return int(uid)
    except (ValueError, AttributeError):
        return None


def user_of(request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.query.get("t", "")
    uid = read_token(token)
    if not uid:
        raise web.HTTPUnauthorized(text="нужен вход", headers=HEADERS)
    return uid


def reply(data):
    return web.json_response(data, headers={**HEADERS, "Cache-Control": "no-store"},
                             dumps=lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":")))


def int_arg(request, name, default=None):
    try:
        return int(request.query.get(name, default))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text=f"плохой параметр {name}", headers=HEADERS)


async def page(request):
    return web.FileResponse(PAGE, headers={**HEADERS, "Cache-Control": "no-cache"})


async def login(request):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="нужен JSON", headers=HEADERS)
    uid = check_init_data(str(body.get("initData", "")))
    if not uid:
        raise web.HTTPUnauthorized(text="подпись Telegram не сошлась", headers=HEADERS)
    return reply({"token": make_token(uid), "has_archive": ab.owner_has_archive(uid)})


async def chats(request):
    uid = user_of(request)
    offset = max(0, int_arg(request, "offset", 0))
    with ab.db() as con:
        rows = con.execute(
            "SELECT chat_id, MAX(chat_title) AS title, MAX(date) AS last, COUNT(*) AS n, SUM(deleted) AS del"
            " FROM messages WHERE owner_id=? GROUP BY chat_id ORDER BY last DESC LIMIT 40 OFFSET ?",
            (uid, offset)).fetchall()
    return reply({"chats": [{"id": r["chat_id"], "title": r["title"], "last": r["last"][:16], "n": r["n"],
                             "del": r["del"] or 0} for r in rows], "more": len(rows) == 40})


async def days(request):
    uid = user_of(request)
    chat = int_arg(request, "chat")
    with ab.db() as con:
        rows = con.execute("SELECT substr(date,1,10) AS d, COUNT(*) AS n FROM messages WHERE owner_id=? AND chat_id=?"
                           " GROUP BY d ORDER BY d", (uid, chat)).fetchall()
    return reply({"days": [[r["d"], r["n"]] for r in rows]})


def message_json(r, was):
    return {"id": r["message_id"], "me": r["sender_id"] == r["owner_id"], "from": r["sender_name"],
            "t": r["date"][11:16], "d": r["date"][:10], "text": r["text"] or "", "media": r["media_type"],
            "kind": r["store_kind"], "file": bool(r["store_file_id"]), "del": bool(r["deleted"]),
            "ed": bool(r["edited"]), "was": was}


def first_versions(con, uid, chat, ids):
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT message_id, old_text FROM edits WHERE owner_id=? AND chat_id=? AND message_id IN ({marks})"
                       " AND old_text IS NOT NULL ORDER BY edited_at", (uid, chat, *ids)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["message_id"], r["old_text"])
    return out


async def messages(request):
    uid = user_of(request)
    chat = int_arg(request, "chat")
    day = request.query.get("day", "")
    after = int_arg(request, "after", 0)
    with ab.db() as con:
        if not day:
            last = con.execute("SELECT MAX(date) FROM messages WHERE owner_id=? AND chat_id=?", (uid, chat)).fetchone()[0]
            day = (last or "")[:10]
        rows = con.execute("SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND substr(date,1,10)=?"
                           " AND message_id>? ORDER BY message_id LIMIT 50", (uid, chat, day, after)).fetchall()
        edited = [r["message_id"] for r in rows if r["edited"]]
        was = first_versions(con, uid, chat, edited)
    return reply({"day": day, "messages": [message_json(r, was.get(r["message_id"])) for r in rows],
                  "more": len(rows) == 50})


async def search(request):
    uid = user_of(request)
    q = request.query.get("q", "").strip()
    offset = max(0, int_arg(request, "offset", 0))
    if len(q) < 2:
        return reply({"results": [], "more": False})
    with ab.db() as con:
        rows = con.execute("SELECT * FROM messages WHERE owner_id=? AND ulower(text) LIKE ? ORDER BY date DESC LIMIT 30 OFFSET ?",
                           (uid, f"%{q.lower()}%", offset)).fetchall()
    return reply({"results": [{**message_json(r, None), "chat": r["chat_id"], "title": r["chat_title"],
                               "text": (r["text"] or "")[:300]} for r in rows], "more": len(rows) == 30})


async def media(request):
    uid = user_of(request)
    chat = int_arg(request, "chat")
    mid = int_arg(request, "id")
    with ab.db() as con:
        row = con.execute("SELECT store_file_id, store_kind, ext FROM messages WHERE owner_id=? AND chat_id=?"
                          " AND message_id=?", (uid, chat, mid)).fetchone()
    if not row or not row["store_file_id"]:
        raise web.HTTPNotFound(text="файла нет", headers=HEADERS)
    cache = ab.DATA / "cache"
    cache.mkdir(exist_ok=True)
    name = hashlib.sha256(f"{uid}:{chat}:{mid}".encode()).hexdigest()[:24]
    target = cache / f"c_{name}{row['ext'] or ''}"
    if not target.exists():
        bot = request.app["bot"]
        part = target.with_suffix(target.suffix + ".part")
        for attempt in range(3):
            try:
                await bot.download(row["store_file_id"], destination=part)
                part.replace(target)
                break
            except Exception:
                await asyncio.sleep(2)
        else:
            raise web.HTTPServiceUnavailable(text="Telegram не отдал файл, попробуй ещё раз", headers=HEADERS)
    target.touch()
    kind = row["store_kind"] or ""
    headers = {**HEADERS, "Cache-Control": "private, max-age=3600"}
    if kind in CACHE_TYPES:
        headers["Content-Type"] = CACHE_TYPES[kind]
    return web.FileResponse(target, headers=headers)


async def send_to_chat(request):
    uid = user_of(request)
    try:
        body = await request.json()
        chat, mid = int(body["chat"]), int(body["id"])
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest(text="нужны chat и id", headers=HEADERS)
    with ab.db() as con:
        row = con.execute("SELECT media_type, sender_name, date FROM messages WHERE owner_id=? AND chat_id=?"
                          " AND message_id=? AND store_file_id IS NOT NULL", (uid, chat, mid)).fetchone()
    if not row:
        raise web.HTTPNotFound(text="файла нет", headers=HEADERS)
    ab.enqueue(uid, "media", f"Из архива: {row['media_type']} от {row['sender_name']}, {row['date'][:16]}"[:1000],
               (uid, chat, mid))
    return reply({"ok": True})


def make_app(bot):
    app = web.Application(client_max_size=64 * 1024)
    app["bot"] = bot
    app.router.add_get("/", page)
    app.router.add_get("/health", lambda request: web.Response(text="ok"))
    app.router.add_post("/api/login", login)
    app.router.add_get("/api/chats", chats)
    app.router.add_get("/api/days", days)
    app.router.add_get("/api/messages", messages)
    app.router.add_get("/api/search", search)
    app.router.add_get("/api/media", media)
    app.router.add_post("/api/send", send_to_chat)
    return app


async def start(bot, port):
    runner = web.AppRunner(make_app(bot), access_log=None)
    await runner.setup()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    await web.TCPSite(runner, host, port).start()
    ab.log.info("мини-апп слушает %s:%s", host, port)
    return runner
