"""Мини-апп «Угу»: статика /u/ и API /u/api/* (архив, планы, заметки, вопросы, картинки, камера, тариф, партнёрка)."""
import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

import archive_bot as ab
import web as w
from timeparse import MSK, parse_when

ROOT = Path(__file__).resolve().parent / "webapp" / "ugu"
COLORS = {"none", "violet", "pink", "yellow", "green", "blue"}
FX_KINDS = {"demotivator": "демотиватор", "shakal": "шакал", "zhmykh": "жмых", "meme": "текст"}
PHOTO_MAX = 12 * 1024 * 1024
SNOOZE_MAX = 60 * 24 * 30
VOICE_KINDS = ("голосовое", "кружок")
TEXT_MAX = {"title": 120, "body": 4000, "q": 500, "task": 300, "busy": 300}
RATE = {}


def now():
    return datetime.now(MSK)


def iso(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")


def t_iso(s):
    """'2026-11-14 18:05:00' → '2026-11-14T18:05' (так дату понимает любой браузер, и iPhone тоже)."""
    return (s or "")[:16].replace(" ", "T")


def bad(text):
    return web.HTTPBadRequest(text=text, headers=w.HEADERS)


async def body_json(request):
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise bad("нужен JSON")
    if not isinstance(data, dict):
        raise bad("нужен объект")
    return data


def text_of(data, key, limit, required=True):
    val = data.get(key, "")
    if not isinstance(val, str):
        raise bad(f"{key}: нужна строка")
    val = val.strip()[:limit]
    if required and not val:
        raise bad(f"{key}: пусто")
    return val


def path_id(request):
    try:
        return int(request.match_info["id"])
    except ValueError:
        raise bad("плохой id")


def throttle(uid, key, per_min):
    """Простой ограничитель частоты на тяжёлые ручки (поиск, фото), чтобы апп не долбили скриптом."""
    t = time.monotonic()
    hits = [x for x in RATE.get((uid, key), []) if t - x < 60]
    if len(hits) >= per_min:
        raise web.HTTPTooManyRequests(text="слишком часто, подожди минутку", headers=w.HEADERS)
    hits.append(t)
    RATE[(uid, key)] = hits


def init_db():
    with ab.db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS ugu_names (user_id INTEGER PRIMARY KEY, name TEXT, username TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS ugu_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, title TEXT, "
                    "body TEXT, created TEXT, pinned INTEGER DEFAULT 0)")
        try:
            con.execute("ALTER TABLE ugu_notes ADD COLUMN color TEXT")
        except Exception:
            pass


# ---------- вход и профиль ----------

async def login(request):
    data = str((await body_json(request)).get("initData", ""))
    uid = w.check_init_data(data, ab.UGU_TOKEN) if ab.UGU_TOKEN else None
    uid = uid or w.check_init_data(data)
    if not uid:
        raise web.HTTPUnauthorized(text="подпись Telegram не сошлась", headers=w.HEADERS)
    try:
        user = json.loads(dict(parse_qsl(data)).get("user", "{}"))
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)[:64]
        with ab.db() as con:
            con.execute("INSERT INTO ugu_names VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,"
                        " username=excluded.username", (uid, name, (user.get("username") or "")[:64]))
    except (ValueError, AttributeError):
        pass
    return w.reply({"token": w.make_token(uid), "has_archive": ab.owner_has_archive(uid)})


def name_of(uid):
    with ab.db() as con:
        r = con.execute("SELECT name FROM ugu_names WHERE user_id=?", (uid,)).fetchone()
    return (r["name"] if r else "") or "Ты"


def settings_of(uid):
    import assistant
    return {"notify_deleted": bool(ab.pref(uid, "notify_deleted")), "notify_edited": bool(ab.pref(uid, "notify_edited")),
            "digest": bool(assistant.setting(uid, "digest")), "voice_auto": bool(assistant.setting(uid, "voice"))}


async def me(request):
    import tiers
    uid = w.user_of(request)
    return w.reply({"user": {"id": uid, "name": name_of(uid)}, "tier": tiers.tier_of(uid), "until": t_iso(tiers.until_of(uid)),
                    "limits": tiers.limits_view(uid), "settings": settings_of(uid), "has_archive": ab.owner_has_archive(uid)})


async def put_settings(request):
    import assistant
    uid = w.user_of(request)
    data = await body_json(request)
    with ab.db() as con:
        for key in ("notify_deleted", "notify_edited"):
            if key in data:
                con.execute("INSERT OR REPLACE INTO prefs VALUES (?,?,?)", (uid, key, int(bool(data[key]))))
    for key, col in (("digest", "digest"), ("voice_auto", "voice")):
        if key in data:
            assistant.set_setting(uid, col, int(bool(data[key])))
    return w.reply({"ok": True, "settings": settings_of(uid)})


async def wipe(request):
    """Удаляет всё о человеке: архив с файлами, планы, заметки. Тариф и оплаты остаются (это чеки)."""
    uid = w.user_of(request)
    with ab.db() as con:
        files = [r[0] for r in con.execute("SELECT file_path FROM messages WHERE owner_id=? AND file_path IS NOT NULL", (uid,))]
        for table, col in (("messages", "owner_id"), ("edits", "owner_id"), ("reminders", "owner_id"), ("tasks", "owner_id"),
                           ("busy", "owner_id"), ("busy_hits", "owner_id"), ("birthdays", "owner_id"), ("ugu_notes", "owner_id"),
                           ("pending", "owner_id"), ("ugu_log", "owner_id"), ("ugu_pending", "owner_id"), ("prefs", "owner_id")):
            try:
                con.execute(f"DELETE FROM {table} WHERE {col}=?", (uid,))
            except Exception:
                pass
    for f in files:
        try:
            p = Path(f)
            if p.is_file() and ab.DATA in p.resolve().parents:
                p.unlink()
        except OSError:
            pass
    shutil.rmtree(ab.DATA / "cache", ignore_errors=True)
    return w.reply({"ok": True})


# ---------- сегодня ----------

async def today(request):
    uid = w.user_of(request)
    t = now()
    day = t.strftime("%Y-%m-%d")
    since = (t - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with ab.db() as con:
        deleted = con.execute("SELECT COUNT(*) FROM messages WHERE owner_id=? AND deleted=1 AND deleted_at LIKE ?"
                              " AND (sender_id IS NULL OR sender_id != ?)", (uid, day + "%", uid)).fetchone()[0]
        edited = con.execute("SELECT COUNT(*) FROM edits WHERE owner_id=? AND edited_at LIKE ?", (uid, day + "%")).fetchone()[0]
        voice = con.execute("SELECT COUNT(*) FROM messages WHERE owner_id=? AND date LIKE ? AND media_type IN (?,?)",
                            (uid, day + "%", *VOICE_KINDS)).fetchone()[0]
        lasts = con.execute("SELECT m.chat_id, m.chat_title, m.sender_id, m.date, m.text, m.media_type FROM messages m JOIN ("
                            " SELECT chat_id, MAX(date) d FROM messages WHERE owner_id=? AND chat_id > 0 AND date >= ?"
                            " GROUP BY chat_id) x ON x.chat_id=m.chat_id AND x.d=m.date WHERE m.owner_id=?",
                            (uid, since, uid)).fetchall()
        bdays = con.execute("SELECT name, day, month FROM birthdays WHERE owner_id=?", (uid,)).fetchall()
    waiting = []
    for r in sorted(lasts, key=lambda r: r["date"]):
        hours = int((t - datetime.strptime(r["date"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)).total_seconds() // 3600)
        if r["sender_id"] != uid and hours >= 3:
            waiting.append({"chat_id": r["chat_id"], "name": r["chat_title"] or "?", "hours": hours,
                            "text": (r["text"] or (f"[{r['media_type']}]" if r["media_type"] else ""))[:120]})
    return w.reply({"counters": {"deleted": deleted, "edited": edited, "voice": voice}, "waiting": waiting[:5],
                    "birthdays": upcoming_birthdays(bdays, t, 14)})


def next_birthday(day, month, t):
    for year in (t.year, t.year + 1):
        try:
            d = datetime(year, month, day, tzinfo=MSK)
        except ValueError:
            d = datetime(year, 3, 1, tzinfo=MSK)
        if d.date() >= t.date():
            return d
    return None


def upcoming_birthdays(rows, t, horizon):
    out = []
    for b in rows:
        d = next_birthday(b["day"], b["month"], t)
        if d and (d.date() - t.date()).days <= horizon:
            out.append({"name": b["name"], "date": d.strftime("%Y-%m-%d"), "days": (d.date() - t.date()).days})
    return sorted(out, key=lambda b: b["days"])


# ---------- планы ----------

def chat_of(context):
    m = re.match(r"(?i)^чат с (.+)$", context or "")
    return m.group(1) if m else (context or "")


def day_arg(request, name, default):
    raw = request.query.get(name, "")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=MSK) if raw else default
    except ValueError:
        raise bad(f"плохой параметр {name}")


async def plans(request):
    uid = w.user_of(request)
    t = now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = day_arg(request, "from", t)
    end = day_arg(request, "to", start + timedelta(days=6))
    if end < start or (end - start).days > 62:
        raise bad("слишком длинный период")
    stop = end + timedelta(days=1)
    with ab.db() as con:
        rems = con.execute("SELECT id, title, due, status, context FROM reminders WHERE owner_id=? AND due>=? AND due<?"
                           " AND status IN ('active','done','missed') ORDER BY due", (uid, iso(start), iso(stop))).fetchall()
        tasks = con.execute("SELECT id, text, done, created FROM tasks WHERE owner_id=? AND (done=0 OR created>=?)"
                            " ORDER BY done, id DESC LIMIT 100", (uid, iso(now() - timedelta(days=7)))).fetchall()
        bdays = con.execute("SELECT name, day, month FROM birthdays WHERE owner_id=?", (uid,)).fetchall()
        busy = con.execute("SELECT until, text FROM busy WHERE owner_id=?", (uid,)).fetchone()
    items = [{"id": r["id"], "kind": "remind", "text": r["title"], "when": t_iso(r["due"]), "chat": chat_of(r["context"]),
              "done": r["status"] != "active"} for r in rems]
    for b in rows_in(bdays, start, end):
        items.append({"id": f"b{b['date']}{b['name']}", "kind": "birthday", "text": f"День рождения {b['name']}", "date": b["date"]})
    items += [{"id": r["id"], "kind": "task", "text": r["text"], "done": bool(r["done"])} for r in tasks]
    active = busy and busy["until"] > iso(now())
    return w.reply({"items": items, "busy": {"until": t_iso(busy["until"]), "text": busy["text"]} if active else None})


def rows_in(bdays, start, end):
    out = []
    for b in bdays:
        d = next_birthday(b["day"], b["month"], start)
        if d and start.date() <= d.date() <= end.date():
            out.append({"name": b["name"], "date": d.strftime("%Y-%m-%d")})
    return out


def plan_room(uid):
    import tiers
    ok, tier, cap = tiers.room(uid, "plans")
    if not ok:
        raise web.HTTPPaymentRequired(text=f"На {tiers.NAMES[tier]} не больше {cap} активных напоминаний и задач",
                                      headers=w.HEADERS)


async def add_remind(request):
    import assistant
    uid = w.user_of(request)
    text = text_of(await body_json(request), "text", TEXT_MAX["task"])
    plan_room(uid)
    title = assistant.clean_title(text)
    when, rest, vague = parse_when(title)
    title = assistant.clean_title(rest) or title or "Напоминание"
    t = now()
    if when is None or when <= t:
        when = (t + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    left = when - t
    with ab.db() as con:
        cur = con.execute("INSERT INTO reminders (owner_id, title, due, created, context, ping30, ping5) VALUES (?,?,?,?,?,?,?)",
                          (uid, title[:200], iso(when), iso(t), "", int(left <= timedelta(minutes=31)),
                           int(left <= timedelta(minutes=6))))
    return w.reply({"id": cur.lastrowid, "when": t_iso(iso(when)), "text": title})


def own_reminder(con, uid, rid):
    r = con.execute("SELECT * FROM reminders WHERE id=? AND owner_id=?", (rid, uid)).fetchone()
    if not r:
        raise web.HTTPNotFound(text="нет такого напоминания", headers=w.HEADERS)
    return r


async def snooze(request):
    uid = w.user_of(request)
    rid = path_id(request)
    try:
        minutes = int((await body_json(request)).get("minutes", 0))
    except (TypeError, ValueError):
        raise bad("minutes: нужно число")
    if not 1 <= minutes <= SNOOZE_MAX:
        raise bad("minutes: от 1 минуты до 30 дней")
    with ab.db() as con:
        r = own_reminder(con, uid, rid)
        base = max(datetime.strptime(r["due"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK), now())
        when = base + timedelta(minutes=minutes)
        left = when - now()
        con.execute("UPDATE reminders SET due=?, status='active', ping30=?, ping5=?, spam_count=0, last_spam=NULL WHERE id=?",
                    (iso(when), int(left <= timedelta(minutes=31)), int(left <= timedelta(minutes=6)), rid))
    return w.reply({"id": rid, "when": t_iso(iso(when))})


async def plan_done(request):
    uid = w.user_of(request)
    rid = path_id(request)
    with ab.db() as con:
        own_reminder(con, uid, rid)
        con.execute("UPDATE reminders SET status='done' WHERE id=?", (rid,))
    return w.reply({"ok": True})


async def plan_delete(request):
    uid = w.user_of(request)
    rid = path_id(request)
    with ab.db() as con:
        own_reminder(con, uid, rid)
        con.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (rid,))
    return w.reply({"ok": True})


async def add_task(request):
    uid = w.user_of(request)
    text = text_of(await body_json(request), "text", TEXT_MAX["task"])
    plan_room(uid)
    with ab.db() as con:
        cur = con.execute("INSERT INTO tasks (owner_id, text, who, chat_title, created) VALUES (?,?,?,?,?)",
                          (uid, text, "", "", iso(now())))
    return w.reply({"id": cur.lastrowid, "text": text, "done": False})


async def toggle_task(request):
    uid = w.user_of(request)
    tid = path_id(request)
    with ab.db() as con:
        r = con.execute("SELECT done FROM tasks WHERE id=? AND owner_id=?", (tid, uid)).fetchone()
        if not r:
            raise web.HTTPNotFound(text="нет такой задачи", headers=w.HEADERS)
        con.execute("UPDATE tasks SET done=? WHERE id=?", (int(not r["done"]), tid))
    return w.reply({"id": tid, "done": not r["done"]})


async def busy_on(request):
    uid = w.user_of(request)
    data = await body_json(request)
    try:
        hours = float(data.get("hours", 1))
    except (TypeError, ValueError):
        raise bad("hours: нужно число")
    if not 0 < hours <= 72:
        raise bad("hours: от 0 до 72")
    text = text_of(data, "text", TEXT_MAX["busy"], required=False) or "Сейчас занят, отвечу чуть позже."
    until = now() + timedelta(hours=hours)
    with ab.db() as con:
        con.execute("INSERT OR REPLACE INTO busy VALUES (?,?,?,?)", (uid, iso(until), text, iso(now())))
        con.execute("DELETE FROM busy_hits WHERE owner_id=?", (uid,))
    return w.reply({"until": t_iso(iso(until)), "text": text})


async def busy_off(request):
    import assistant
    uid = w.user_of(request)
    with ab.db() as con:
        active = con.execute("SELECT 1 FROM busy WHERE owner_id=?", (uid,)).fetchone()
    if active:
        await assistant.finish_busy(ab.bot_for(uid, request.app["bot"]), uid)
    return w.reply({"ok": True})


# ---------- заметки ----------

def note_json(r):
    return {"id": r["id"], "title": r["title"] or "", "body": r["body"] or "", "color": r["color"] or "none",
            "pinned": bool(r["pinned"]), "ts": t_iso(r["created"])}


async def notes(request):
    uid = w.user_of(request)
    q = request.query.get("q", "").strip().lower()[:100]
    with ab.db() as con:
        if q:
            rows = con.execute("SELECT * FROM ugu_notes WHERE owner_id=? AND (ulower(title) LIKE ? OR ulower(body) LIKE ?)"
                               " ORDER BY pinned DESC, id DESC LIMIT 200", (uid, f"%{q}%", f"%{q}%")).fetchall()
        else:
            rows = con.execute("SELECT * FROM ugu_notes WHERE owner_id=? ORDER BY pinned DESC, id DESC LIMIT 200",
                               (uid,)).fetchall()
    return w.reply({"items": [note_json(r) for r in rows]})


def note_fields(data):
    title = text_of(data, "title", TEXT_MAX["title"], required=False)
    body = text_of(data, "body", TEXT_MAX["body"], required=False)
    if not title and not body:
        raise bad("пустая заметка")
    color = data.get("color", "none")
    return title or body.split("\n")[0][:60], body, color if color in COLORS else "none"


async def add_note(request):
    import tiers
    uid = w.user_of(request)
    title, body, color = note_fields(await body_json(request))
    ok, tier, cap = tiers.room(uid, "notes")
    if not ok:
        raise web.HTTPPaymentRequired(text=f"На {tiers.NAMES[tier]} не больше {cap} заметок", headers=w.HEADERS)
    with ab.db() as con:
        cur = con.execute("INSERT INTO ugu_notes (owner_id, title, body, created, color) VALUES (?,?,?,?,?)",
                          (uid, title, body, iso(now()), color))
        r = con.execute("SELECT * FROM ugu_notes WHERE id=?", (cur.lastrowid,)).fetchone()
    return w.reply(note_json(r))


def own_note(con, uid, nid):
    r = con.execute("SELECT * FROM ugu_notes WHERE id=? AND owner_id=?", (nid, uid)).fetchone()
    if not r:
        raise web.HTTPNotFound(text="нет такой заметки", headers=w.HEADERS)
    return r


async def put_note(request):
    uid = w.user_of(request)
    nid = path_id(request)
    title, body, color = note_fields(await body_json(request))
    with ab.db() as con:
        own_note(con, uid, nid)
        con.execute("UPDATE ugu_notes SET title=?, body=?, color=? WHERE id=?", (title, body, color, nid))
        r = own_note(con, uid, nid)
    return w.reply(note_json(r))


async def del_note(request):
    uid = w.user_of(request)
    nid = path_id(request)
    with ab.db() as con:
        own_note(con, uid, nid)
        con.execute("DELETE FROM ugu_notes WHERE id=?", (nid,))
    return w.reply({"ok": True})


async def pin_note(request):
    uid = w.user_of(request)
    nid = path_id(request)
    with ab.db() as con:
        r = own_note(con, uid, nid)
        con.execute("UPDATE ugu_notes SET pinned=? WHERE id=?", (int(not r["pinned"]), nid))
    return w.reply({"id": nid, "pinned": not r["pinned"]})


# ---------- архив ----------

async def chats(request):
    uid = w.user_of(request)
    with ab.db() as con:
        rows = con.execute(
            "SELECT m.chat_id, m.chat_title, m.date, m.text, m.media_type, x.del FROM messages m JOIN ("
            " SELECT chat_id, MAX(date) d, SUM(deleted) del FROM messages WHERE owner_id=? GROUP BY chat_id) x"
            " ON x.chat_id=m.chat_id AND x.d=m.date WHERE m.owner_id=? GROUP BY m.chat_id ORDER BY m.date DESC LIMIT 100",
            (uid, uid)).fetchall()
    return w.reply({"items": [{"id": r["chat_id"], "name": r["chat_title"] or "?", "ts": t_iso(r["date"]),
                               "last": (r["text"] or (f"[{r['media_type']}]" if r["media_type"] else ""))[:80],
                               "deleted": r["del"] or 0} for r in rows]})


async def days(request):
    uid = w.user_of(request)
    chat = w.int_arg(request, "chat")
    with ab.db() as con:
        rows = con.execute("SELECT substr(date,1,10) AS d, COUNT(*) AS n, SUM(deleted) AS del FROM messages"
                           " WHERE owner_id=? AND chat_id=? GROUP BY d ORDER BY d DESC LIMIT 120", (uid, chat)).fetchall()
    return w.reply({"items": [{"day": r["d"], "count": r["n"], "deleted": r["del"] or 0} for r in rows]})


def msg_json(r, uid, was=None):
    media = None
    if r["media_type"] in VOICE_KINDS:
        media = {"kind": "voice", "id": r["message_id"], "dur": ""}
    elif r["store_kind"] == "photo" and r["store_file_id"]:
        media = {"kind": "photo", "id": r["message_id"]}
    text = r["text"] or ("" if media else (f"[{r['media_type']}]" if r["media_type"] else ""))
    return {"id": r["message_id"], "from": "me" if r["sender_id"] == uid else "them", "name": r["sender_name"] or "",
            "text": text, "time": (r["date"] or "")[11:16],
            "deleted": ((r["deleted_at"] or "")[11:16] or "?") if r["deleted"] else None,
            "was": was, "media": media}


async def messages(request):
    uid = w.user_of(request)
    chat = w.int_arg(request, "chat")
    day = request.query.get("day", "")
    if day and not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        raise bad("плохой день")
    with ab.db() as con:
        if not day:
            last = con.execute("SELECT MAX(date) FROM messages WHERE owner_id=? AND chat_id=?", (uid, chat)).fetchone()[0]
            day = (last or "")[:10]
        rows = con.execute("SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND substr(date,1,10)=?"
                           " ORDER BY date, message_id LIMIT 500", (uid, chat, day)).fetchall()
        was = w.first_versions(con, uid, chat, [r["message_id"] for r in rows if r["edited"]])
    return w.reply({"day": day, "items": [msg_json(r, uid, was.get(r["message_id"])) for r in rows]})


async def search(request):
    uid = w.user_of(request)
    throttle(uid, "search", 60)
    q = request.query.get("q", "").strip()[:100]
    only_del = request.query.get("deleted") == "1"
    only_media = request.query.get("media") == "1"
    if len(q) < 2 and not (only_del or only_media):
        return w.reply({"items": []})
    sql, args = "SELECT * FROM messages WHERE owner_id=?", [uid]
    if len(q) >= 2:
        sql += " AND ulower(text) LIKE ?"
        args.append(f"%{q.lower()}%")
    if only_del:
        sql += " AND deleted=1"
    if only_media:
        sql += " AND media_type IS NOT NULL"
    with ab.db() as con:
        rows = con.execute(sql + " ORDER BY date DESC LIMIT 60", args).fetchall()
    return w.reply({"items": [{**msg_json(r, uid), "chat": r["chat_id"], "chat_name": r["chat_title"] or "?",
                               "day": (r["date"] or "")[:10], "text": (msg_json(r, uid)["text"] or "")[:300]} for r in rows]})


# ---------- Угу: вопросы, картинки, камера ----------

def as_html(text):
    import ugu
    m = ugu.IMG_RX.search(text or "")
    img = m.group(1) if m else ""
    return ugu.deco(ugu.IMG_RX.sub("", text or ""), custom=False), img


async def ask(request):
    import ugu
    uid = w.user_of(request)
    throttle(uid, "ask", 30)
    data = await body_json(request)
    q = text_of(data, "q", TEXT_MAX["q"])
    kind = data.get("kind") if data.get("kind") in ugu.LABELS else None
    chat, title = data.get("chat"), ""
    if isinstance(chat, int) and ugu.has_chat(uid, chat):
        with ab.db() as con:
            r = con.execute("SELECT MAX(chat_title) FROM messages WHERE owner_id=? AND chat_id=?", (uid, chat)).fetchone()
        title = r[0] or ""
    else:
        chat = None
    if kind and not chat:
        await ugu.remember(uid, q, kind)
    ans = await ugu.brain(ugu.Ctx(uid, q, chat_id=chat, chat_title=title, kind=kind, can_ask=not kind))
    text, img = as_html(ans.private or ans.public)
    images = [{"url": u, "thumb": th or u} for u, th, *_ in ans.images] if ans.images else []
    if img:
        images.insert(0, {"url": img, "thumb": img})
    return w.reply({"html": text, "images": images,
                    "choices": [{"kind": k, "label": ugu.LABELS.get(k, k)} for k in ans.choices]})


async def images(request):
    import websearch
    uid = w.user_of(request)
    throttle(uid, "images", 30)
    q = request.query.get("q", "").strip()[:100]
    offset = max(0, min(w.int_arg(request, "offset", 0), 600))
    if not q:
        return w.reply({"items": [], "next": None})
    found = await websearch.images(q, 30, offset)
    return w.reply({"items": [{"url": u, "thumb": th or u} for u, th, *_ in found],
                    "next": offset + 30 if len(found) >= 10 else None})


async def photo(request):
    import tiers
    import ugu
    uid = w.user_of(request)
    throttle(uid, "photo", 12)
    if not request.content_type.startswith("multipart/"):
        raise bad("нужно фото")
    reader = await request.multipart()
    action, text, path = "describe", "", None
    ab.TMP.mkdir(parents=True, exist_ok=True)
    try:
        async for part in reader:
            if part.name == "action":
                action = (await part.text())[:20]
            elif part.name == "text":
                text = (await part.text())[:120]
            elif part.name == "file":
                path = ab.TMP / f"app_{uid}_{int(time.time() * 1000)}.jpg"
                size = 0
                with open(path, "wb") as f:
                    while chunk := await part.read_chunk(65536):
                        size += len(chunk)
                        if size > PHOTO_MAX:
                            raise web.HTTPRequestEntityTooLarge(max_size=PHOTO_MAX, actual_size=size, headers=w.HEADERS)
                        f.write(chunk)
        if not path or not path.stat().st_size:
            raise bad("нужно фото")
        if action not in FX_KINDS and action not in ("describe", "product"):
            raise bad("плохое действие")
        key = "fx" if action in FX_KINDS else "photo"
        ok, tier, cap = tiers.use(uid, key)
        if not ok:
            return w.reply({"html": as_html(tiers.limit_text(key, tier, cap))[0]})
        if action in FX_KINDS:
            data = await ugu.fx_file(path, FX_KINDS[action], text)
            if not data:
                return w.reply({"html": "😔 Эффект не получился, попробуй другое фото."})
            return web.Response(body=data, headers={**w.HEADERS, "Content-Type": "image/jpeg", "Cache-Control": "no-store"})
        out = await (ugu.product_file(path, uid) if action == "product" else ugu.describe_file(path))
        return w.reply({"html": as_html(out)[0]})
    finally:
        if path:
            path.unlink(missing_ok=True)


# ---------- тариф и партнёрка ----------

async def tariff_buy(request):
    import tiers
    uid = w.user_of(request)
    data = await body_json(request)
    tier, period = data.get("tier"), data.get("period", "month")
    if tier not in tiers.STARS or period not in ("month", "year"):
        raise bad("нет такого тарифа")
    bot = ab.bot_by("ugu", request.app["bot"])
    try:
        link = await tiers.invoice_link(bot, uid, tier, period)
    except Exception as e:
        ab.log.warning("счёт не создан: %s", e)
        raise web.HTTPServiceUnavailable(text="Telegram не выдал счёт, попробуй ещё раз", headers=w.HEADERS)
    return w.reply({"invoice_link": link, "stars": tiers.price(tier, period)})


async def partner(request):
    import tiers
    import ugu
    uid = w.user_of(request)
    return w.reply(tiers.partner_view(uid, ugu.UGU.get("username") or "ugu_ai"))


# ---------- статика ----------

async def index(request):
    return web.FileResponse(ROOT / "index.html", headers={**w.HEADERS, "Cache-Control": "no-cache"})


async def static(request):
    rel = request.match_info["path"]
    target = (ROOT / rel).resolve()
    if ROOT.resolve() not in target.parents or not target.is_file() or "shots" in target.relative_to(ROOT.resolve()).parts:
        raise web.HTTPNotFound(text="нет", headers=w.HEADERS)
    return web.FileResponse(target, headers={**w.HEADERS, "Cache-Control": "no-cache"})


def gzip_assets():
    """Сжатые копии js/css/json рядом с оригиналом: aiohttp сам отдаёт .gz, на медленной связи апп грузится в разы быстрее."""
    import gzip
    for f in ROOT.rglob("*"):
        if f.suffix in (".js", ".css", ".html", ".json") and "shots" not in f.parts:
            gz = f.with_name(f.name + ".gz")
            if not gz.exists() or gz.stat().st_mtime < f.stat().st_mtime:
                gz.write_bytes(gzip.compress(f.read_bytes(), 9))


def setup(app):
    init_db()
    try:
        gzip_assets()
    except OSError as e:
        ab.log.warning("мини-апп: не сжал файлы: %s", e)
    r = app.router
    r.add_get("/u", lambda request: web.HTTPFound("/u/"))
    r.add_get("/u/", index)
    r.add_post("/u/api/login", login)
    r.add_get("/u/api/me", me)
    r.add_put("/u/api/settings", put_settings)
    r.add_delete("/u/api/me/data", wipe)
    r.add_get("/u/api/today", today)
    r.add_get("/u/api/plans", plans)
    r.add_post("/u/api/plans/remind", add_remind)
    r.add_post("/u/api/plans/{id}/snooze", snooze)
    r.add_post("/u/api/plans/{id}/done", plan_done)
    r.add_delete("/u/api/plans/{id}", plan_delete)
    r.add_post("/u/api/tasks", add_task)
    r.add_post("/u/api/tasks/{id}/toggle", toggle_task)
    r.add_post("/u/api/busy", busy_on)
    r.add_delete("/u/api/busy", busy_off)
    r.add_get("/u/api/notes", notes)
    r.add_post("/u/api/notes", add_note)
    r.add_put("/u/api/notes/{id}", put_note)
    r.add_delete("/u/api/notes/{id}", del_note)
    r.add_post("/u/api/notes/{id}/pin", pin_note)
    r.add_get("/u/api/chats", chats)
    r.add_get("/u/api/days", days)
    r.add_get("/u/api/messages", messages)
    r.add_get("/u/api/search", search)
    r.add_get("/u/api/media", w.media)
    r.add_post("/u/api/ask", ask)
    r.add_get("/u/api/images", images)
    r.add_post("/u/api/photo", photo)
    r.add_post("/u/api/tariff/buy", tariff_buy)
    r.add_get("/u/api/partner", partner)
    r.add_get("/u/{path:.+}", static)
