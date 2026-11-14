import asyncio
import hashlib
import html
import json
import logging
import random
import re
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (CallbackQuery, ChatMemberUpdated, ChatPermissions, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyParameters)

import archive_bot as ab
import ugu
from timeparse import MSK

log = logging.getLogger("groups")
router = Router()
GROUPS = {"group", "supergroup"}
ANON = 1087968824
clock = time.time
WARN_MUTE = timedelta(days=1)
FLOOD_N, FLOOD_SEC, FLOOD_MUTE = 5, 5, timedelta(minutes=10)
ROULETTE_MUTE = timedelta(minutes=5)
REP_COOLDOWN = 3600
DEFAULTS = {"welcome": False, "antilinks": False, "antispam": False, "antimat": False, "antibots": False,
            "rp": True, "games": True, "roulette_mute": True, "warn_limit": 3}
PANEL = [("welcome", "Приветствие"), ("antilinks", "Антиссылки"), ("antispam", "Антиспам"), ("antimat", "Антимат"),
         ("antibots", "Антиботы"), ("rp", "RP"), ("games", "Игры"), ("roulette_mute", "Мут в рулетке")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS ugu_groups (chat_id INTEGER PRIMARY KEY, settings TEXT, welcome TEXT, rules TEXT);
CREATE TABLE IF NOT EXISTS ugu_group_stats (chat_id INTEGER, user_id INTEGER, name TEXT, day TEXT, count INTEGER,
    PRIMARY KEY (chat_id, user_id, day));
CREATE TABLE IF NOT EXISTS ugu_group_users (chat_id INTEGER, user_id INTEGER, username TEXT, name TEXT,
    PRIMARY KEY (chat_id, user_id));
CREATE TABLE IF NOT EXISTS ugu_group_ranks (chat_id INTEGER, user_id INTEGER, rank INTEGER, PRIMARY KEY (chat_id, user_id));
CREATE TABLE IF NOT EXISTS ugu_group_warns (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    reason TEXT, by_id INTEGER, ts TEXT);
CREATE TABLE IF NOT EXISTS ugu_group_rep (chat_id INTEGER, user_id INTEGER, name TEXT, score INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id));
CREATE TABLE IF NOT EXISTS ugu_group_rep_log (chat_id INTEGER, giver INTEGER, receiver INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS ugu_group_notes (chat_id INTEGER, title TEXT, text TEXT, author TEXT, ts TEXT,
    PRIMARY KEY (chat_id, title));
CREATE TABLE IF NOT EXISTS ugu_group_timers (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
    name TEXT, fire_at TEXT, text TEXT, done INTEGER DEFAULT 0);
"""
READY = set()
SEEN = defaultdict(lambda: deque(maxlen=500))
FLOOD = defaultdict(lambda: deque(maxlen=20))
COOL = {}
JOINED = {}


@contextmanager
def dbx():
    with ab.db() as con:
        if str(ab.DB_PATH) not in READY:
            con.executescript(SCHEMA)
            READY.add(str(ab.DB_PATH))
        yield con


def B(s):
    return html.escape(str(s))


def nm(u):
    return " ".join(x for x in (u.first_name, u.last_name) if x) or u.username or "без имени"


def link(uid, name):
    return f'<a href="tg://user?id={uid}">{B(name)}</a>'


def cool(key, sec):
    t = clock()
    if t - COOL.get(key, -1e9) < sec:
        return False
    COOL[key] = t
    return True


def day_str(back=0):
    return (datetime.now(MSK) - timedelta(days=back)).strftime("%Y-%m-%d")


async def tell(bot, msg, text, reply=True, markup=None):
    rp = ReplyParameters(message_id=msg.message_id, allow_sending_without_reply=True) if reply else None
    th = msg.message_thread_id if msg.is_topic_message else None
    return await ugu.say(lambda t: bot.send_message(msg.chat.id, t, parse_mode="HTML", reply_parameters=rp, message_thread_id=th,
                                                    link_preview_options=ugu.lp(), reply_markup=markup), text)


async def say_chat(bot, chat_id, text):
    return await ugu.say(lambda t: bot.send_message(chat_id, t, parse_mode="HTML", link_preview_options=ugu.lp()), text)


def settings_of(chat_id):
    with dbx() as con:
        r = con.execute("SELECT settings, welcome, rules FROM ugu_groups WHERE chat_id=?", (chat_id,)).fetchone()
    s = dict(DEFAULTS)
    if r and r["settings"]:
        try:
            s.update(json.loads(r["settings"]))
        except ValueError:
            pass
    return s, (r["welcome"] if r else None), (r["rules"] if r else None)


def save(chat_id, **fields):
    with dbx() as con:
        con.execute("INSERT OR IGNORE INTO ugu_groups (chat_id, settings) VALUES (?, '{}')", (chat_id,))
        for k, v in fields.items():
            if k == "settings":
                v = json.dumps(v, ensure_ascii=False)
            assert k in ("settings", "welcome", "rules")
            con.execute(f"UPDATE ugu_groups SET {k}=? WHERE chat_id=?", (v, chat_id))


async def member(bot, chat_id, uid):
    try:
        return await bot.get_chat_member(chat_id, uid)
    except TelegramAPIError as e:
        if ab.is_network(e):
            raise
        return None


async def rank_of(bot, chat_id, uid):
    if uid == ANON:
        return 3
    with dbx() as con:
        r = con.execute("SELECT rank FROM ugu_group_ranks WHERE chat_id=? AND user_id=?", (chat_id, uid)).fetchone()
    stored = r["rank"] if r else 0
    m = await member(bot, chat_id, uid)
    status = getattr(getattr(m, "status", None), "value", getattr(m, "status", None))
    if status == "creator":
        return 3
    if status == "administrator":
        return max(stored, 2)
    return stored


def fail(e, what):
    s = str(e).lower()
    if "owner" in s or "administrator" in s and "can't" in s or "not enough rights" in s and "user" in s:
        return "⟪sad⟫ Админов я не трогаю."
    if "rights" in s or "forbidden" in s or "not enough" in s or "admin" in s:
        return f"⟪sad⟫ Дай мне права админа: {what}."
    return f"⟪huh⟫ Не вышло: {B(str(e)[:120])}"


async def nag(bot, msg, e, what):
    if cool(("nag", msg.chat.id, what), 300):
        await tell(bot, msg, fail(e, what), reply=False)


def fmt_dur(td):
    s = int(td.total_seconds())
    for sec, u in ((86400 * 30, "мес"), (86400 * 7, "нед"), (86400, "д"), (3600, "ч"), (60, "мин")):
        if s >= sec and s % sec == 0:
            return f"{s // sec} {u}"
    return f"{max(s // 60, 1)} мин"


DUR = re.compile(r"(?i)(?<![\w])(\d+)\s*(мес\w*|нед\w*|дн\w*|ден\w*|сут\w*|д|час\w*|ч|мин\w*|м|сек\w*|с)(?![\w])")
DUR_WORD = re.compile(r"(?i)(?<![\w])(полчаса|час|сутки|день|неделю|неделя|месяц|навсегда)(?![\w])")
WORD_SEC = {"полчаса": 1800, "час": 3600, "сутки": 86400, "день": 86400, "неделю": 604800, "неделя": 604800, "месяц": 2592000}


def unit_sec(u):
    u = u.lower()
    for pre, sec in (("мес", 2592000), ("нед", 604800), ("дн", 86400), ("ден", 86400), ("сут", 86400), ("час", 3600),
                     ("мин", 60), ("сек", 1)):
        if u.startswith(pre):
            return sec
    return {"д": 86400, "ч": 3600, "м": 60, "с": 1}[u]


def parse_dur(text, anchored=False):
    """(timedelta | None, остаток, навсегда). «30м», «2ч», «1д», «неделя», «навсегда»."""
    for m in DUR.finditer(text):
        if not anchored or m.start() == 0:
            return timedelta(seconds=int(m.group(1)) * unit_sec(m.group(2))), (text[:m.start()] + text[m.end():]).strip(), False
    for m in DUR_WORD.finditer(text):
        if not anchored or m.start() == 0:
            rest = (text[:m.start()] + text[m.end():]).strip()
            w = m.group(1).lower()
            return (None, rest, True) if w == "навсегда" else (timedelta(seconds=WORD_SEC[w]), rest, False)
    return None, text.strip(), False


USER_RX = re.compile(r"@(\w{3,32})")


class Tgt:
    def __init__(self, uid, name, rest, user=None):
        self.id, self.name, self.rest, self.user = uid, name, rest, user


def username_id(chat_id, username):
    with dbx() as con:
        r = con.execute("SELECT user_id, name FROM ugu_group_users WHERE chat_id=? AND username=?",
                        (chat_id, username.lower())).fetchone()
    return (r["user_id"], r["name"]) if r else None


def mentions(msg, arg):
    """Все упомянутые: [(id | None, имя, @ник)] и текст без упоминаний."""
    out, rest = [], arg
    for e in msg.entities or []:
        if e.type == "text_mention" and e.user and not e.user.is_bot:
            out.append((e.user.id, nm(e.user), e.user.username))
            rest = rest.replace(e.extract_from(msg.text or ""), "", 1)
    for u in USER_RX.findall(rest):
        found = username_id(msg.chat.id, u)
        out.append((found[0] if found else None, found[1] if found else u, u))
    return out, USER_RX.sub("", rest).strip()


def target(msg, arg):
    r = msg.reply_to_message
    if r and r.from_user and not (r.from_user.is_bot and r.from_user.id != ANON):
        return Tgt(r.from_user.id, ab.person(r.from_user), arg.strip(), r.from_user)
    found, rest = mentions(msg, arg)
    for uid, name, un in found:
        if uid:
            return Tgt(uid, f"{name} (@{un})" if un else name, rest)
    return None


async def pick(bot, msg, arg):
    t = target(msg, arg)
    if not t:
        await tell(bot, msg, "⟪huh⟫ Ответь на сообщение человека или укажи @ник (он должен был писать в чат).")
    return t


async def need(bot, msg, level):
    r = await rank_of(bot, msg.chat.id, msg.from_user.id)
    if r < level:
        await tell(bot, msg, f"⟪ghost⟫ Не по чину: нужен ранг {level}.")
        return None
    return r


async def can_hit(bot, msg, t, actor):
    if t.id == bot.id:
        await tell(bot, msg, "⟪ghost⟫ Себя не трону.")
        return False
    tr = await rank_of(bot, msg.chat.id, t.id)
    if t.id == msg.from_user.id or tr >= 3 or (tr >= actor and actor < 3):
        await tell(bot, msg, "⟪ghost⟫ Этого человека трогать нельзя.")
        return False
    return True


def mute_perms():
    return ChatPermissions(**{f: False for f in ("can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos",
                                                 "can_send_videos", "can_send_video_notes", "can_send_voice_notes",
                                                 "can_send_polls", "can_send_other_messages", "can_add_web_page_previews")})


async def open_perms(bot, chat_id):
    try:
        p = (await bot.get_chat(chat_id)).permissions
        if p and p.can_send_messages:
            return p
    except Exception as e:
        if ab.is_network(e):
            raise
    return ChatPermissions(**{f: True for f in ("can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos",
                                                "can_send_videos", "can_send_video_notes", "can_send_voice_notes",
                                                "can_send_polls", "can_send_other_messages", "can_add_web_page_previews",
                                                "can_invite_users")})


def until(td):
    return datetime.now(timezone.utc) + max(td, timedelta(seconds=60))


async def do_mute(bot, chat_id, uid, td):
    await bot.restrict_chat_member(chat_id, uid, mute_perms(), until_date=until(td))


async def delete_ids(bot, chat_id, ids):
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        if len(chunk) == 1:
            await bot.delete_message(chat_id, chunk[0])
        elif chunk:
            await bot.delete_messages(chat_id, chunk)


# ---------- ввод ----------

COMMANDS = []
PREFIX = re.compile(r"(?i)^\s*(?:[!/]|(?:угубот|угу)\s+)")


def cmd(pattern, raw=False):
    rx = re.compile(rf"^(?P<w>{pattern})(?![\w])\s*(?P<a>.*)$", re.I | re.S)

    def wrap(f):
        f.raw = raw
        COMMANDS.append((rx, f))
        return f
    return wrap


def parse(text):
    t = (text or "").strip()
    m = PREFIX.match(t)
    body = t[m.end():].strip() if m else t
    if m and m.group(0).strip().startswith("/"):
        body = re.sub(r"^(\S+?)@\w+", r"\1", body)
    if not body or (not m and body[0] not in "+-"):
        return None
    for rx, f in COMMANDS:
        r = rx.match(body)
        if r:
            return f, (f"{r.group('w')} {r.group('a')}".strip() if f.raw else r.group("a"))
    return None


def track(msg):
    u = msg.from_user
    SEEN[msg.chat.id].append((msg.message_id, u.id))
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_users (chat_id, user_id, username, name) VALUES (?,?,?,?) "
                    "ON CONFLICT(chat_id, user_id) DO UPDATE SET username=excluded.username, name=excluded.name",
                    (msg.chat.id, u.id, (u.username or "").lower() or None, nm(u)))


def count(msg):
    u = msg.from_user
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_stats (chat_id, user_id, name, day, count) VALUES (?,?,?,?,1) "
                    "ON CONFLICT(chat_id, user_id, day) DO UPDATE SET count=count+1, name=excluded.name",
                    (msg.chat.id, u.id, nm(u), day_str()))


LINK_RX = re.compile(r"(?i)(https?://|www\.|t\.me/|telegram\.me/|\b[\w-]+\.(?:ru|com|net|org|io|me|su|рф|info|xyz|ly|gg|cc|top|site|online)\b)")
MAT_RX = re.compile(r"(?i)(?<![\wа-яё])(?:[хx][уy]й\w*|пизд\w*|[её]б[аоуиылн]\w*|бл[яа]д\w*|бл[яа]ть|муда[кч]\w*|залуп\w*|[сc]ук[аи]\b)")
REP_RX = re.compile(r"^[+\-]\s*1?$")


def has_link(msg):
    text = msg.text or msg.caption or ""
    ents = (msg.entities or []) + (msg.caption_entities or [])
    return bool(LINK_RX.search(text)) or any(e.type in ("url", "text_link") for e in ents)


async def guards(bot, msg, s, flood=True):
    """True, если сообщение удалено и дальше не обрабатываем."""
    if not (s["antilinks"] or s["antimat"] or s["antispam"]):
        return False
    text = msg.text or msg.caption or ""
    reason = None
    if s["antilinks"] and has_link(msg):
        reason = ("ссылки", "тут нельзя со ссылками")
    elif s["antimat"] and MAT_RX.search(text):
        reason = ("мат", "давай без мата")
    flooding = False
    if flood and s["antispam"]:
        q = FLOOD[(msg.chat.id, msg.from_user.id)]
        now = clock()
        q.append(now)
        while q and now - q[0] > FLOOD_SEC:
            q.popleft()
        flooding = len(q) > FLOOD_N
    if not reason and not flooding:
        return False
    if await rank_of(bot, msg.chat.id, msg.from_user.id) >= 1:
        return False
    if flooding:
        FLOOD[(msg.chat.id, msg.from_user.id)].clear()
        try:
            await do_mute(bot, msg.chat.id, msg.from_user.id, FLOOD_MUTE)
            await tell(bot, msg, f"⟪sad⟫ {B(nm(msg.from_user))}, не флуди: мут на {fmt_dur(FLOOD_MUTE)}.", reply=False)
        except TelegramAPIError as e:
            await nag(bot, msg, e, "ограничение участников")
        return False
    try:
        await bot.delete_message(msg.chat.id, msg.message_id)
    except TelegramAPIError as e:
        await nag(bot, msg, e, "удаление сообщений")
        return False
    if cool(("guard", msg.chat.id, msg.from_user.id), 30):
        await tell(bot, msg, f"⟪huh⟫ {B(nm(msg.from_user))}, {reason[1]}.", reply=False)
    return True


@router.message(F.chat.type.in_(GROUPS), F.new_chat_members)
async def on_new(msg: Message, bot: Bot):
    for u in msg.new_chat_members:
        await joined(bot, msg.chat.id, u, msg.from_user)


@router.chat_member(F.chat.type.in_(GROUPS))
async def on_cm(ev: ChatMemberUpdated, bot: Bot):
    val = lambda m: getattr(m.status, "value", m.status)
    old, new = val(ev.old_chat_member), val(ev.new_chat_member)
    if old in ("left", "kicked") and (new == "member" or new == "restricted" and ev.new_chat_member.is_member):
        await joined(bot, ev.chat.id, ev.new_chat_member.user, ev.from_user)


async def joined(bot, chat_id, u, by):
    key = (chat_id, u.id)
    if clock() - JOINED.get(key, -1e9) < 60:
        return
    JOINED[key] = clock()
    if u.id == bot.id:
        await say_chat(bot, chat_id, "⟪ghost⟫ Угу на месте. «!помощь» покажет команды. Дай мне права админа, чтобы я мог наводить порядок.")
        return
    s, welcome, rules = settings_of(chat_id)
    if u.is_bot:
        if s["antibots"] and by and by.id != u.id and await rank_of(bot, chat_id, by.id) < 2:
            try:
                await bot.ban_chat_member(chat_id, u.id)
                await bot.unban_chat_member(chat_id, u.id, only_if_banned=True)
                await say_chat(bot, chat_id, f"⟪ghost⟫ Бота {B(nm(u))} выставил за дверь: ботов добавляют только админы.")
            except TelegramAPIError as e:
                await say_chat(bot, chat_id, fail(e, "блокировка участников"))
        return
    if s["welcome"] and welcome:
        text = B(welcome).replace("{имя}", link(u.id, nm(u)))
        tail = "\nПравила: «!правила»" if rules else ""
        await say_chat(bot, chat_id, f"⟪hi⟫ {text}{tail}")


@router.message(F.chat.type.in_(GROUPS))
async def on_message(msg: Message, bot: Bot):
    u = msg.from_user
    if not u or (u.is_bot and u.id != ANON) or msg.new_chat_members or msg.left_chat_member:
        raise SkipHandler
    track(msg)
    s, _, _ = settings_of(msg.chat.id)
    if await guards(bot, msg, s):
        return
    count(msg)
    text = msg.text or ""
    r = msg.reply_to_message
    if r and r.from_user and not r.from_user.is_bot and REP_RX.match(text.strip()):
        return await give_rep(bot, msg, text.strip()[0] == "+")
    found = parse(text)
    if not found:
        raise SkipHandler
    f, arg = found
    await f(bot, msg, arg)


@router.edited_message(F.chat.type.in_(GROUPS))
async def on_edit(msg: Message, bot: Bot):
    if not msg.from_user or msg.from_user.is_bot:
        raise SkipHandler
    s, _, _ = settings_of(msg.chat.id)
    if not await guards(bot, msg, s, flood=False):
        raise SkipHandler


# ---------- модерация ----------

@cmd(r"варн|warn")
async def c_warn(bot, msg, arg):
    actor = await need(bot, msg, 1)
    if actor is None:
        return
    t = await pick(bot, msg, arg)
    if not t or not await can_hit(bot, msg, t, actor):
        return
    s, _, _ = settings_of(msg.chat.id)
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_warns (chat_id, user_id, reason, by_id, ts) VALUES (?,?,?,?,?)",
                    (msg.chat.id, t.id, t.rest[:200], msg.from_user.id, ab.now()))
        n = con.execute("SELECT COUNT(*) FROM ugu_group_warns WHERE chat_id=? AND user_id=?", (msg.chat.id, t.id)).fetchone()[0]
    why = f" Причина: {B(t.rest)}." if t.rest else ""
    if n < s["warn_limit"]:
        return await tell(bot, msg, f"⟪huh⟫ Варн {B(t.name)}: {n}/{s['warn_limit']}.{why}")
    try:
        await do_mute(bot, msg.chat.id, t.id, WARN_MUTE)
    except TelegramAPIError as e:
        return await tell(bot, msg, f"⟪huh⟫ Варн {B(t.name)}: {n}/{s['warn_limit']}.{why}\n{fail(e, 'ограничение участников')}")
    with dbx() as con:
        con.execute("DELETE FROM ugu_group_warns WHERE chat_id=? AND user_id=?", (msg.chat.id, t.id))
    await tell(bot, msg, f"⟪sad⟫ {B(t.name)}: {n}/{s['warn_limit']} варнов, мут на {fmt_dur(WARN_MUTE)}.{why}")


@cmd(r"-варн|-warn|unwarn|снять\s+варн")
async def c_unwarn(bot, msg, arg):
    if await need(bot, msg, 1) is None:
        return
    t = await pick(bot, msg, arg)
    if not t:
        return
    with dbx() as con:
        row = con.execute("SELECT id FROM ugu_group_warns WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                          (msg.chat.id, t.id)).fetchone()
        if row:
            con.execute("DELETE FROM ugu_group_warns WHERE id=?", (row["id"],))
        n = con.execute("SELECT COUNT(*) FROM ugu_group_warns WHERE chat_id=? AND user_id=?", (msg.chat.id, t.id)).fetchone()[0]
    await tell(bot, msg, f"⟪ok⟫ Снял варн с {B(t.name)}. Осталось: {n}." if row else f"⟪think⟫ У {B(t.name)} нет варнов.")


@cmd(r"варны|warns")
async def c_warns(bot, msg, arg):
    t = target(msg, arg)
    with dbx() as con:
        if t:
            rows = con.execute("SELECT reason, ts FROM ugu_group_warns WHERE chat_id=? AND user_id=? ORDER BY id",
                               (msg.chat.id, t.id)).fetchall()
            lim = settings_of(msg.chat.id)[0]["warn_limit"]
            if not rows:
                return await tell(bot, msg, f"⟪ok⟫ У {B(t.name)} чисто.")
            body = "\n".join(f"{i}. {B(r['reason'] or 'без причины')} ({r['ts'][:10]})" for i, r in enumerate(rows, 1))
            return await tell(bot, msg, f"⟪see⟫ Варны {B(t.name)}: {len(rows)}/{lim}\n{body}")
        rows = con.execute("SELECT w.user_id, COUNT(*) c, COALESCE(u.name, '?') n FROM ugu_group_warns w LEFT JOIN ugu_group_users u "
                           "ON u.chat_id=w.chat_id AND u.user_id=w.user_id WHERE w.chat_id=? GROUP BY w.user_id ORDER BY c DESC LIMIT 20",
                           (msg.chat.id,)).fetchall()
    if not rows:
        return await tell(bot, msg, "⟪ok⟫ Варнов ни у кого нет.")
    await tell(bot, msg, "⟪see⟫ Варны в чате:\n" + "\n".join(f"{B(r['n'])}: {r['c']}" for r in rows))


@cmd(r"мут|mute")
async def c_mute(bot, msg, arg):
    actor = await need(bot, msg, 1)
    if actor is None:
        return
    t = await pick(bot, msg, arg)
    if not t or not await can_hit(bot, msg, t, actor):
        return
    td, rest, forever = parse_dur(t.rest)
    td = td or (timedelta(days=366) if forever else timedelta(hours=1))
    try:
        await do_mute(bot, msg.chat.id, t.id, td)
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "ограничение участников"))
    await tell(bot, msg, f"⟪sleep⟫ {B(t.name)} молчит {fmt_dur(td) if td < timedelta(days=366) else 'навсегда'}." + (f" Причина: {B(rest)}." if rest else ""))


@cmd(r"размут|unmute")
async def c_unmute(bot, msg, arg):
    if await need(bot, msg, 1) is None:
        return
    t = await pick(bot, msg, arg)
    if not t:
        return
    try:
        await bot.restrict_chat_member(msg.chat.id, t.id, await open_perms(bot, msg.chat.id))
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "ограничение участников"))
    await tell(bot, msg, f"⟪ok⟫ {B(t.name)} снова может писать.")


@cmd(r"бан|ban")
async def c_ban(bot, msg, arg):
    actor = await need(bot, msg, 2)
    if actor is None:
        return
    t = await pick(bot, msg, arg)
    if not t or not await can_hit(bot, msg, t, actor):
        return
    td, rest, forever = parse_dur(t.rest)
    try:
        await bot.ban_chat_member(msg.chat.id, t.id, until_date=until(td) if td else None)
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "блокировка участников"))
    await tell(bot, msg, f"⟪ghost⟫ {B(t.name)} улетел " + (f"на {fmt_dur(td)}." if td else "навсегда.") + (f" Причина: {B(rest)}." if rest else ""))


@cmd(r"разбан|unban")
async def c_unban(bot, msg, arg):
    if await need(bot, msg, 2) is None:
        return
    t = await pick(bot, msg, arg)
    if not t:
        return
    try:
        await bot.unban_chat_member(msg.chat.id, t.id, only_if_banned=True)
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "блокировка участников"))
    await tell(bot, msg, f"⟪ok⟫ {B(t.name)} может вернуться.")


@cmd(r"кик|kick")
async def c_kick(bot, msg, arg):
    actor = await need(bot, msg, 2)
    if actor is None:
        return
    t = await pick(bot, msg, arg)
    if not t or not await can_hit(bot, msg, t, actor):
        return
    try:
        await bot.ban_chat_member(msg.chat.id, t.id)
        await bot.unban_chat_member(msg.chat.id, t.id, only_if_banned=True)
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "блокировка участников"))
    await tell(bot, msg, f"⟪ghost⟫ {B(t.name)} выставлен за дверь.")


@cmd(r"удали|del")
async def c_delete(bot, msg, arg):
    await delete_cmd(bot, msg, arg, False)


@cmd(r"-смс|-sms")
async def c_sms(bot, msg, arg):
    await delete_cmd(bot, msg, arg, True)


async def delete_cmd(bot, msg, arg, is_sms):
    if await need(bot, msg, 1) is None:
        return
    r = msg.reply_to_message
    m = re.match(r"\s*(\d+)", arg)
    if is_sms or m:
        n = min(int(m.group(1)) if m else 1, 100)
        who = r.from_user.id if r and r.from_user else None
        ids = [mid for mid, uid in reversed(SEEN[msg.chat.id]) if mid != msg.message_id and (who is None or uid == who)][:n]
    elif r:
        ids = [r.message_id]
    else:
        return await tell(bot, msg, "⟪huh⟫ Ответь на сообщение, которое удалить, или «-смс 5».")
    try:
        await delete_ids(bot, msg.chat.id, ids + [msg.message_id])
    except TelegramAPIError as e:
        return await tell(bot, msg, fail(e, "удаление сообщений"))
    gone = set(ids)
    SEEN[msg.chat.id] = deque((x for x in SEEN[msg.chat.id] if x[0] not in gone and x[0] != msg.message_id), maxlen=500)


# ---------- ранги ----------

@cmd(r"\+модер|\+мод|\+rank")
async def c_rank_add(bot, msg, arg):
    if await need(bot, msg, 3) is None:
        return
    t = await pick(bot, msg, arg)
    if not t:
        return
    m = re.search(r"[123]", t.rest)
    rank = int(m.group()) if m else 1
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_ranks (chat_id, user_id, rank) VALUES (?,?,?) "
                    "ON CONFLICT(chat_id, user_id) DO UPDATE SET rank=excluded.rank", (msg.chat.id, t.id, rank))
    await tell(bot, msg, f"⟪ok⟫ {B(t.name)} теперь модер, ранг {rank}.")


@cmd(r"-модер|-мод|-rank")
async def c_rank_del(bot, msg, arg):
    if await need(bot, msg, 3) is None:
        return
    t = await pick(bot, msg, arg)
    if not t:
        return
    with dbx() as con:
        con.execute("DELETE FROM ugu_group_ranks WHERE chat_id=? AND user_id=?", (msg.chat.id, t.id))
    await tell(bot, msg, f"⟪ok⟫ {B(t.name)} больше не модер.")


@cmd(r"модеры|ранги")
async def c_ranks(bot, msg, arg):
    with dbx() as con:
        rows = con.execute("SELECT r.rank, COALESCE(u.name, r.user_id) n FROM ugu_group_ranks r LEFT JOIN ugu_group_users u "
                           "ON u.chat_id=r.chat_id AND u.user_id=r.user_id WHERE r.chat_id=? ORDER BY r.rank DESC", (msg.chat.id,)).fetchall()
    await tell(bot, msg, "⟪see⟫ Модеры:\n" + "\n".join(f"{B(r['n'])}: ранг {r['rank']}" for r in rows) if rows else
               "⟪think⟫ Модеров нет. Админы чата могут всё, остальных назначает «+модер».")


# ---------- приветствие и правила ----------

def text_setting(field, label, genitive):
    @cmd(rf"\+{label}")
    async def add(bot, msg, arg):
        if await need(bot, msg, 2) is None:
            return
        if not arg.strip():
            return await tell(bot, msg, f"⟪huh⟫ Напиши текст с новой строки: «+{label}» и дальше текст.")
        save(msg.chat.id, **{field: arg.strip()[:2000]})
        if field == "welcome":
            s, _, _ = settings_of(msg.chat.id)
            s["welcome"] = True
            save(msg.chat.id, settings=s)
        await tell(bot, msg, f"⟪ok⟫ Запомнил {genitive}.")

    @cmd(rf"-{label}")
    async def clear(bot, msg, arg):
        if await need(bot, msg, 2) is None:
            return
        save(msg.chat.id, **{field: None})
        await tell(bot, msg, f"⟪ok⟫ Убрал {genitive}.")

    @cmd(label)
    async def show(bot, msg, arg):
        s, welcome, rules = settings_of(msg.chat.id)
        val = welcome if field == "welcome" else rules
        await tell(bot, msg, f"⟪see⟫ {B(val)}" if val else f"⟪think⟫ {label.capitalize()} пока не заданы.")


text_setting("welcome", "приветствие", "приветствие")
text_setting("rules", "правила", "правила")


# ---------- настройки ----------

def panel_kb(s):
    btns = [InlineKeyboardButton(text=f"{'✅' if s[k] else '❌'} {label}", callback_data=f"grp:t:{k}") for k, label in PANEL]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text=f"Лимит варнов: {s['warn_limit']}", callback_data="grp:w")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@cmd(r"настройки|settings")
async def c_settings(bot, msg, arg):
    if await need(bot, msg, 3) is None:
        return
    s, _, _ = settings_of(msg.chat.id)
    await tell(bot, msg, "⟪ghost⟫ Настройки чата. Нажми, чтобы переключить:", markup=panel_kb(s))


@router.callback_query(F.data.startswith("grp:"), F.message.chat.type.in_(GROUPS))
async def on_panel(call: CallbackQuery, bot: Bot):
    msg = call.message
    cid = msg.chat.id
    if await rank_of(bot, cid, call.from_user.id) < 3:
        return await bot.answer_callback_query(call.id, text="Это только для ранга 3")
    s, _, _ = settings_of(cid)
    parts = call.data.split(":")
    if parts[1] == "t" and len(parts) == 3 and parts[2] in dict(PANEL):
        s[parts[2]] = not s[parts[2]]
    elif parts[1] == "w":
        s["warn_limit"] = s["warn_limit"] % 5 + 1
    else:
        return await bot.answer_callback_query(call.id)
    save(cid, settings=s)
    try:
        await bot.edit_message_reply_markup(chat_id=cid, message_id=msg.message_id, reply_markup=panel_kb(s))
    except TelegramAPIError as e:
        if "not modified" not in str(e):
            raise
    await bot.answer_callback_query(call.id, text="Готово")


# ---------- статистика и социалка ----------

def top_rows(chat_id, since=None, limit=10):
    with dbx() as con:
        return con.execute("SELECT user_id, MAX(name) n, SUM(count) c FROM ugu_group_stats WHERE chat_id=? AND day>=? "
                           "GROUP BY user_id ORDER BY c DESC, user_id LIMIT ?", (chat_id, since or "0000", limit)).fetchall()


def board(rows):
    return "\n".join(f"{i}. {B(r['n'])}: {r['c']}" for i, r in enumerate(rows, 1)) or "пока тихо"


@cmd(r"моя\s+стата|my\s*stats?")
async def c_mystat(bot, msg, arg):
    t = target(msg, arg)
    uid, name = (t.id, t.name) if t else (msg.from_user.id, nm(msg.from_user))
    q = "SELECT COALESCE(SUM(count), 0) FROM ugu_group_stats WHERE chat_id=? AND user_id=? AND day>=?"
    with dbx() as con:
        d, w, a = (con.execute(q, (msg.chat.id, uid, since)).fetchone()[0] for since in (day_str(), day_str(6), "0000"))
        rep = con.execute("SELECT score FROM ugu_group_rep WHERE chat_id=? AND user_id=?", (msg.chat.id, uid)).fetchone()
    await tell(bot, msg, f"⟪see⟫ {B(name)}: сегодня {d}, за неделю {w}, всего {a}. Репутация: {rep['score'] if rep else 0}.")


@cmd(r"стата|статистика|stats?")
async def c_stat(bot, msg, arg):
    await tell(bot, msg, f"⟪see⟫ <b>Сегодня</b>\n{board(top_rows(msg.chat.id, day_str()))}\n\n"
                         f"<b>Неделя</b>\n{board(top_rows(msg.chat.id, day_str(6)))}")


@cmd(r"топ|top")
async def c_top(bot, msg, arg):
    await tell(bot, msg, f"⟪see⟫ <b>Топ за всё время</b>\n{board(top_rows(msg.chat.id))}")


def active(chat_id):
    with dbx() as con:
        return [(r["user_id"], r["n"]) for r in con.execute(
            "SELECT user_id, MAX(name) n FROM ugu_group_stats WHERE chat_id=? AND day>=? GROUP BY user_id ORDER BY user_id",
            (chat_id, day_str(6))).fetchall()]


@cmd(r"кто\s+сегодня")
async def c_who(bot, msg, arg):
    what = arg.strip(" ?!.")
    people = active(msg.chat.id)
    if not what or not people:
        return await tell(bot, msg, "⟪huh⟫ Напиши: «кто сегодня красавчик». И чтобы в чате кто-то писал.")
    seed = int(hashlib.md5(f"{msg.chat.id}{day_str()}{what.lower()}".encode()).hexdigest(), 16)
    uid, name = people[seed % len(people)]
    await tell(bot, msg, f"⟪think⟫ Сегодня {B(what)}: {link(uid, name)}")


@cmd(r"шипперим|шипперить|ship")
async def c_ship(bot, msg, arg):
    people = active(msg.chat.id)
    if len(people) < 2:
        return await tell(bot, msg, "⟪huh⟫ Мало народу: нужно хотя бы двое активных.")
    a, b = random.sample(people, 2)
    await tell(bot, msg, f"⟪love⟫ Шипперим: {B(a[1])} и {B(b[1])}. Совет да любовь.")


async def give_rep(bot, msg, plus):
    r = msg.reply_to_message.from_user
    me = msg.from_user
    if r.id == me.id:
        return await tell(bot, msg, "⟪boo⟫ Себе репутацию не накрутить.")
    if r.id == bot.id:
        return await tell(bot, msg, "⟪boo⟫ Мне не надо, я призрак.")
    now = clock()
    with dbx() as con:
        last = con.execute("SELECT MAX(ts) FROM ugu_group_rep_log WHERE chat_id=? AND giver=? AND receiver=?",
                           (msg.chat.id, me.id, r.id)).fetchone()[0]
        if last and now - last < REP_COOLDOWN:
            left = int((REP_COOLDOWN - (now - last)) // 60) + 1
            return await tell(bot, msg, f"⟪sleep⟫ Этому человеку можно раз в час. Подожди {left} мин.")
        con.execute("INSERT INTO ugu_group_rep_log (chat_id, giver, receiver, ts) VALUES (?,?,?,?)", (msg.chat.id, me.id, r.id, now))
        con.execute("INSERT INTO ugu_group_rep (chat_id, user_id, name, score) VALUES (?,?,?,?) "
                    "ON CONFLICT(chat_id, user_id) DO UPDATE SET score=score+?, name=excluded.name",
                    (msg.chat.id, r.id, nm(r), 1 if plus else -1, 1 if plus else -1))
        score = con.execute("SELECT score FROM ugu_group_rep WHERE chat_id=? AND user_id=?", (msg.chat.id, r.id)).fetchone()[0]
    await tell(bot, msg, f"⟪ok⟫ {B(nm(me))} {'повысил' if plus else 'понизил'} репутацию {B(nm(r))}: теперь {score}.", reply=False)


@cmd(r"репутация|реп|rep")
async def c_rep(bot, msg, arg):
    t = target(msg, arg)
    uid, name = (t.id, t.name) if t else (msg.from_user.id, nm(msg.from_user))
    with dbx() as con:
        r = con.execute("SELECT score FROM ugu_group_rep WHERE chat_id=? AND user_id=?", (msg.chat.id, uid)).fetchone()
    await tell(bot, msg, f"⟪see⟫ Репутация {B(name)}: {r['score'] if r else 0}")


@cmd(r"рейтинг")
async def c_rating(bot, msg, arg):
    with dbx() as con:
        rows = con.execute("SELECT name, score FROM ugu_group_rep WHERE chat_id=? AND score!=0 ORDER BY score DESC LIMIT 10",
                           (msg.chat.id,)).fetchall()
    await tell(bot, msg, "⟪see⟫ <b>Рейтинг репутации</b>\n" + "\n".join(f"{i}. {B(r['name'])}: {r['score']}" for i, r in enumerate(rows, 1))
               if rows else "⟪think⟫ Репутацию пока никому не давали. Ответь «+» на сообщение.")


# ---------- RP ----------

RP = [(r"обн\w*", "обнимает", "🤗"), (r"(?:по)?целов\w*|целуй\w*|чмок\w*", "целует", "😘"), (r"удар\w*|бить|врежь", "бьёт", "👊"),
      (r"пн\w*|пинк\w*|пина\w*", "пинает", "🦶"), (r"погла\w*|гладь", "гладит", "🥰"), (r"укус\w*|кус\w*", "кусает", "😬"),
      (r"пожм\w*|пожать\s+руку", "жмёт руку", "🤝"), (r"да(?:ть|й)\s+пять", "даёт пять", "🙌"), (r"похвал\w*|хвали\w*", "хвалит", "👏"),
      (r"накорм\w*|покорм\w*", "кормит", "🍔"), (r"пощекот\w*", "щекочет", "😆"), (r"угост\w*", "угощает чаем", "🍵")]


def make_rp(pattern, verb, emoji):
    @cmd(pattern)
    async def rp(bot, msg, arg):
        s, _, _ = settings_of(msg.chat.id)
        if not s["rp"]:
            return await tell(bot, msg, "⟪sleep⟫ RP в этом чате выключено.")
        t = target(msg, arg)
        if not t:
            found, _ = mentions(msg, arg)
            if not found:
                return await tell(bot, msg, "⟪huh⟫ Ответь на сообщение или укажи @ник.")
            name = f"@{found[0][2]}"
        else:
            name = nm(t.user) if t.user else t.name
        await tell(bot, msg, f"{B(nm(msg.from_user))} {verb} {B(name)} {emoji}", reply=False)


for _p, _v, _e in RP:
    make_rp(_p, _v, _e)


# ---------- игры ----------

async def games_on(bot, msg):
    s, _, _ = settings_of(msg.chat.id)
    if not s["games"]:
        await tell(bot, msg, "⟪sleep⟫ Игры в этом чате выключены.")
    return s["games"]


@cmd(r"кубы|кубик|кости|dice", raw=True)
async def c_dice(bot, msg, arg):
    if not await games_on(bot, msg):
        return
    n = 1 if arg.lower().startswith("кубик") else 2
    th = msg.message_thread_id if msg.is_topic_message else None
    for _ in range(n):
        await bot.send_dice(msg.chat.id, emoji="🎲", message_thread_id=th)


@cmd(r"дуэль")
async def c_duel(bot, msg, arg):
    if not await games_on(bot, msg):
        return
    t = target(msg, arg)
    if not t:
        return await tell(bot, msg, "⟪huh⟫ Ответь на сообщение соперника.")
    a, b = nm(msg.from_user), (nm(t.user) if t.user else t.name)
    w = random.choice([a, b])
    line = random.choice(["Хлопок, дым, тишина.", "Оба моргнули, но один быстрее.", "Дуэль была недолгой.", "Призрак засчитал."])
    await tell(bot, msg, f"⟪boo⟫ {B(a)} и {B(b)} сошлись на дуэли. {line} Побеждает <b>{B(w)}</b>", reply=False)


@cmd(r"рулетка")
async def c_roulette(bot, msg, arg):
    if not await games_on(bot, msg):
        return
    s, _, _ = settings_of(msg.chat.id)
    me = msg.from_user
    if random.randrange(6) != 0:
        return await tell(bot, msg, f"⟪boo⟫ Щёлк. {B(nm(me))} живёт дальше.")
    out = f"⟪wow⟫ Бах. {B(nm(me))} выбывает."
    if s["roulette_mute"]:
        bm = await member(bot, msg.chat.id, bot.id)
        if getattr(getattr(bm, "status", None), "value", getattr(bm, "status", None)) == "administrator":
            try:
                await do_mute(bot, msg.chat.id, me.id, ROULETTE_MUTE)
                out += f" Помолчит {fmt_dur(ROULETTE_MUTE)}."
            except TelegramAPIError:
                out += " Но админа мне не взять."
    await tell(bot, msg, out, reply=False)


@cmd(r"жребий")
async def c_lot(bot, msg, arg):
    if not await games_on(bot, msg):
        return
    found, rest = mentions(msg, arg)
    opts = [f"@{un}" if un else name for _, name, un in found]
    if len(opts) < 2:
        opts = [o.strip() for o in re.split(r"(?i),|\s+или\s+", rest) if o.strip()]
    if len(opts) < 2:
        return await tell(bot, msg, "⟪huh⟫ Укажи минимум двоих: «жребий @a @b @c».")
    await tell(bot, msg, f"⟪boo⟫ Жребий выпал: <b>{B(random.choice(opts))}</b>")


def fun(pattern):
    @cmd(pattern, raw=True)
    async def f(bot, msg, arg):
        if await games_on(bot, msg):
            await tell(bot, msg, ugu.fun_answer(arg))


fun(r"инфа|вероятность|шанс")
fun(r"выбери")
fun(r"данет|да\s+или\s+нет")
fun(r"рандом")
fun(r"монетка|монету|орёл|орел")


# ---------- заметки и таймеры ----------

def split_note(arg):
    arg = arg.strip()
    if "\n" in arg:
        title, _, text = arg.partition("\n")
    else:
        title, _, text = arg.partition(" ")
    return title.strip().lower()[:50], text.strip()[:3000]


@cmd(r"\+заметка")
async def c_note_add(bot, msg, arg):
    if await need(bot, msg, 1) is None:
        return
    title, text = split_note(arg)
    if not title or not text:
        return await tell(bot, msg, "⟪huh⟫ Формат: «+заметка название» и с новой строки текст.")
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_notes (chat_id, title, text, author, ts) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(chat_id, title) DO UPDATE SET text=excluded.text, author=excluded.author, ts=excluded.ts",
                    (msg.chat.id, title, text, nm(msg.from_user), ab.now()))
    await tell(bot, msg, f"⟪ok⟫ Записал заметку «{B(title)}».")


@cmd(r"-заметка")
async def c_note_del(bot, msg, arg):
    if await need(bot, msg, 1) is None:
        return
    title = arg.strip().lower()
    with dbx() as con:
        n = con.execute("DELETE FROM ugu_group_notes WHERE chat_id=? AND title=?", (msg.chat.id, title)).rowcount
    await tell(bot, msg, f"⟪ok⟫ Заметка «{B(title)}» удалена." if n else "⟪think⟫ Такой заметки нет.")


@cmd(r"заметки")
async def c_notes(bot, msg, arg):
    with dbx() as con:
        rows = con.execute("SELECT title FROM ugu_group_notes WHERE chat_id=? ORDER BY title", (msg.chat.id,)).fetchall()
    await tell(bot, msg, "⟪see⟫ Заметки: " + ", ".join(B(r["title"]) for r in rows) if rows else "⟪think⟫ Заметок пока нет.")


@cmd(r"заметка")
async def c_note(bot, msg, arg):
    with dbx() as con:
        r = con.execute("SELECT title, text FROM ugu_group_notes WHERE chat_id=? AND title=?", (msg.chat.id, arg.strip().lower())).fetchone()
    await tell(bot, msg, f"⟪see⟫ <b>{B(r['title'])}</b>\n{B(r['text'])}" if r else "⟪think⟫ Такой заметки нет. Список: «заметки».")


@cmd(r"таймер|timer")
async def c_timer(bot, msg, arg):
    arg = re.sub(r"(?i)^через\s+", "", arg.strip())
    td, text, forever = parse_dur(arg, anchored=True)
    if not td or forever or td > timedelta(days=30):
        return await tell(bot, msg, "⟪huh⟫ Формат: «таймер через 10 минут позвонить». До 30 дней.")
    when = datetime.now(MSK) + td
    with dbx() as con:
        con.execute("INSERT INTO ugu_group_timers (chat_id, user_id, name, fire_at, text) VALUES (?,?,?,?,?)",
                    (msg.chat.id, msg.from_user.id, nm(msg.from_user), when.strftime("%Y-%m-%d %H:%M:%S"), text[:500] or "время вышло"))
    await tell(bot, msg, f"⟪alarm⟫ Поставил таймер на {when:%d.%m %H:%M}: {B(text) or 'время вышло'}")


@cmd(r"таймеры")
async def c_timers(bot, msg, arg):
    with dbx() as con:
        rows = con.execute("SELECT fire_at, text FROM ugu_group_timers WHERE chat_id=? AND done=0 ORDER BY fire_at LIMIT 15",
                           (msg.chat.id,)).fetchall()
    await tell(bot, msg, "⟪alarm⟫ Таймеры:\n" + "\n".join(f"{r['fire_at'][5:16]} {B(r['text'])}" for r in rows) if rows else "⟪think⟫ Таймеров нет.")


async def tick(bot, now=None):
    now = now or datetime.now(MSK)
    with dbx() as con:
        due = con.execute("SELECT * FROM ugu_group_timers WHERE done=0 AND fire_at<=? ORDER BY fire_at LIMIT 50",
                          (now.strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()
    for t in due:
        try:
            await say_chat(bot, t["chat_id"], f"⟪alarm⟫ <b>Таймер</b>: {B(t['text'])}\nПоставил: {link(t['user_id'], t['name'])}")
        except Exception as e:
            if ab.is_network(e):
                continue
            log.warning("таймер %s не отправлен: %s", t["id"], e)
        with dbx() as con:
            con.execute("UPDATE ugu_group_timers SET done=1 WHERE id=?", (t["id"],))


async def timers_loop(bot):
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("таймеры чатов")
        await asyncio.sleep(20)


# ---------- помощь ----------

HELP = ("⟪ghost⟫ Команды чата. Префикс: «!», «/», «угу » или «угубот ».\n"
        "<b>Модерация</b>: варн [причина], -варн, варны, мут [30м, 2ч, 1д], размут, бан [время], разбан, кик, удали, -смс N\n"
        "<b>Ранги</b>: +модер [1-3], -модер, модеры\n"
        "<b>Чат</b>: +приветствие, приветствие, +правила, правила, настройки\n"
        "<b>Статистика</b>: стата, моя стата, топ, кто сегодня ..., шипперим, репутация, рейтинг; «+» или «-» ответом\n"
        "<b>RP</b>: обнять, поцеловать, ударить, пнуть, погладить, укусить, пожать руку, дать пять, похвалить, накормить\n"
        "<b>Игры</b>: кубы, дуэль, рулетка, жребий @a @b, инфа, выбери, данет, рандом, монетка\n"
        "<b>Заметки</b>: +заметка, заметки, заметка имя, -заметка имя; таймер через 10 минут текст, таймеры")


@cmd(r"помощь|команды|help")
async def c_help(bot, msg, arg):
    await tell(bot, msg, HELP)
