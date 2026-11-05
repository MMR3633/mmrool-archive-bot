import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import ReplyParameters, BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import archive_bot as ab
import llm
from textutil import birthday_in, match_score, promises, stems, summary
from timeparse import MSK, fmt, parse_duration, parse_when

log = logging.getLogger("archive.assistant")
router = Router()

CMD_RX = re.compile(r"^\s*(?:!|бот[,:]?\s+)\s*(напомни(?:ть)?|напоминание|обещания|пересказ|выгрузи|выгрузка|найди|текст|гс)\b(.*)$",
                    re.I | re.S)
VOICE_TRIGGERS = {"т", "тт", "текст", "войс", "voice"}
LONG_VOICE = 180
TASK_TRIGGERS = {"+задача", "+ задача", "+з", "+ з", "+задачу", "+task"}
SPAM_EVERY = 10
SPAM_MAX = 20
VOICE_SEM = asyncio.Semaphore(1)
WHISPER = {"model": None, "broken": False}


def init_db():
    with ab.db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, title TEXT, due TEXT, status TEXT DEFAULT 'active',
            ping30 INTEGER DEFAULT 0, ping5 INTEGER DEFAULT 0, spam_count INTEGER DEFAULT 0, last_spam TEXT,
            created TEXT, context TEXT);
        CREATE TABLE IF NOT EXISTS reminder_msgs (reminder_id INTEGER, message_id INTEGER, spam INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, text TEXT, who TEXT, chat_title TEXT,
            created TEXT, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS busy (owner_id INTEGER PRIMARY KEY, until TEXT, text TEXT, started TEXT);
        CREATE TABLE IF NOT EXISTS busy_hits (
            owner_id INTEGER, chat_id INTEGER, title TEXT, count INTEGER DEFAULT 0, replied INTEGER DEFAULT 0,
            PRIMARY KEY (owner_id, chat_id));
        CREATE TABLE IF NOT EXISTS birthdays (
            owner_id INTEGER, person_id INTEGER, name TEXT, day INTEGER, month INTEGER, source TEXT, last_note TEXT,
            PRIMARY KEY (owner_id, person_id));
        CREATE TABLE IF NOT EXISTS assistant_settings (
            owner_id INTEGER PRIMARY KEY, voice INTEGER DEFAULT 1, digest INTEGER DEFAULT 1, last_digest TEXT);
        CREATE TABLE IF NOT EXISTS pending (owner_id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS assistant_meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        if not con.execute("SELECT 1 FROM assistant_meta WHERE key='voice_default_v9'").fetchone():
            owners = {ab.OWNER_ID} | {r[0] for r in con.execute("SELECT DISTINCT user_id FROM connections")}
            for o in owners:
                if o:
                    con.execute("INSERT OR IGNORE INTO assistant_settings (owner_id, voice) VALUES (?, 1)", (o,))
            con.execute("INSERT INTO assistant_meta VALUES ('voice_default_v9', '1')")
        if not con.execute("SELECT 1 FROM assistant_meta WHERE key='voice_default_v10'").fetchone():
            con.execute("UPDATE assistant_settings SET voice=0 WHERE owner_id<>?", (ab.OWNER_ID,))
            con.execute("INSERT INTO assistant_meta VALUES ('voice_default_v10', '1')")


def now():
    return datetime.now(MSK)


def iso(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
                                                 for row in rows])


async def send(bot: Bot, chat_id, text, keyboard=None):
    for attempt in range(4):
        try:
            return await bot.send_message(chat_id, text, reply_markup=keyboard, disable_web_page_preview=True)
        except Exception as e:
            if not ab.is_network(e):
                log.warning("не отправил: %s", e)
                break
            await asyncio.sleep(3)
    ab.notify(chat_id, text)
    return None


async def drop(bot: Bot, chat_id, ids):
    ids = [i for i in ids if i]
    for i in range(0, len(ids), 100):
        for attempt in range(3):
            try:
                await bot.delete_messages(chat_id, ids[i:i + 100])
                break
            except Exception as e:
                if not ab.is_network(e):
                    log.warning("не удалил сообщения: %s", e)
                    break
                await asyncio.sleep(2)


def setting(owner, key):
    with ab.db() as con:
        row = con.execute(f"SELECT {key} FROM assistant_settings WHERE owner_id=?", (owner,)).fetchone()
    if row is None:
        return 0 if key == "voice" else 1
    return row[0]


def set_setting(owner, key, value):
    with ab.db() as con:
        con.execute("INSERT OR IGNORE INTO assistant_settings (owner_id, voice) VALUES (?, 0)", (owner,))
        con.execute(f"UPDATE assistant_settings SET {key}=? WHERE owner_id=?", (value, owner))


def is_owner(msg_or_call):
    user = msg_or_call.from_user
    return bool(user and ab.owner_has_archive(user.id))


# ---------- напоминания ----------

REMIND_WORDS = re.compile(r"^(?:напомни(?:ть)?|напоминание)\s*(?:мне\s*)?(?:,\s*)?(?:что\s+|про\s+|о\s+)?", re.I)


def clean_title(text):
    t = REMIND_WORDS.sub("", text.strip())
    return re.sub(r"\s+", " ", t).strip(" ,.:;-") or ""


async def create_reminder(bot: Bot, owner, text, context=""):
    title = clean_title(text)
    when, rest, vague = parse_when(title)
    title = clean_title(rest)
    if when is None and llm.enabled():
        data = await llm.ask_json(
            f"Сейчас {iso(now())} (Москва). Фраза: «{text}». Верни JSON {{\"when\": \"YYYY-MM-DD HH:MM\" или null, "
            f"\"title\": короткое название}}.", "Ты разбираешь напоминания на русском.")
        if data and data.get("when"):
            try:
                when = datetime.strptime(data["when"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK)
                title = data.get("title") or title
            except ValueError:
                when = None
    if not title:
        title = "Напоминание" + (f" ({context})" if context else "")
    if when is None or when <= now():
        with ab.db() as con:
            con.execute("INSERT OR REPLACE INTO pending VALUES (?, 'reminder', ?, ?)",
                        (owner, json.dumps({"title": title, "context": context}, ensure_ascii=False), iso(now())))
        await send(bot, owner, f"Во сколько напомнить «{html.escape(title)}»? Напиши время "
                               f"(например «18:00», «через 20 минут», «завтра в 9») или выбери:",
                   kb([("через 30 мин", "rq:30"), ("через 1 ч", "rq:60"), ("через 3 ч", "rq:180")],
                      [("сегодня 19:00", "rq:t19"), ("завтра 9:00", "rq:m9"), ("отмена", "rq:x")]))
        return None
    return await add_reminder(bot, owner, title, when, context, vague)


async def add_reminder(bot: Bot, owner, title, when, context="", vague=False):
    left = when - now()
    with ab.db() as con:
        cur = con.execute("INSERT INTO reminders (owner_id, title, due, created, context, ping30, ping5)"
                          " VALUES (?,?,?,?,?,?,?)",
                          (owner, title, iso(when), iso(now()), context,
                           int(left <= timedelta(minutes=31)), int(left <= timedelta(minutes=6))))
        rid = cur.lastrowid
    note = " Время не указал, ставлю на 9:00." if vague else ""
    await send(bot, owner, f"⏰ Напомню: «{html.escape(title)}» {fmt(when)}.{note}\n"
                           f"Предупрежу за 30 и за 5 минут, а в последнюю минуту буду долбить, пока не нажмёшь «Я помню».",
               kb([("Отменить", f"rem:cancel:{rid}")]))
    return rid


async def reminder_tick(bot: Bot, t=None):
    t = t or now()
    with ab.db() as con:
        rows = con.execute("SELECT * FROM reminders WHERE status='active'").fetchall()
    for r in rows:
        due = parse_iso(r["due"])
        left = due - t
        title = html.escape(r["title"])
        if not r["ping30"] and left <= timedelta(minutes=30):
            msg = await send(bot, r["owner_id"], f"⏰ Через 30 минут: {title} ({due.strftime('%H:%M')})")
            with ab.db() as con:
                con.execute("UPDATE reminders SET ping30=1 WHERE id=?", (r["id"],))
                if msg:
                    con.execute("INSERT INTO reminder_msgs VALUES (?,?,0)", (r["id"], msg.message_id))
        if not r["ping5"] and left <= timedelta(minutes=5):
            msg = await send(bot, r["owner_id"], f"⏰ Через 5 минут: {title} ({due.strftime('%H:%M')})")
            with ab.db() as con:
                con.execute("UPDATE reminders SET ping5=1 WHERE id=?", (r["id"],))
                if msg:
                    con.execute("INSERT INTO reminder_msgs VALUES (?,?,0)", (r["id"], msg.message_id))
        if left <= timedelta(seconds=60):
            last = parse_iso(r["last_spam"]) if r["last_spam"] else None
            if r["spam_count"] >= SPAM_MAX:
                if t - due > timedelta(minutes=2):
                    with ab.db() as con:
                        con.execute("UPDATE reminders SET status='missed' WHERE id=?", (r["id"],))
                continue
            if last and (t - last).total_seconds() < SPAM_EVERY - 0.5:
                continue
            bell = "🔔" * (1 + r["spam_count"] % 3)
            msg = await send(bot, r["owner_id"], f"{bell} {title} в {due.strftime('%H:%M')}!",
                             kb([("✅ Я помню", f"rem:ack:{r['id']}")]))
            with ab.db() as con:
                con.execute("UPDATE reminders SET spam_count=spam_count+1, last_spam=? WHERE id=?", (iso(t), r["id"]))
                if msg:
                    con.execute("INSERT INTO reminder_msgs VALUES (?,?,1)", (r["id"], msg.message_id))


async def reminder_loop(bot: Bot):
    while True:
        try:
            await reminder_tick(bot)
        except Exception as e:
            log.warning("напоминания: %s", e)
        await asyncio.sleep(2)


@router.callback_query(F.data.startswith("rem:"))
async def cb_reminder(call: CallbackQuery, bot: Bot):
    _, action, rid = call.data.split(":")
    owner = call.from_user.id
    with ab.db() as con:
        r = con.execute("SELECT * FROM reminders WHERE id=? AND owner_id=?", (int(rid), owner)).fetchone()
        ids = [x["message_id"] for x in con.execute("SELECT message_id FROM reminder_msgs WHERE reminder_id=?", (int(rid),))]
    if not r:
        await ab.safe_ack(call, "Напоминание не найдено")
        return
    due = parse_iso(r["due"])
    if action == "ack":
        with ab.db() as con:
            con.execute("UPDATE reminders SET status='done' WHERE id=?", (r["id"],))
            con.execute("DELETE FROM reminder_msgs WHERE reminder_id=?", (r["id"],))
        await drop(bot, owner, ids)
        await send(bot, owner, f"✅ {html.escape(r['title'])} в {due.strftime('%H:%M')}")
        await ab.safe_ack(call, "Отлично, не забудь")
    elif action == "cancel":
        with ab.db() as con:
            con.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (r["id"],))
            con.execute("DELETE FROM reminder_msgs WHERE reminder_id=?", (r["id"],))
        await drop(bot, owner, ids)
        await ab.safe_edit(call, f"Отменил: «{html.escape(r['title'])}» {fmt(due)}", None)
        await ab.safe_ack(call, "Отменено")


@router.callback_query(F.data.startswith("rq:"))
async def cb_quick_time(call: CallbackQuery, bot: Bot):
    owner = call.from_user.id
    code = call.data.split(":")[1]
    with ab.db() as con:
        p = con.execute("SELECT * FROM pending WHERE owner_id=? AND kind='reminder'", (owner,)).fetchone()
        con.execute("DELETE FROM pending WHERE owner_id=?", (owner,))
    if not p or code == "x":
        await ab.safe_edit(call, "Хорошо, не напоминаю.", None)
        await ab.safe_ack(call)
        return
    data = json.loads(p["payload"])
    when = quick_time(code)
    await ab.safe_ack(call)
    await ab.safe_edit(call, f"Ставлю «{html.escape(data['title'])}» {fmt(when)}", None)
    await add_reminder(bot, owner, data["title"], when, data.get("context", ""))


def quick_time(code, t=None):
    t = t or now()
    if code.isdigit():
        return (t + timedelta(minutes=int(code))).replace(second=0, microsecond=0)
    if code == "t19":
        when = t.replace(hour=19, minute=0, second=0, microsecond=0)
        return when if when > t else when + timedelta(days=1)
    return (t + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)


@router.message(Command("remind"))
async def cmd_remind(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    text = (msg.text or "").partition(" ")[2].strip()
    if not text:
        await ab.answer(msg, "Напиши так: /remind 18:00 созвон, или /remind через 20 минут позвонить маме")
        return
    await create_reminder(bot, msg.from_user.id, text)


@router.message(Command("reminders"))
async def cmd_reminders(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    with ab.db() as con:
        rows = con.execute("SELECT * FROM reminders WHERE owner_id=? AND status='active' ORDER BY due",
                           (msg.from_user.id,)).fetchall()
    if not rows:
        await ab.answer(msg, "Активных напоминаний нет. Поставить: /remind 18:00 созвон")
        return
    for r in rows[:20]:
        await send(bot, msg.chat.id, f"⏰ {html.escape(r['title'])} · {fmt(parse_iso(r['due']))}",
                   kb([("Отменить", f"rem:cancel:{r['id']}")]))
    if len(rows) > 20:
        await send(bot, msg.chat.id, f"Показал 20 ближайших из {len(rows)}.")


# ---------- задачи ----------

async def add_task(bot: Bot, owner, src: Message):
    label = ab.media_of(src)[0]
    text = ab.body_of(src) or (f"[{label}]" if label else "(пусто)")
    who = ab.person(src.from_user)
    with ab.db() as con:
        cur = con.execute("INSERT INTO tasks (owner_id, text, who, chat_title, created) VALUES (?,?,?,?,?)",
                          (owner, text, who, ab.chat_title(src.chat), iso(now())))
        tid = cur.lastrowid
    await send(bot, owner, f"📝 Задача из чата с {html.escape(ab.chat_title(src.chat))}:\n{html.escape(text[:600])}",
               task_kb(tid))
    return tid


async def add_task_text(bot: Bot, owner, text, chat_title=""):
    with ab.db() as con:
        cur = con.execute("INSERT INTO tasks (owner_id, text, who, chat_title, created) VALUES (?,?,?,?,?)",
                          (owner, text, "", chat_title, iso(now())))
        tid = cur.lastrowid
    where = f" (чат с {html.escape(chat_title)})" if chat_title else ""
    await send(bot, owner, f"📝 Задача{where}:\n{html.escape(text[:600])}", task_kb(tid))
    return tid


def task_kb(tid):
    return kb([("✅ Готово", f"task:done:{tid}"), ("⏰ Напомнить", f"task:rem:{tid}")])


@router.message(Command("tasks"))
async def cmd_tasks(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    with ab.db() as con:
        rows = con.execute("SELECT * FROM tasks WHERE owner_id=? AND done=0 ORDER BY id", (msg.from_user.id,)).fetchall()
    if not rows:
        await ab.answer(msg, "Открытых задач нет. Добавить: ответь на любое сообщение в чате «+задача».")
        return
    for t in rows[:30]:
        await send(bot, msg.chat.id, f"✅ {html.escape(t['text'][:500])}\n<i>{html.escape(t['chat_title'] or '')}, "
                                     f"{t['created'][5:16]}</i>", task_kb(t["id"]))
    if len(rows) > 30:
        await send(bot, msg.chat.id, f"Показал первые 30 из {len(rows)}. Закрой выполненные, и появятся остальные.")


@router.callback_query(F.data.startswith("task:"))
async def cb_task(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    action, tid = parts[1], int(parts[2])
    owner = call.from_user.id
    with ab.db() as con:
        t = con.execute("SELECT * FROM tasks WHERE id=? AND owner_id=?", (tid, owner)).fetchone()
    if not t:
        await ab.safe_ack(call, "Задача не найдена")
        return
    if action == "done":
        with ab.db() as con:
            con.execute("UPDATE tasks SET done=1 WHERE id=?", (tid,))
        await ab.safe_edit(call, f"✅ <s>{html.escape(t['text'][:500])}</s>", None)
        await ab.safe_ack(call, "Готово")
    elif action == "rem":
        await ab.safe_edit(call, f"📝 {html.escape(t['text'][:500])}\nКогда напомнить?",
                           kb([("через 1 ч", f"task:at:{tid}:60"), ("сегодня 19:00", f"task:at:{tid}:t19"),
                               ("завтра 9:00", f"task:at:{tid}:m9")]))
        await ab.safe_ack(call)
    elif action == "at":
        when = quick_time(parts[3])
        await ab.safe_edit(call, f"📝 {html.escape(t['text'][:500])}", task_kb(tid))
        await ab.safe_ack(call, f"Напомню {fmt(when)}")
        await add_reminder(bot, owner, f"Задача: {t['text'][:80]}", when, t["chat_title"] or "")


# ---------- занят ----------

@router.message(Command("busy"))
async def cmd_busy(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    owner = msg.from_user.id
    args = (msg.text or "").partition(" ")[2].strip()
    if args.lower() in ("off", "выкл", "стоп"):
        await finish_busy(bot, owner)
        return
    await ab.answer(msg, set_busy(owner, args))


def set_busy(owner, args, default_hours=1):
    until, text = parse_duration(args) if args else (None, "")
    if until is None:
        until, text = now() + timedelta(hours=default_hours), args
    text = text or "Сейчас занят, отвечу чуть позже."
    with ab.db() as con:
        con.execute("INSERT OR REPLACE INTO busy VALUES (?,?,?,?)", (owner, iso(until), text, iso(now())))
        con.execute("DELETE FROM busy_hits WHERE owner_id=?", (owner,))
    till = until.astimezone(MSK)
    till_s = till.strftime("%H:%M") if till.date() == now().astimezone(MSK).date() else till.strftime("%d.%m %H:%M")
    return (f"🔕 До {till_s} отвечаю за тебя в личке (каждому один раз):\n"
            f"«{html.escape(text)}»\nВыключить раньше: /busy off")


async def busy_reply(bot: Bot, owner, msg: Message):
    with ab.db() as con:
        b = con.execute("SELECT * FROM busy WHERE owner_id=?", (owner,)).fetchone()
        if not b or parse_iso(b["until"]) <= now():
            return False
        con.execute("INSERT INTO busy_hits (owner_id, chat_id, title, count) VALUES (?,?,?,1)"
                    " ON CONFLICT(owner_id, chat_id) DO UPDATE SET count=count+1",
                    (owner, msg.chat.id, ab.chat_title(msg.chat)))
        hit = con.execute("SELECT replied FROM busy_hits WHERE owner_id=? AND chat_id=?", (owner, msg.chat.id)).fetchone()
    if hit["replied"]:
        return False
    for attempt in range(3):
        try:
            await bot.send_message(msg.chat.id, b["text"], business_connection_id=msg.business_connection_id)
            with ab.db() as con:
                con.execute("UPDATE busy_hits SET replied=1 WHERE owner_id=? AND chat_id=?", (owner, msg.chat.id))
            return True
        except Exception as e:
            if not ab.is_network(e):
                log.warning("автоответ не ушёл: %s", e)
                return False
            await asyncio.sleep(2)
    return False


async def finish_busy(bot: Bot, owner):
    with ab.db() as con:
        b = con.execute("SELECT * FROM busy WHERE owner_id=?", (owner,)).fetchone()
        hits = con.execute("SELECT * FROM busy_hits WHERE owner_id=? ORDER BY count DESC", (owner,)).fetchall()
        con.execute("DELETE FROM busy WHERE owner_id=?", (owner,))
        con.execute("DELETE FROM busy_hits WHERE owner_id=?", (owner,))
    if not b:
        await send(bot, owner, "Режим «занят» и так выключен.")
        return
    if not hits:
        await send(bot, owner, "🔔 Режим «занят» выключен. Пока тебя не было, никто не писал.")
        return
    lines = [f"• {html.escape(h['title'])}: {h['count']} сообщ." for h in hits]
    await send(bot, owner, "🔔 Режим «занят» выключен. Пока тебя не было, писали:\n" + "\n".join(lines))


async def busy_tick(bot: Bot):
    with ab.db() as con:
        rows = con.execute("SELECT owner_id, until FROM busy").fetchall()
    for r in rows:
        if parse_iso(r["until"]) <= now():
            await finish_busy(bot, r["owner_id"])


# ---------- дни рождения ----------

def remember_birthday(owner, msg: Message):
    found = birthday_in(ab.body_of(msg))
    if not found or not msg.from_user:
        return None
    day, month = found
    with ab.db() as con:
        con.execute("INSERT OR REPLACE INTO birthdays (owner_id, person_id, name, day, month, source, last_note)"
                    " VALUES (?,?,?,?,?,?, (SELECT last_note FROM birthdays WHERE owner_id=? AND person_id=?))",
                    (owner, msg.from_user.id, ab.person(msg.from_user), day, month, ab.body_of(msg)[:200],
                     owner, msg.from_user.id))
    ab.notify(owner, f"🎂 Запомнил: у {html.escape(ab.person(msg.from_user))} день рождения {day:02d}.{month:02d}. "
                     f"Напомню за день и в сам день.")
    return day, month


async def birthday_tick(bot: Bot, t=None):
    t = t or now()
    if t.hour < 10:
        return
    tomorrow = (t + timedelta(days=1)).date()
    with ab.db() as con:
        rows = con.execute("SELECT * FROM birthdays").fetchall()
    for b in rows:
        for kind, d, text in (("pre", tomorrow, "Завтра день рождения у"), ("day", t.date(), "Сегодня день рождения у")):
            if (b["day"], b["month"]) == (d.day, d.month) and b["last_note"] != f"{d.year}-{kind}":
                await send(bot, b["owner_id"], f"🎂 {text} {html.escape(b['name'])}!")
                with ab.db() as con:
                    con.execute("UPDATE birthdays SET last_note=? WHERE owner_id=? AND person_id=?",
                                (f"{d.year}-{kind}", b["owner_id"], b["person_id"]))


@router.message(Command("birthdays"))
async def cmd_birthdays(msg: Message):
    if not is_owner(msg):
        return
    with ab.db() as con:
        rows = con.execute("SELECT * FROM birthdays WHERE owner_id=? ORDER BY month, day", (msg.from_user.id,)).fetchall()
    if not rows:
        await ab.answer(msg, "Пока ни одного дня рождения не поймал. Как только кто-то напишет «у меня др 12 марта», запомню.")
        return
    await ab.answer(msg, "🎂 Дни рождения:\n" + "\n".join(f"{b['day']:02d}.{b['month']:02d} {html.escape(b['name'])}"
                                                         for b in rows))


# ---------- дайджест ----------

def build_digest(owner, t=None):
    t = t or now()
    day = t.strftime("%Y-%m-%d")
    with ab.db() as con:
        deleted = con.execute("SELECT sender_name, COUNT(*) n FROM messages WHERE owner_id=? AND deleted=1 AND deleted_at LIKE ?"
                              " AND (sender_id IS NULL OR sender_id != ?) GROUP BY sender_name ORDER BY n DESC",
                              (owner, day + "%", owner)).fetchall()
        edited = con.execute("SELECT COALESCE(m.sender_name, 'неизвестно') sender_name, COUNT(*) n FROM edits e"
                             " LEFT JOIN messages m ON m.owner_id=e.owner_id AND m.chat_id=e.chat_id AND m.message_id=e.message_id"
                             " WHERE e.owner_id=? AND e.edited_at LIKE ? AND (m.sender_id IS NULL OR m.sender_id != ?)"
                             " GROUP BY m.sender_name ORDER BY n DESC", (owner, day + "%", owner)).fetchall()
        since = (t - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        lasts = con.execute("SELECT m.chat_title, m.sender_id, m.date FROM messages m JOIN ("
                            " SELECT chat_id, MAX(date) d FROM messages WHERE owner_id=? AND chat_id > 0 AND date >= ?"
                            " GROUP BY chat_id) x ON x.chat_id=m.chat_id AND x.d=m.date WHERE m.owner_id=?",
                            (owner, since, owner)).fetchall()
    waiting = [r for r in lasts if r["sender_id"] != owner and parse_iso(r["date"]) <= t - timedelta(hours=3)]
    lines = [f"🌙 Итоги дня, {t.strftime('%d.%m')}"]
    if deleted:
        lines.append("\n🗑 Удалили:\n" + "\n".join(f"• {html.escape(r['sender_name'] or '?')}: {r['n']}" for r in deleted))
    if edited:
        lines.append("\n✏️ Изменили:\n" + "\n".join(f"• {html.escape(r['sender_name'] or '?')}: {r['n']}" for r in edited))
    if waiting:
        lines.append("\n⏳ Ждут ответа больше 3 часов:\n" + "\n".join(
            f"• {html.escape(r['chat_title'] or '?')} (с {r['date'][5:16]})" for r in sorted(waiting, key=lambda r: r["date"])))
    if len(lines) == 1:
        lines.append("Тихо: никто ничего не удалял и не правил, неотвеченных нет.")
    return "\n".join(lines)


async def digest_tick(bot: Bot, t=None):
    t = t or now()
    if t.hour != 21:
        return
    day = t.strftime("%Y-%m-%d")
    with ab.db() as con:
        owners = [r[0] for r in con.execute("SELECT DISTINCT user_id FROM connections WHERE enabled=1")]
    for owner in owners:
        with ab.db() as con:
            con.execute("INSERT OR IGNORE INTO assistant_settings (owner_id, voice) VALUES (?, 0)", (owner,))
            s = con.execute("SELECT digest, last_digest FROM assistant_settings WHERE owner_id=?", (owner,)).fetchone()
        if not s["digest"] or s["last_digest"] == day:
            continue
        set_setting(owner, "last_digest", day)
        ab.notify(owner, build_digest(owner, t))


@router.message(Command("digest"))
async def cmd_digest(msg: Message):
    if not is_owner(msg):
        return
    arg = (msg.text or "").partition(" ")[2].strip().lower()
    owner = msg.from_user.id
    if arg in ("off", "выкл"):
        set_setting(owner, "digest", 0)
        await ab.answer(msg, "Вечерний дайджест выключен. Включить: /digest on")
    elif arg in ("on", "вкл"):
        set_setting(owner, "digest", 1)
        await ab.answer(msg, "Вечерний дайджест включён, приходит в 21:00.")
    else:
        await ab.answer(msg, build_digest(owner))


# ---------- ГС в текст ----------

def _transcribe(path):
    import stt
    return stt.transcribe(path, download_root=str(ab.DATA / "whisper"))


def voice_card(icon, who, when, text):
    words = text.split()
    quote = " ".join(words[:8]) + ("…" if len(words) > 8 else "")
    head = f"📝 {icon} от <b>{html.escape(who)}</b>" + (f", {when}" if when else "")
    if not text:
        return f"{head}\n<i>без слов</i>"
    return f"{head}\n<blockquote>{html.escape(quote)}</blockquote>\n{html.escape(text)}"


CAN_REPLY_HELP = ("Чтобы текст ГС появлялся прямо в чате, разреши мне отвечать: Настройки → Telegram для бизнеса → "
                  "Чат-боты → @mmrool_archive_bot → включи «Отвечать на сообщения». Пока прислал текст сюда.")


async def publish_in_chat(bot: Bot, owner, target, text):
    conn_id, chat_id, reply_id = target
    body = "📝 " + (text or "(без слов)")
    parts = [body[i:i + 4000] for i in range(0, len(body), 4000)]
    for n, part in enumerate(parts):
        for attempt in range(4):
            try:
                await bot.send_message(chat_id, part, business_connection_id=conn_id, parse_mode=None,
                                       disable_web_page_preview=True,
                                       reply_parameters=ReplyParameters(message_id=reply_id,
                                                                        allow_sending_without_reply=True)
                                       if n == 0 and reply_id else None)
                break
            except Exception as e:
                if ab.is_network(e) and attempt < 3:
                    await asyncio.sleep(3)
                    continue
                log.warning("не опубликовал текст ГС в чате: %s", e)
                return False, str(e)
    return True, ""


def no_reply_right(err):
    err = (err or "").lower()
    return any(s in err for s in ("not enough rights", "bot_access_forbidden", "business_peer", "can't reply",
                                  "cant_reply", "forbidden", "not allowed", "rights"))


async def transcribe_file(bot: Bot, owner, file_id, size, ext, name, duration=0, who="", when="", icon="🎤 ГС",
                          target=None):
    if WHISPER["broken"]:
        ab.notify(owner, "📝 Расшифровка ГС сейчас недоступна: на сервере не запустилось распознавание речи.")
        return None
    if duration and duration > LONG_VOICE:
        ab.notify(owner, f"⏳ Расшифровываю {icon} от {html.escape(who)} на {round(duration / 60)} мин…")
    path = await ab.download(bot, name, file_id, size, ext)
    if not path:
        ab.notify(owner, f"📝 Не смог скачать {icon} от {html.escape(who)}, попробуй ещё раз через минуту.")
        return None
    try:
        async with VOICE_SEM:
            text = await asyncio.to_thread(_transcribe, path)
    except ImportError as e:
        WHISPER["broken"] = True
        log.warning("распознавание недоступно: %s", e)
        ab.notify(owner, "📝 Расшифровка ГС сейчас недоступна: на сервере не запустилось распознавание речи.")
        return None
    except Exception as e:
        log.warning("не расшифровал ГС: %s", e)
        ab.notify(owner, f"📝 Не получилось расшифровать {icon} от {html.escape(who)}: {html.escape(str(e))}")
        return None
    finally:
        Path(path).unlink(missing_ok=True)
    if target:
        ok, err = await publish_in_chat(bot, owner, target, text)
        if ok:
            return text
        if no_reply_right(err):
            ab.notify(owner, CAN_REPLY_HELP)
        else:
            ab.notify(owner, f"📝 Не смог показать текст в чате ({html.escape(err[:200])}), прислал сюда.")
    ab.notify(owner, voice_card(icon, who, when, text))
    return text


def msg_when(m: Message):
    try:
        return m.date.astimezone(MSK).strftime("%d.%m %H:%M")
    except Exception:
        return ""


async def voice_to_text(bot: Bot, owner, msg: Message, force=False, target=None):
    if not force and not setting(owner, "voice"):
        return None
    obj = msg.voice or msg.video_note
    if not obj:
        return None
    return await transcribe_file(bot, owner, obj.file_id, obj.file_size, ".ogg" if msg.voice else ".mp4",
                                 f"stt_{msg.chat.id}_{msg.message_id}", getattr(obj, "duration", 0) or 0,
                                 ab.person(msg.from_user), msg_when(msg), "🎤 ГС" if msg.voice else "⭕ Кружок",
                                 target=target)


async def last_voice(bot: Bot, owner, chat_id, conn_id=None):
    with ab.db() as con:
        row = con.execute(
            "SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND media_type IN ('голосовое', 'кружок')"
            " AND (sender_id IS NULL OR sender_id<>?) ORDER BY date DESC, message_id DESC LIMIT 1",
            (owner, chat_id, owner)).fetchone()
    if not row:
        ab.notify(owner, "📝 В этом чате нет ГС от собеседника, которые я успел сохранить.")
        return None
    voice = row["media_type"] == "голосовое"
    file_id = row["store_file_id"] or row["file_id"]
    when = (row["date"] or "")[5:16].replace("-", ".")
    target = (conn_id, chat_id, row["message_id"]) if conn_id else None
    return await transcribe_file(bot, owner, file_id, None, ".ogg" if voice else ".mp4",
                                 f"stt_{chat_id}_{row['message_id']}", 0, row["sender_name"] or "", when,
                                 "🎤 ГС" if voice else "⭕ Кружок", target=target)


@router.message(F.chat.type == "private", F.voice | F.video_note | F.audio)
async def on_private_voice(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    obj = msg.voice or msg.video_note or msg.audio
    ext = ".mp4" if msg.video_note else ".ogg"
    origin = getattr(msg, "forward_origin", None)
    who = getattr(getattr(origin, "sender_user", None), "first_name", None) or getattr(origin, "sender_user_name", None)         or ("пересланное" if origin else "тебя")
    icon = "⭕ Кружок" if msg.video_note else "🎤 ГС"
    await transcribe_file(bot, msg.from_user.id, obj.file_id, obj.file_size, ext,
                          f"stt_pm_{msg.chat.id}_{msg.message_id}", getattr(obj, "duration", 0) or 0,
                          who, msg_when(msg), icon)


@router.message(Command("voice"))
async def cmd_voice(msg: Message):
    if not is_owner(msg):
        return
    arg = (msg.text or "").partition(" ")[2].strip().lower()
    if arg in ("auto", "авто", "on", "вкл"):
        set_setting(msg.from_user.id, "voice", 1)
        await ab.answer(msg, "📝 Режим auto: каждое ГС и кружок собеседника сразу присылаю тебе сюда текстом.\n"
                             "Ответ «т» на ГС в чате тоже работает: текст появится прямо в чате.")
    elif arg in ("off", "выкл"):
        set_setting(msg.from_user.id, "voice", 0)
        await ab.answer(msg, "📝 Режим off: расшифровываю только по запросу. Ответь в чате на ГС словом «т», "
                             "метку сотру, а текст появится в чате ответом на это ГС.")
    else:
        mode = "auto" if setting(msg.from_user.id, "voice") else "off"
        await ab.answer(msg, f"📝 Сейчас режим {mode}.\n"
                             "Ответь в чате на ГС словом «т»: текст появится прямо в чате ответом на ГС.\n"
                             "/voice auto: каждое входящее ГС сразу присылаю сюда текстом.\n"
                             "/voice off: только по «т».")


# ---------- обещания, пересказ, поиск ----------

PERIOD = re.compile(r"за\s+(сегодня|день|сутки|неделю|месяц|(\d+)\s*(дн[ейя]*|день|недел[иья]*|месяц[аев]*))", re.I)


def period_days(text, default=7):
    m = PERIOD.search(text or "")
    if not m:
        return default
    word = m.group(1).lower()
    if word in ("сегодня", "день", "сутки"):
        return 1
    if word == "неделю":
        return 7
    if word == "месяц":
        return 30
    n = int(m.group(2))
    unit = m.group(3).lower()
    return n * (7 if unit.startswith("недел") else 30 if unit.startswith("месяц") else 1)


def chat_ids_for(owner, who):
    who = who.strip().lstrip("@").lower()
    with ab.db() as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT chat_id FROM messages WHERE owner_id=? AND (ulower(chat_title) LIKE ? OR ulower(chat_title) LIKE ?)",
            (owner, f"%(@{who})%", f"{who}%"))]


def chat_rows(owner, chat_ids, days):
    since = (now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    if not chat_ids:
        return []
    marks = ",".join("?" * len(chat_ids))
    with ab.db() as con:
        return [dict(r) for r in con.execute(
            f"SELECT * FROM messages WHERE owner_id=? AND chat_id IN ({marks}) AND date >= ? ORDER BY date",
            (owner, *chat_ids, since))]


async def rows_from_account(who, days):
    if ab.USER is None or not await ab.USER.ready():
        return []
    since = now() - timedelta(days=days)
    try:
        name, owner_name, msgs = await ab.USER.export_dialog(who, since=since, image_budget=0)
    except Exception as e:
        log.warning("не взял переписку из аккаунта: %s", e)
        return []
    return [{"sender_id": ab.OWNER_ID if m["out"] else -1, "sender_name": m["sender"],
             "date": m["date"].astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S"), "text": m["text"],
             "media_type": m["media"], "deleted": 0, "edited": 0} for m in msgs]


async def gather(owner, who=None, chat_ids=None, days=7):
    ids = chat_ids or (chat_ids_for(owner, who) if who else [])
    rows = chat_rows(owner, ids, days)
    if len(rows) < 20 and who and owner == ab.OWNER_ID:
        more = await rows_from_account(who, days)
        if len(more) > len(rows):
            rows = more
    return rows


async def promises_text(owner, rows, title):
    if not rows:
        return f"По чату {html.escape(title)} за этот период сообщений нет."
    if llm.enabled():
        res = await llm.ask("Вот переписка:\n" + llm.transcript(rows, owner) +
                            "\n\nВыпиши все договорённости и обещания: кто, что, к какому сроку. Коротко, списком.",
                            "Ты личный помощник. Пиши по-русски, без длинных тире.")
        if res:
            return f"🤝 Договорённости, {html.escape(title)}:\n{html.escape(res)}"
    found = promises(rows, owner)
    if not found:
        return f"🤝 В чате {html.escape(title)} обещаний и сроков не нашёл."
    lines = [f"• <b>{html.escape(who)}</b>, {d[5:16]}{' · срок: ' + html.escape(dl) if dl else ''}\n  {html.escape(s)}"
             for who, d, s, dl in found[-20:]]
    return f"🤝 Обещания и сроки, {html.escape(title)}:\n" + "\n".join(lines)


async def summary_text(owner, rows, title, days):
    if not rows:
        return f"По чату {html.escape(title)} за {days} дн. сообщений нет."
    if llm.enabled():
        res = await llm.ask("Вот переписка:\n" + llm.transcript(rows, owner) +
                            f"\n\nПерескажи коротко, о чём говорили за последние {days} дн.: главные темы, решения, "
                            f"открытые вопросы. 5-10 пунктов.", "Ты личный помощник. Пиши по-русски, без длинных тире.")
        if res:
            return f"📋 Пересказ, {html.escape(title)}, {days} дн.:\n{html.escape(res)}"
    s = summary(rows, owner)
    media = ", ".join(f"{k}: {v}" for k, v in s["media"].items()) or "нет"
    lines = [f"📋 Пересказ, {html.escape(title)}, {days} дн.",
             f"Сообщений {s['total']} (твоих {s['mine']}, собеседника {s['theirs']}), дней с перепиской {len(s['days'])}.",
             f"Медиа: {media}. Удалено {s['deleted']}, изменено {s['edited']}.",
             f"Частые темы: {html.escape(', '.join(s['top_words'])) or 'нет'}.", "", "Главное:"]
    for r in s["key"]:
        who = "Я" if r["sender_id"] == owner else (r["sender_name"] or "?")
        lines.append(f"• {r['date'][5:16]} {html.escape(who)}: {html.escape((r['text'] or '')[:200])}")
    return "\n".join(lines)


async def find_text(owner, query, chat_ids=None):
    words = stems(query)
    if llm.enabled():
        extra = await llm.ask_json(f"Запрос для поиска по переписке: «{query}». Дай JSON-список из 10 русских слов-синонимов "
                                   f"и связанных слов, которые могут встретиться в нужных сообщениях.")
        if isinstance(extra, list):
            words += stems(" ".join(str(x) for x in extra))
    if not words:
        return "Напиши, что искать: /find где он кидал адрес"
    with ab.db() as con:
        sql = "SELECT * FROM messages WHERE owner_id=? AND text IS NOT NULL AND text != ''"
        args = [owner]
        if chat_ids:
            sql += f" AND chat_id IN ({','.join('?' * len(chat_ids))})"
            args += chat_ids
        rows = con.execute(sql + " ORDER BY date DESC LIMIT 20000", args).fetchall()
    scored = sorted(((match_score(words, r["text"]), r) for r in rows), key=lambda x: (x[0], x[1]["date"]), reverse=True)
    best = [r for s, r in scored if s > 0][:15]
    if not best:
        return "Ничего похожего не нашёл."
    return "🔎 Нашёл:\n\n" + "\n\n".join(
        f"<b>{html.escape(r['chat_title'] or '')}</b> · {html.escape(r['sender_name'] or '')} · {r['date'][5:16]}"
        f"{' 🗑' if r['deleted'] else ''}\n{html.escape(r['text'][:300])}" for r in best)


def who_arg(text):
    m = re.search(r"@?([A-Za-z0-9_]{4,})", text or "")
    return m.group(1) if m else None


@router.message(Command("promises"))
async def cmd_promises(msg: Message):
    if not is_owner(msg):
        return
    args = (msg.text or "").partition(" ")[2]
    who = who_arg(args)
    if not who:
        await ab.answer(msg, "Напиши так: /promises @username [за месяц]")
        return
    days = period_days(args, 30)
    await ab.answer(msg, f"⏳ Собираю договорённости с @{html.escape(who)} за {days} дн…")
    rows = await gather(msg.from_user.id, who, days=days)
    ab.notify(msg.chat.id, await promises_text(msg.from_user.id, rows, "@" + who))


@router.message(Command("summary"))
async def cmd_summary(msg: Message):
    if not is_owner(msg):
        return
    args = (msg.text or "").partition(" ")[2]
    who = who_arg(args)
    if not who:
        await ab.answer(msg, "Напиши так: /summary @username [за неделю]")
        return
    days = period_days(args, 7)
    await ab.answer(msg, f"⏳ Пересказываю переписку с @{html.escape(who)} за {days} дн…")
    rows = await gather(msg.from_user.id, who, days=days)
    ab.notify(msg.chat.id, await summary_text(msg.from_user.id, rows, "@" + who, days))


@router.message(Command("find"))
async def cmd_find(msg: Message):
    if not is_owner(msg):
        return
    ab.notify(msg.chat.id, await find_text(msg.from_user.id, (msg.text or "").partition(" ")[2].strip()))


# ---------- выгрузка ----------

DATE = re.compile(r"\b(с|по)\s+(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", re.I)


def export_args(text):
    since = until = None
    for kw, d, m, y in DATE.findall(text or ""):
        y = int(y) + (2000 if len(y) == 2 else 0)
        dt = datetime(y, int(m), int(d), tzinfo=MSK)
        if kw.lower() == "с":
            since = dt
        else:
            until = dt + timedelta(days=1) - timedelta(seconds=1)
    return since, until


async def run_export(bot: Bot, owner, target, since=None, until=None):
    from exporter import build_html, build_txt
    if owner != ab.OWNER_ID or ab.USER is None or not await ab.USER.ready():
        await send(bot, owner, "Для выгрузки нужен вход в аккаунт: /phone +7XXXXXXXXXX или /login.")
        return
    status = await send(bot, owner, f"⏳ Выгружаю переписку с {html.escape(str(target))}…")

    async def progress(n):
        if status:
            try:
                await bot.edit_message_text(f"⏳ Выгружаю: {n} сообщений…", chat_id=owner, message_id=status.message_id)
            except Exception:
                pass

    try:
        name, owner_name, msgs = await ab.USER.export_dialog(target, since=since, until=until, progress=progress)
    except Exception as e:
        await send(bot, owner, f"Не смог выгрузить {html.escape(str(target))}: {html.escape(str(e))}")
        return
    if not msgs:
        await send(bot, owner, f"С {html.escape(name)} за этот период сообщений нет.")
        return
    period = f"{msgs[0]['date'].astimezone(MSK):%d.%m.%Y} – {msgs[-1]['date'].astimezone(MSK):%d.%m.%Y}".replace(" – ", " по ")
    title = f"Переписка с {name}"
    safe = re.sub(r"[^\w\-]+", "_", name)[:40]
    parts = build_html(msgs, title, owner_name, "с " + period)
    for i, doc in enumerate(parts, 1):
        suffix = f"_часть{i}" if len(parts) > 1 else ""
        await bot.send_document(owner, BufferedInputFile(doc.encode(), f"{safe}{suffix}.html"),
                                caption=f"{title}: {len(msgs)} сообщ.{f' (часть {i} из {len(parts)})' if len(parts) > 1 else ''}",
                                parse_mode=None)
    await bot.send_document(owner, BufferedInputFile(build_txt(msgs, title, owner_name).encode(), f"{safe}.txt"),
                            caption="То же текстом", parse_mode=None)
    if status:
        try:
            await bot.delete_message(owner, status.message_id)
        except Exception:
            pass


@router.message(Command("export"))
async def cmd_export(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    args = (msg.text or "").partition(" ")[2]
    who = re.search(r"@[A-Za-z0-9_]{4,}|\b\d{5,}\b", args)
    if not who:
        await ab.answer(msg, "Напиши так: /export @username [с 01.09.2026] [по 05.11.2026]")
        return
    since, until = export_args(args)
    asyncio.create_task(run_export(bot, msg.from_user.id, who.group(0), since, until))


@router.message(F.chat.type == "private",
                F.text.regexp(r"(?i)^\s*(выгрузи\s+@[A-Za-z0-9_]{4,}|@[A-Za-z0-9_]{4,}\s+выгрузи)"))
async def text_export(msg: Message, bot: Bot):
    if not is_owner(msg):
        return
    who = re.search(r"@[A-Za-z0-9_]{4,}", msg.text).group(0)
    since, until = export_args(msg.text)
    asyncio.create_task(run_export(bot, msg.from_user.id, who, since, until))


# ---------- ответ на вопрос «во сколько» ----------

def has_pending(msg: Message):
    if not msg.from_user or not msg.text or msg.text.startswith("/"):
        return False
    with ab.db() as con:
        return bool(con.execute("SELECT 1 FROM pending WHERE owner_id=?", (msg.from_user.id,)).fetchone())


@router.message(F.chat.type == "private", F.func(has_pending))
async def on_pending_answer(msg: Message, bot: Bot):
    owner = msg.from_user.id
    with ab.db() as con:
        p = con.execute("SELECT * FROM pending WHERE owner_id=?", (owner,)).fetchone()
    data = json.loads(p["payload"])
    when, _, vague = parse_when(msg.text)
    if when is None or when <= now():
        await ab.answer(msg, "Не понял время. Напиши, например: 18:00, через 20 минут, завтра в 9.")
        return
    with ab.db() as con:
        con.execute("DELETE FROM pending WHERE owner_id=?", (owner,))
    await add_reminder(bot, owner, data["title"], when, data.get("context", ""), vague)


# ---------- хук для личных чатов (Telegram для бизнеса) ----------

async def handle_business(msg: Message, bot: Bot, owner, mine):
    text = (msg.text or "").strip()
    if mine and msg.via_bot and msg.via_bot.id == bot.id:
        import inline
        await inline.handle_via(msg, bot, owner)
        return True
    if mine:
        src = msg.reply_to_message
        if src and text.lower() in VOICE_TRIGGERS and (src.voice or src.video_note):
            await ab.remove_trigger(msg, bot, owner)
            asyncio.create_task(voice_to_text(bot, owner, src, force=True,
                                              target=(msg.business_connection_id, msg.chat.id, src.message_id)))
            return True
        if msg.reply_to_message and text.lower() in TASK_TRIGGERS:
            await ab.remove_trigger(msg, bot, owner)
            await add_task(bot, owner, msg.reply_to_message)
            return True
        m = CMD_RX.match(text)
        if m:
            await ab.remove_trigger(msg, bot, owner)
            await chat_command(bot, owner, msg, m.group(1).lower(), m.group(2).strip())
            return True
        return False
    if msg.chat.type == "private":
        await busy_reply(bot, owner, msg)
    remember_birthday(owner, msg)
    if msg.voice or msg.video_note:
        asyncio.create_task(voice_to_text(bot, owner, msg))
    return False


async def chat_command(bot: Bot, owner, msg: Message, cmd, rest):
    title = ab.chat_title(msg.chat)
    if cmd.startswith("напомни") or cmd == "напоминание":
        await create_reminder(bot, owner, rest, f"чат с {title}")
    elif cmd == "обещания":
        rows = await gather(owner, chat_ids=[msg.chat.id], days=period_days(rest, 30))
        if len(rows) < 20 and owner == ab.OWNER_ID:
            more = await rows_from_account(msg.chat.id, period_days(rest, 30))
            rows = more if len(more) > len(rows) else rows
        ab.notify(owner, await promises_text(owner, rows, title))
    elif cmd == "пересказ":
        days = period_days(rest, 7)
        rows = await gather(owner, chat_ids=[msg.chat.id], days=days)
        if len(rows) < 20 and owner == ab.OWNER_ID:
            more = await rows_from_account(msg.chat.id, days)
            rows = more if len(more) > len(rows) else rows
        ab.notify(owner, await summary_text(owner, rows, title, days))
    elif cmd in ("гс", "текст"):
        await last_voice(bot, owner, msg.chat.id, msg.business_connection_id)
    elif cmd.startswith("выгруз"):
        since, until = export_args(rest)
        asyncio.create_task(run_export(bot, owner, msg.chat.id, since, until))
    elif cmd == "найди":
        ab.notify(owner, await find_text(owner, rest, [msg.chat.id]))


HELP = (
    "Что я умею, кроме архива:\n\n"
    "⚡ В любом чате набери @mmrool_archive_bot и выбери действие: 📝 расшифровать ГС, ⏰ напомнить (можно сразу "
    "«@mmrool_archive_bot 18:00 созвон»), ✅ задача, 🔎 найти, 🧾 пересказ, 🤝 что обещали, 📥 выгрузить чат, "
    "💤 занят. Служебное сообщение я сразу удаляю, ответ приходит сюда (текст ГС появляется в самом чате).\n"
    "⏰ /remind 18:00 созвон, напоминание. За 30 и 5 минут предупрежу, в последнюю минуту буду долбить, "
    "пока не нажмёшь «Я помню», потом лишнее сотру. /reminders список.\n"
    "💬 В любом личном чате напиши «!напомни 18:00 созвон» или «бот, напомни завтра в 9 позвонить». "
    "Команду сразу удалю, собеседник ничего не увидит. Ещё в чате: «!обещания», «!пересказ за неделю», "
    "«!найди адрес», «!выгрузи».\n"
    "📤 /export @username [с 01.09.2026] [по 05.11.2026], выгрузка переписки в HTML и TXT. "
    "Или просто «выгрузи @username».\n"
    "📝 Расшифровка ГС, две фишки:\n"
    "  1) по запросу: ответь в чате на ГС или кружок словом «т» (или выбери в меню @ «Расшифровать последнее ГС»), "
    "метку сотру, а текст появится прямо в чате ответом на ГС, его видят оба;\n"
    "  2) /voice auto: каждое входящее ГС сразу присылаю тебе сюда текстом, в чат ничего не пишу. /voice off выключить.\n"
    "  3) перешли мне любое ГС или кружок сюда, в личку, и я пришлю текст.\n"
    "🤝 /promises @username, кто что обещал и к какому сроку.\n"
    "📋 /summary @username за неделю, пересказ переписки.\n"
    "🔎 /find где он кидал адрес, поиск по смыслу и словам с любыми окончаниями.\n"
    "✅ Ответь на сообщение «+задача», оно станет задачей (метку уберу). /tasks список.\n"
    "🔕 /busy 2ч Я на паре, сам отвечу собеседникам (каждому один раз), /busy off сводка, кто писал.\n"
    "🎂 Ловлю «у меня др 12 марта» и напоминаю за день и в сам день. /birthdays список.\n"
    "🌙 В 21:00 итоги дня: кто что удалил и изменил, кто ждёт ответа. /digest off выключить, /digest показать сейчас."
)


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await ab.answer(msg, HELP)


async def warm_whisper():
    import stt
    try:
        await asyncio.to_thread(stt.load, str(ab.DATA / "whisper"))
        probe = ab.DATA / "stt_probe.oga"
        if probe.exists():
            import time
            t = time.time()
            text = await asyncio.to_thread(stt.transcribe, str(probe), str(ab.DATA / "whisper"))
            log.info("распознавание: проба %s за %.1f с: %s", probe.name, time.time() - t, text[:300])
            probe.unlink(missing_ok=True)
    except Exception as e:
        log.warning("помощник: модель распознавания не загрузилась: %s", e)


async def loops(bot: Bot):
    try:
        import av  # noqa: F401
        import faster_whisper  # noqa: F401
        import stt
        log.info("помощник: распознавание ГС, модель %s, луч %s, прогреваю в фоне", stt.MODEL_NAME, stt.BEAM)
        asyncio.create_task(warm_whisper())
    except Exception as e:
        WHISPER["broken"] = True
        log.warning("помощник: распознавание ГС недоступно: %s", e)
    log.info("помощник: ключ для умного режима %s", "есть" if llm.enabled() else "не задан, работаю на правилах")
    asyncio.create_task(reminder_loop(bot))
    while True:
        for tick in (busy_tick, birthday_tick, digest_tick):
            try:
                await tick(bot)
            except Exception as e:
                log.warning("%s: %s", tick.__name__, e)
        await asyncio.sleep(30)
