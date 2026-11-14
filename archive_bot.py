import asyncio
import html
import logging
import os
import re
import sqlite3
import sys
from contextlib import contextmanager

if __name__ == "__main__":
    sys.modules.setdefault("archive_bot", sys.modules[__name__])
from datetime import datetime, timezone, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import (BusinessConnection, BusinessMessagesDeleted, CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo)

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DATA_DIR", BASE / "data"))
MEDIA = DATA / "media"
TMP = DATA / "tmp"
DB_PATH = DATA / "archive.db"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
UGU_TOKEN = os.environ.get("UGU_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
STORE_CHAT_ID = int(os.environ.get("STORE_CHAT_ID", "0"))
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
WEB_PORT = int(os.environ.get("PORT") or os.environ.get("WEB_PORT") or "0")
MAX_DOWNLOAD = 20 * 1024 * 1024
MSK = timezone(timedelta(hours=3))

log = logging.getLogger("archive")
router = Router()
BOTS = {}
CONN_OWNER = {}
ARCHIVING = set()
TRIGGER_IDS = set()
SAVE_TRIGGERS = {".", "+", "📌", "сохр", "сохрани", "s"}


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.create_function("ulower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    owner_id INTEGER, chat_id INTEGER, message_id INTEGER, connection_id TEXT,
    chat_title TEXT, sender_id INTEGER, sender_name TEXT,
    date TEXT, text TEXT, media_type TEXT, file_id TEXT, file_path TEXT, ext TEXT,
    dl_tries INTEGER DEFAULT 0, edited INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, deleted_at TEXT,
    store_file_id TEXT, store_msg_id INTEGER, store_kind TEXT,
    PRIMARY KEY (owner_id, chat_id, message_id))
"""


def columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY, user_id INTEGER, enabled INTEGER, updated TEXT);
        CREATE TABLE IF NOT EXISTS edits (
            chat_id INTEGER, message_id INTEGER, old_text TEXT, new_text TEXT, edited_at TEXT);
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, kind TEXT,
            text TEXT, file_id TEXT, file_path TEXT, tries INTEGER DEFAULT 0, created TEXT);
        """)
        old = columns(con, "messages")
        if old and "owner_id" not in old:
            for column in ("ext TEXT", "dl_tries INTEGER DEFAULT 0"):
                try:
                    con.execute(f"ALTER TABLE messages ADD COLUMN {column}")
                except sqlite3.OperationalError:
                    pass
            con.execute("ALTER TABLE messages RENAME TO messages_v1")
            con.execute(MESSAGES_SCHEMA)
            con.execute(
                "INSERT OR IGNORE INTO messages (owner_id, chat_id, message_id, connection_id, chat_title, sender_id,"
                " sender_name, date, text, media_type, file_id, file_path, ext, dl_tries, edited, deleted, deleted_at)"
                " SELECT COALESCE(c.user_id, ?), m.chat_id, m.message_id, m.connection_id, m.chat_title, m.sender_id,"
                " m.sender_name, m.date, m.text, m.media_type, m.file_id, m.file_path, m.ext, m.dl_tries, m.edited,"
                " m.deleted, m.deleted_at FROM messages_v1 m LEFT JOIN connections c ON c.id = m.connection_id",
                (OWNER_ID,))
            con.execute("DROP TABLE messages_v1")
        else:
            con.execute(MESSAGES_SCHEMA)
        con.execute("CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(owner_id, chat_id, date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_msg_store ON messages(store_file_id)")
        con.execute("CREATE TABLE IF NOT EXISTS bot_users (user_id INTEGER, bot TEXT, seen TEXT, PRIMARY KEY (user_id, bot))")
        con.execute("CREATE TABLE IF NOT EXISTS conn_bot (id TEXT PRIMARY KEY, bot TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS prefs (owner_id INTEGER, key TEXT, value INTEGER, PRIMARY KEY (owner_id, key))")
        for table, column in (("edits", "owner_id INTEGER"), ("outbox", "ref_owner INTEGER"),
                              ("outbox", "ref_chat INTEGER"), ("outbox", "ref_msg INTEGER"), ("outbox", "via TEXT"),
                              ("messages", "recv_bot TEXT"), ("messages", "store_bot TEXT")):
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        con.execute("UPDATE edits SET owner_id=? WHERE owner_id IS NULL", (OWNER_ID,))
        for row in con.execute("SELECT id, user_id FROM connections"):
            CONN_OWNER[row["id"]] = row["user_id"]
    import assistant
    import tiers
    assistant.init_db()
    tiers.init_db()


def now():
    return datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")


# ---------- два бота в одном процессе: архив и Угу ----------

def bot_name(bot):
    """Имя бота в реестре: 'archive' или 'ugu'. Неизвестный (тесты, один бот) = 'archive'."""
    for name, b in BOTS.items():
        if b is not None and bot is not None and b.id == bot.id:
            return name
    return "archive"


def bot_by(name, default=None):
    return BOTS.get(name) or BOTS.get("archive") or default


class OnBot(Filter):
    """Обработчик только для своего бота: общий Dispatcher кормит оба."""

    def __init__(self, name):
        self.name = name

    async def __call__(self, event, bot: Bot) -> bool:
        return bot_name(bot) == self.name


def business_bot(owner):
    """Чей бизнес-архив главный: подключён Угу = Угу, иначе архив-бот."""
    with db() as con:
        row = con.execute("SELECT 1 FROM connections c JOIN conn_bot b ON b.id=c.id WHERE c.user_id=? AND c.enabled=1"
                          " AND b.bot='ugu'", (owner,)).fetchone()
    return "ugu" if row else "archive"


def handles(bot, owner):
    """Если подключены оба бота, бизнес-события обрабатывает только главный, чтобы не было дублей."""
    return len(BOTS) < 2 or bot_name(bot) == business_bot(owner)


def via_for(user_id):
    """Каким ботом писать человеку: тот, к которому подключён архив, иначе тот, кому он писал последним."""
    if len(BOTS) < 2 or not user_id:
        return "archive"
    with db() as con:
        conn = con.execute("SELECT COALESCE(b.bot,'archive') b FROM connections c LEFT JOIN conn_bot b ON b.id=c.id"
                           " WHERE c.user_id=? AND c.enabled=1 ORDER BY (COALESCE(b.bot,'archive')='ugu') DESC, c.updated DESC"
                           " LIMIT 1", (user_id,)).fetchone()
        if conn:
            return conn["b"]
        seen = con.execute("SELECT bot FROM bot_users WHERE user_id=? ORDER BY seen DESC LIMIT 1", (user_id,)).fetchone()
    return seen["bot"] if seen else "archive"


def bot_for(user_id, default=None):
    if len(BOTS) < 2:
        return default or bot_by("archive")
    return bot_by(via_for(user_id), default)


def seen_user(user_id, bot):
    if not user_id or len(BOTS) < 2:
        return
    with db() as con:
        con.execute("INSERT INTO bot_users VALUES (?,?,?) ON CONFLICT(user_id, bot) DO UPDATE SET seen=excluded.seen",
                    (user_id, bot_name(bot), now()))


def person(user):
    if not user:
        return "неизвестно"
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or "без имени"
    return f"{name} (@{user.username})" if user.username else name


def chat_title(chat):
    if chat.title:
        return chat.title
    name = " ".join(x for x in (chat.first_name, chat.last_name) if x) or "без имени"
    return f"{name} (@{chat.username})" if chat.username else name


def media_of(msg: Message):
    if msg.photo:
        return "фото", msg.photo[-1].file_id, msg.photo[-1].file_size, ".jpg"
    for kind, label, ext in (("video", "видео", ".mp4"), ("voice", "голосовое", ".ogg"),
                             ("video_note", "кружок", ".mp4"), ("audio", "аудио", ".mp3"),
                             ("document", "файл", ""), ("animation", "гифка", ".mp4"),
                             ("sticker", "стикер", ".webp")):
        obj = getattr(msg, kind)
        if obj:
            name = getattr(obj, "file_name", None) or ""
            return label, obj.file_id, obj.file_size, Path(name).suffix or ext
    if msg.contact:
        return "контакт", None, None, ""
    if msg.location:
        return "геолокация", None, None, ""
    return None, None, None, ""


def body_of(msg: Message):
    text = msg.text or msg.caption or ""
    if msg.contact:
        text = f"{msg.contact.first_name} {msg.contact.phone_number}".strip()
    if msg.location:
        text = f"{msg.location.latitude}, {msg.location.longitude}"
    return text


async def download(bot: Bot, name, file_id, size, ext, tries=3):
    if not file_id or (size and size > MAX_DOWNLOAD):
        return None
    target = TMP / f"{name}{ext}"
    for attempt in range(tries):
        try:
            await bot.download(file_id, destination=target)
            return str(target)
        except Exception as e:
            log.warning("не скачал файл %s (попытка %s): %s", name, attempt + 1, e)
            if attempt + 1 < tries:
                await asyncio.sleep(3)
    return None


async def resolve_owner(bot: Bot, connection_id):
    if connection_id in CONN_OWNER:
        return CONN_OWNER[connection_id]
    with db() as con:
        row = con.execute("SELECT user_id FROM connections WHERE id=?", (connection_id,)).fetchone()
    if row:
        CONN_OWNER[connection_id] = row["user_id"]
        return row["user_id"]
    for attempt in range(3):
        try:
            conn = await bot.get_business_connection(connection_id)
            save_connection(conn, bot_name(bot))
            return conn.user.id
        except Exception as e:
            log.warning("не узнал владельца подключения %s: %s", connection_id, e)
            await asyncio.sleep(2)
    return 0


def save_connection(conn: BusinessConnection, bot="archive"):
    CONN_OWNER[conn.id] = conn.user.id
    with db() as con:
        con.execute("INSERT OR REPLACE INTO connections VALUES (?, ?, ?, ?)",
                    (conn.id, conn.user.id, int(conn.is_enabled), now()))
        con.execute("INSERT OR REPLACE INTO conn_bot VALUES (?, ?)", (conn.id, bot))
        con.execute("UPDATE messages SET owner_id=? WHERE owner_id=0 AND connection_id=?", (conn.user.id, conn.id))


def enqueue(chat_id, kind, text=None, ref=None, via=None):
    ref = ref or (None, None, None)
    via = via or via_for(chat_id)
    with db() as con:
        con.execute("INSERT INTO outbox (chat_id, kind, text, created, ref_owner, ref_chat, ref_msg, via)"
                    " VALUES (?,?,?,?,?,?,?,?)", (chat_id, kind, text, now(), *ref, via))


def notify(chat_id, text):
    for i in range(0, len(text), 4000):
        enqueue(chat_id, "text", text[i:i + 4000])


def archive_keyboard():
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="📂 Открыть архив", web_app=WebAppInfo(url=WEBAPP_URL))]])


@router.business_connection()
async def on_connection(conn: BusinessConnection, bot: Bot):
    save_connection(conn, bot_name(bot))
    if conn.is_enabled:
        notify(conn.user.id, "Архив подключён, сохраняю все личные переписки. Открыть архив: кнопка «Архив» внизу.")
    else:
        notify(conn.user.id, "Архив отключён. Сохранённое останется, пока ты не попросишь удалить.")


def mark_recv(owner, msg: Message, bot):
    """Какой бот получил сообщение: его file_id скачивается только этим ботом."""
    if len(BOTS) < 2:
        return
    with db() as con:
        con.execute("UPDATE messages SET recv_bot=? WHERE owner_id=? AND chat_id=? AND message_id=?",
                    (bot_name(bot), owner, msg.chat.id, msg.message_id))


def store_row(owner, msg: Message, quoted=False):
    label, file_id, size, ext = media_of(msg)
    keep = ("media_type=COALESCE(media_type, excluded.media_type), file_id=COALESCE(file_id, excluded.file_id),"
            " ext=COALESCE(ext, excluded.ext)") if quoted else (
            "text=excluded.text, media_type=COALESCE(excluded.media_type, media_type),"
            " file_id=COALESCE(excluded.file_id, file_id), ext=COALESCE(excluded.ext, ext)")
    with db() as con:
        con.execute(
            "INSERT INTO messages (owner_id, chat_id, message_id, connection_id, chat_title, sender_id,"
            " sender_name, date, text, media_type, file_id, ext) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
            f" ON CONFLICT(owner_id, chat_id, message_id) DO UPDATE SET {keep}",
            (owner, msg.chat.id, msg.message_id, msg.business_connection_id, chat_title(msg.chat),
             msg.from_user.id if msg.from_user else None, person(msg.from_user),
             msg.date.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S"), body_of(msg), label, file_id, ext or None))
    return label, file_id, size


def from_guest_bot(msg: Message):
    """Ответы ботов-гостей (Угу, Mira) в переписке: в архив не кладём, это не слова людей."""
    return bool(getattr(msg, "guest_bot_caller_user", None) or (msg.from_user and msg.from_user.is_bot))


@router.business_message()
async def on_message(msg: Message, bot: Bot):
    if from_guest_bot(msg):
        return
    owner = await resolve_owner(bot, msg.business_connection_id)
    if not handles(bot, owner):
        return
    mine = bool(msg.from_user and msg.from_user.id == owner)
    import assistant
    try:
        if await assistant.handle_business(msg, bot, owner, mine):
            return
    except Exception as e:
        log.warning("помощник: %s", e)
    if mine and msg.reply_to_message and (msg.text or "").strip().lower() in SAVE_TRIGGERS:
        await remove_trigger(msg, bot, owner)
    else:
        label, file_id, size = store_row(owner, msg)
        mark_recv(owner, msg, bot)
        if file_id:
            asyncio.create_task(archive_row(bot, owner, msg.chat.id, msg.message_id))
        if (msg.voice or msg.video_note) and not mine:
            icon = "🎤 ГС" if msg.voice else "⭕ Кружок"
            if msg.video_note:
                notify(owner, f"{icon} от <b>{html.escape(person(msg.from_user))}</b>")
            enqueue(owner, "media", f"{icon} от {person(msg.from_user)}", (owner, msg.chat.id, msg.message_id))
    if mine and msg.reply_to_message:
        await save_replied(msg, bot, owner)


async def remove_trigger(msg: Message, bot: Bot, owner):
    TRIGGER_IDS.add((owner, msg.chat.id, msg.message_id))
    for attempt in range(5):
        try:
            await bot.delete_business_messages(business_connection_id=msg.business_connection_id,
                                               message_ids=[msg.message_id])
            return
        except Exception as e:
            if not is_network(e):
                log.warning("не удалил метку: %s", e)
                notify(owner, "Не могу удалить твою метку из чата: дай мне право удалять сообщения. "
                              "Настройки → Telegram для бизнеса → Чат-боты → @mmrool_archive_bot → «Удаление сообщений».")
                return
            await asyncio.sleep(2)


async def save_replied(msg: Message, bot: Bot, owner):
    src = msg.reply_to_message
    trigger = (msg.text or "").strip().lower() in SAVE_TRIGGERS
    label, file_id, size = store_row(owner, src, quoted=True)
    if not file_id:
        if trigger:
            notify(owner, f"📌 Сохранил: <b>{html.escape(person(src.from_user))}</b>\n{html.escape(body_of(src))}")
        return
    asyncio.create_task(archive_row(bot, owner, src.chat.id, src.message_id))
    caption = f"📌 Сохранил по твоему ответу: {label} от {person(src.from_user)}"
    if label == "кружок":
        notify(owner, html.escape(caption))
    enqueue(owner, "media", caption[:1000], (owner, src.chat.id, src.message_id))


@router.edited_business_message()
async def on_edit(msg: Message, bot: Bot):
    if from_guest_bot(msg):
        return
    owner = await resolve_owner(bot, msg.business_connection_id)
    if not handles(bot, owner) or (owner, msg.chat.id, msg.message_id) in TRIGGER_IDS:
        return
    new_text = body_of(msg)
    with db() as con:
        row = con.execute("SELECT text FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
                          (owner, msg.chat.id, msg.message_id)).fetchone()
        old_text = row["text"] if row else None
        con.execute("INSERT INTO edits (chat_id, message_id, old_text, new_text, edited_at, owner_id) VALUES (?,?,?,?,?,?)",
                    (msg.chat.id, msg.message_id, old_text, new_text, now(), owner))
        if row:
            con.execute("UPDATE messages SET text=?, edited=1 WHERE owner_id=? AND chat_id=? AND message_id=?",
                        (new_text, owner, msg.chat.id, msg.message_id))
    if not row:
        label, file_id, size = store_row(owner, msg)
        with db() as con:
            con.execute("UPDATE messages SET edited=1 WHERE owner_id=? AND chat_id=? AND message_id=?",
                        (owner, msg.chat.id, msg.message_id))
        if file_id:
            asyncio.create_task(archive_row(bot, owner, msg.chat.id, msg.message_id))
    if (msg.from_user and msg.from_user.id == owner) or old_text == new_text or not pref(owner, "notify_edited"):
        return
    was = html.escape(old_text) if old_text is not None else "<i>не было в архиве</i>"
    notify(owner,
           f"✏️ <b>{html.escape(person(msg.from_user))}</b> изменил сообщение\n"
           f"Чат: {html.escape(chat_title(msg.chat))}\n\n"
           f"<b>Было:</b>\n{was or '<i>пусто</i>'}\n\n<b>Стало:</b>\n{html.escape(new_text) or '<i>пусто</i>'}")


@router.deleted_business_messages()
async def on_delete(event: BusinessMessagesDeleted, bot: Bot):
    owner = await resolve_owner(bot, event.business_connection_id)
    if not handles(bot, owner):
        return
    ids = [m for m in event.message_ids if (owner, event.chat.id, m) not in TRIGGER_IDS]
    if not ids:
        return
    with db() as con:
        rows = []
        for mid in sorted(ids):
            row = con.execute("SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?",
                              (owner, event.chat.id, mid)).fetchone()
            con.execute("UPDATE messages SET deleted=1, deleted_at=? WHERE owner_id=? AND chat_id=? AND message_id=?",
                        (now(), owner, event.chat.id, mid))
            rows.append((mid, row))
    if not pref(owner, "notify_deleted"):
        return
    lines = [f"🗑 В чате <b>{html.escape(chat_title(event.chat))}</b> удалено {len(rows)} сообщ."]
    for mid, row in rows:
        if not row:
            lines.append(f"\n• #{mid}: в архиве нет (пришло до подключения бота)")
            continue
        media = f" [{row['media_type']}]" if row["media_type"] else ""
        lines.append(f"\n• <b>{html.escape(row['sender_name'] or '')}</b>, {row['date'][5:16]}{media}\n"
                     f"{html.escape(row['text'] or '')}")
    notify(owner, "\n".join(lines))
    for mid, row in rows:
        if row and row["file_id"]:
            enqueue(owner, "media", f"Удалённое: {row['media_type']} от {row['sender_name']}"[:1000],
                    (owner, event.chat.id, mid))


UPLOAD = {"фото": "photo", "видео": "video", "голосовое": "voice", "кружок": "video_note",
          "аудио": "audio", "гифка": "animation"}


def file_id_of(sent: Message):
    if sent.photo:
        return sent.photo[-1].file_id
    for kind in ("video", "voice", "video_note", "audio", "animation", "document", "sticker"):
        obj = getattr(sent, kind, None)
        if obj:
            return obj.file_id
    return None


async def upload(bot: Bot, kind, path, caption):
    media = FSInputFile(path)
    if kind == "photo":
        return await bot.send_photo(STORE_CHAT_ID, media, caption=caption, parse_mode=None)
    if kind == "video":
        return await bot.send_video(STORE_CHAT_ID, media, caption=caption, parse_mode=None)
    if kind == "voice":
        return await bot.send_voice(STORE_CHAT_ID, media, caption=caption, parse_mode=None)
    if kind == "video_note":
        return await bot.send_video_note(STORE_CHAT_ID, media)
    if kind == "audio":
        return await bot.send_audio(STORE_CHAT_ID, media, caption=caption, parse_mode=None)
    if kind == "animation":
        return await bot.send_animation(STORE_CHAT_ID, media, caption=caption, parse_mode=None)
    return await bot.send_document(STORE_CHAT_ID, media, caption=caption, parse_mode=None)


async def archive_row(bot: Bot, owner, chat_id, message_id):
    key = (owner, chat_id, message_id)
    if key in ARCHIVING:
        return False
    ARCHIVING.add(key)
    try:
        with db() as con:
            row = con.execute("SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND message_id=?", key).fetchone()
        if not row or row["store_file_id"]:
            return bool(row)
        local = row["file_path"]
        path = local if local and Path(local).exists() else None
        if not path:
            path = await download(bot, f"{owner}_{chat_id}_{message_id}", row["file_id"], None, row["ext"] or "")
        if not path:
            with db() as con:
                con.execute("UPDATE messages SET dl_tries=dl_tries+1 WHERE owner_id=? AND chat_id=? AND message_id=?", key)
            return False
        kind = UPLOAD.get(row["media_type"], "document")
        caption = f"u{owner} · {row['chat_title']} · {row['sender_name']} · {row['date']}"[:1000]
        try:
            sent = await upload(bot, kind, path, caption)
        except Exception as e:
            if is_network(e):
                log.warning("не загрузил в хранилище %s: %s", key, e)
                return False
            log.warning("хранилище не приняло %s как %s (%s), пробую файлом", key, kind, e)
            kind = "document"
            sent = await upload(bot, kind, path, caption)
        with db() as con:
            con.execute("UPDATE messages SET store_file_id=?, store_msg_id=?, store_kind=?, file_path=NULL, store_bot='" + bot_name(bot) + "'"
                        " WHERE owner_id=? AND chat_id=? AND message_id=?",
                        (file_id_of(sent), sent.message_id, kind, *key))
        Path(path).unlink(missing_ok=True)
        return True
    except Exception as e:
        log.warning("архивация %s: %s", key, e)
        return False
    finally:
        ARCHIVING.discard(key)


async def archiver(bot: Bot, once=False):
    while True:
        with db() as con:
            rows = con.execute("SELECT owner_id, chat_id, message_id, recv_bot FROM messages WHERE file_id IS NOT NULL"
                               " AND store_file_id IS NULL AND dl_tries < 30 ORDER BY date DESC LIMIT 10").fetchall()
        for r in rows:
            await archive_row(bot_by(r["recv_bot"] or "archive", bot), r["owner_id"], r["chat_id"], r["message_id"])
        if once:
            return
        await asyncio.sleep(20)


async def deliver(bot: Bot, item):
    kind, chat_id, text = item["kind"], item["chat_id"], item["text"]
    if kind == "text":
        await bot.send_message(chat_id, text, reply_markup=None)
        return
    ref = (item["ref_owner"], item["ref_chat"], item["ref_msg"])
    query = ("SELECT store_file_id, store_kind, store_msg_id, store_bot, recv_bot FROM messages WHERE owner_id=? AND chat_id=?"
             " AND message_id=?")
    with db() as con:
        row = con.execute(query, ref).fetchone()
    if row and not row["store_file_id"]:
        await archive_row(bot_by(row["recv_bot"] or "archive", bot), *ref)
        with db() as con:
            row = con.execute(query, ref).fetchone()
    if not row:
        return
    if not row["store_file_id"]:
        raise FileNotReady("файл ещё не в хранилище")
    if (row["store_bot"] or "archive") != bot_name(bot) and row["store_msg_id"]:
        await bot.copy_message(chat_id, STORE_CHAT_ID, row["store_msg_id"],
                               caption=None if row["store_kind"] == "video_note" else text, parse_mode=None)
        return
    fid, store_kind = row["store_file_id"], row["store_kind"]
    if store_kind == "photo":
        await bot.send_photo(chat_id, fid, caption=text, parse_mode=None)
    elif store_kind == "video":
        await bot.send_video(chat_id, fid, caption=text, parse_mode=None)
    elif store_kind == "voice":
        await bot.send_voice(chat_id, fid, caption=text, parse_mode=None)
    elif store_kind == "video_note":
        await bot.send_video_note(chat_id, fid)
    elif store_kind == "audio":
        await bot.send_audio(chat_id, fid, caption=text, parse_mode=None)
    elif store_kind == "animation":
        await bot.send_animation(chat_id, fid, caption=text, parse_mode=None)
    else:
        await bot.send_document(chat_id, fid, caption=text, parse_mode=None)


class FileNotReady(Exception):
    pass


def is_network(e):
    from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
    return isinstance(e, (TelegramNetworkError, TelegramRetryAfter, TelegramServerError, FileNotReady,
                          asyncio.TimeoutError, OSError))


async def sender(bot: Bot, once=False):
    while True:
        with db() as con:
            item = con.execute("SELECT * FROM outbox ORDER BY id LIMIT 1").fetchone()
        if not item:
            if once:
                return
            await asyncio.sleep(2)
            continue
        try:
            await deliver(bot_by(item["via"] or "archive", bot), item)
            with db() as con:
                con.execute("DELETE FROM outbox WHERE id=?", (item["id"],))
        except Exception as e:
            if is_network(e) and item["tries"] < 500:
                log.warning("нет связи с Telegram, повтор: %s", e)
                with db() as con:
                    con.execute("UPDATE outbox SET tries=tries+1 WHERE id=?", (item["id"],))
                if once:
                    return
                await asyncio.sleep(getattr(e, "retry_after", None) or 10)
                continue
            log.warning("не отправил %s (%s), убираю из очереди: %s", item["kind"], item["id"], e)
            with db() as con:
                con.execute("DELETE FROM outbox WHERE id=?", (item["id"],))
                if item["kind"] != "text":
                    con.execute("INSERT INTO outbox (chat_id, kind, text, created) VALUES (?,?,?,?)",
                                (item["chat_id"], "text", f"Файл не смог переслать: {html.escape(str(e))}", now()))


def pref(owner, key, default=1):
    """Настройка владельца из мини-аппа (уведомлять об удалённом / изменённом)."""
    try:
        with db() as con:
            row = con.execute("SELECT value FROM prefs WHERE owner_id=? AND key=?", (owner, key)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row["value"] if row else default


def owner_has_archive(user_id):
    with db() as con:
        return bool(con.execute("SELECT 1 FROM connections WHERE user_id=?", (user_id,)).fetchone())


async def answer(msg: Message, text, keyboard=None):
    for attempt in range(3):
        try:
            await msg.answer(text, reply_markup=keyboard)
            return
        except Exception as e:
            if not is_network(e):
                raise
            await asyncio.sleep(3)
    notify(msg.chat.id, text)


@router.message(CommandStart(), OnBot("archive"))
async def cmd_start(msg: Message):
    await answer(msg,
                 "Я храню все сообщения из твоих личных чатов. Каждое ГС и кружок сразу присылаю сюда, "
                 "а если кто-то удалил или изменил сообщение, покажу, что было.\n\n"
                 "Подключение (нужен Telegram Premium): Настройки → Telegram для бизнеса → Чат-боты → "
                 "добавь меня, доступ ко всем личным чатам, разреши удалять сообщения.\n\n"
                 "Сохранить что-то тихо: ответь на сообщение точкой, точку я сразу уберу.\n\n"
                 "В любом чате набери @mmrool_archive_bot и выбери действие: напомнить, задача, выгрузить чат, "
                 "пересказ, что обещали, найти, занят. Ответ придёт сюда, собеседник ничего не увидит.\n\n"
                 "/chats листать архив прямо здесь, по чатам и дням\n/stats сколько сохранено\n"
                 "/search слово поиск по архиву\nКнопка «Архив» открывает то же в мини-аппе.\n\n"
                 "/help всё, что я умею как помощник: напоминания, выгрузка переписки, ГС в текст, задачи и другое.",
                 archive_keyboard())


@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    uid = msg.from_user.id
    if not owner_has_archive(uid):
        await answer(msg, "Архива пока нет: подключи меня через Telegram для бизнеса, подробности в /start.")
        return
    with db() as con:
        one = lambda sql: con.execute(sql, (uid,)).fetchone()[0]
        total = one("SELECT COUNT(*) FROM messages WHERE owner_id=?")
        chats = one("SELECT COUNT(DISTINCT chat_id) FROM messages WHERE owner_id=?")
        deleted = one("SELECT COUNT(*) FROM messages WHERE owner_id=? AND deleted=1")
        edits = one("SELECT COUNT(*) FROM edits WHERE owner_id=?")
        voices = one("SELECT COUNT(*) FROM messages WHERE owner_id=? AND media_type IN ('голосовое','кружок')")
        conn = con.execute("SELECT enabled FROM connections WHERE user_id=? ORDER BY updated DESC LIMIT 1",
                           (uid,)).fetchone()
    status = "подключён" if conn and conn["enabled"] else "не подключён"
    await answer(msg, f"Бот {status}.\nСообщений: {total}\nЧатов: {chats}\nГС и кружков: {voices}\n"
                      f"Удалённых: {deleted}\nПравок: {edits}", archive_keyboard())


@router.message(Command("search"))
async def cmd_search(msg: Message):
    uid = msg.from_user.id
    query = (msg.text or "").partition(" ")[2].strip()
    if not query:
        await answer(msg, "Напиши так: /search слово")
        return
    with db() as con:
        rows = con.execute("SELECT * FROM messages WHERE owner_id=? AND ulower(text) LIKE ? ORDER BY date DESC LIMIT 20",
                           (uid, f"%{query.lower()}%")).fetchall()
    if not rows:
        await answer(msg, "Ничего не нашёл.")
        return
    lines = []
    for r in rows:
        mark = " 🗑" if r["deleted"] else (" ✏️" if r["edited"] else "")
        lines.append(f"<b>{html.escape(r['chat_title'] or '')}</b> · {html.escape(r['sender_name'] or '')} · "
                     f"{r['date'][5:16]}{mark}\n{html.escape((r['text'] or '')[:300])}")
    notify(msg.chat.id, "\n\n".join(lines))


MEDIA_ICON = {"фото": "🖼", "видео": "🎬", "голосовое": "🎤", "кружок": "⭕", "аудио": "🎵", "файл": "📎",
              "гифка": "🎞", "стикер": "🙂", "контакт": "👤", "геолокация": "📍"}
CHATS_PAGE = 8


def chats_view(uid, page):
    with db() as con:
        rows = con.execute("SELECT chat_id, MAX(chat_title) AS title, MAX(date) AS last, SUM(deleted) AS del"
                           " FROM messages WHERE owner_id=? GROUP BY chat_id ORDER BY last DESC LIMIT ? OFFSET ?",
                           (uid, CHATS_PAGE + 1, page * CHATS_PAGE)).fetchall()
    if not rows and page == 0:
        return "Архив пока пустой.", None
    kb = [[InlineKeyboardButton(text=f"{r['title'][:40]}" + (f" · 🗑{r['del']}" if r["del"] else ""),
                                callback_data=f"d:{r['chat_id']}:")] for r in rows[:CHATS_PAGE]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"c:{page - 1}"))
    if len(rows) > CHATS_PAGE:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"c:{page + 1}"))
    if nav:
        kb.append(nav)
    return f"Твои чаты, страница {page + 1}. Выбери чат:", InlineKeyboardMarkup(inline_keyboard=kb)


def day_view(uid, chat, day):
    with db() as con:
        days = [r[0] for r in con.execute("SELECT DISTINCT substr(date,1,10) FROM messages WHERE owner_id=? AND chat_id=?"
                                          " ORDER BY 1", (uid, chat))]
        if not days:
            return "В этом чате пусто.", None
        if day not in days:
            later = [d for d in days if d >= day] if day else []
            day = later[0] if later else days[-1]
        rows = con.execute("SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND substr(date,1,10)=?"
                           " ORDER BY message_id", (uid, chat, day)).fetchall()
        was = {}
        for r in con.execute("SELECT message_id, old_text FROM edits WHERE owner_id=? AND chat_id=? AND old_text IS NOT NULL"
                             " ORDER BY edited_at", (uid, chat)):
            was.setdefault(r["message_id"], r["old_text"])
    title = rows[0]["chat_title"] if rows else ""
    head = f"<b>{html.escape(title)}</b>\n{day[8:10]}.{day[5:7]}.{day[:4]}, сообщений: {len(rows)}\n"
    lines = []
    for r in rows:
        who = "Я" if r["sender_id"] == uid else (r["sender_name"] or "").split(" (")[0]
        media = f"[{MEDIA_ICON.get(r['media_type'], '📎')} {r['media_type']}] " if r["media_type"] else ""
        marks = (" 🗑" if r["deleted"] else "") + (" ✏️" if r["edited"] else "")
        line = f"{r['date'][11:16]} <b>{html.escape(who)}</b>{marks}: {media}{html.escape((r['text'] or '')[:400])}"
        if r["edited"] and r["message_id"] in was:
            line += f"\n      <i>было: {html.escape(was[r['message_id']][:200])}</i>"
        lines.append(line)
    shown, size = [], len(head) + 80
    for line in reversed(lines):
        if size + len(line) + 1 > 3900:
            break
        shown.insert(0, line)
        size += len(line) + 1
    cut = "…начало дня не влезло, оно есть в мини-аппе\n" if len(shown) < len(lines) else ""
    text = head + cut + "\n".join(shown)
    i = days.index(day)
    nav = []
    if i > 0:
        nav.append(InlineKeyboardButton(text="◀ " + days[i - 1][5:].replace("-", "."), callback_data=f"d:{chat}:{days[i - 1]}"))
    if i < len(days) - 1:
        nav.append(InlineKeyboardButton(text=days[i + 1][5:].replace("-", ".") + " ▶", callback_data=f"d:{chat}:{days[i + 1]}"))
    kb = [nav] if nav else []
    if any(r["store_file_id"] for r in rows):
        kb.append([InlineKeyboardButton(text="📎 Прислать медиа этого дня", callback_data=f"m:{chat}:{day}")])
    kb.append([InlineKeyboardButton(text="⬅ К чатам", callback_data="c:0")])
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


async def safe_edit(call: CallbackQuery, text, keyboard):
    for attempt in range(3):
        try:
            await call.message.edit_text(text, reply_markup=keyboard)
            return
        except Exception as e:
            if "message is not modified" in str(e):
                return
            if not is_network(e):
                log.warning("не обновил сообщение: %s", e)
                return
            await asyncio.sleep(2)


async def safe_ack(call: CallbackQuery, text=None):
    try:
        await call.answer(text)
    except Exception:
        pass


@router.message(Command("chats"))
async def cmd_chats(msg: Message):
    if not owner_has_archive(msg.from_user.id):
        await answer(msg, "Архива пока нет: подключи меня через Telegram для бизнеса, подробности в /start.")
        return
    text, kb = chats_view(msg.from_user.id, 0)
    await answer(msg, text, kb)


@router.callback_query(F.data.startswith("c:"))
async def cb_chats(call: CallbackQuery):
    await safe_ack(call)
    text, kb = chats_view(call.from_user.id, max(0, int(call.data[2:] or 0)))
    await safe_edit(call, text, kb)


@router.callback_query(F.data.startswith("d:"))
async def cb_day(call: CallbackQuery):
    await safe_ack(call)
    _, chat, day = call.data.split(":", 2)
    text, kb = day_view(call.from_user.id, int(chat), day)
    await safe_edit(call, text, kb)


@router.callback_query(F.data.startswith("m:"))
async def cb_media(call: CallbackQuery):
    uid = call.from_user.id
    _, chat, day = call.data.split(":", 2)
    with db() as con:
        rows = con.execute("SELECT message_id, media_type, sender_name, date FROM messages WHERE owner_id=? AND chat_id=?"
                           " AND substr(date,1,10)=? AND store_file_id IS NOT NULL ORDER BY message_id LIMIT 20",
                           (uid, int(chat), day)).fetchall()
    for r in rows:
        enqueue(uid, "media", f"{r['date'][11:16]} {r['media_type']} от {r['sender_name']}"[:1000],
                (uid, int(chat), r["message_id"]))
    await safe_ack(call, f"Пришлю {len(rows)} файл(ов)" if rows else "Медиа нет")


POST_LINK = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:(c)/(\d+)|(?!c/)([A-Za-z0-9_]{4,}))/(?:\d+/)?(\d+)")


async def album_ids(username, message_id):
    import aiohttp
    url = f"https://t.me/{username}/{message_id}?embed=1&mode=tme"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), trust_env=True) as s:
            async with s.get(url) as r:
                page = await r.text()
    except Exception as e:
        log.warning("превью поста не открылось: %s", e)
        return [message_id]
    ids = sorted({int(x) for x in re.findall(rf"t\.me/{re.escape(username)}/(\d+)\?single", page)})
    return ids if message_id in ids and len(ids) > 1 else [message_id]


async def copy_post(bot: Bot, user_id, source, message_id, username=None):
    ids = await album_ids(username, message_id) if username else [message_id]
    if len(ids) > 1:
        await bot.copy_messages(user_id, source, ids)
    else:
        await bot.copy_message(user_id, source, message_id, parse_mode=None)
    return len(ids)


USER = None

RELAY_ID = 8887932504
RELAY_REQ = "POSTREQ"
RELAY_RES = "POSTRES"
RELAY_VIA = {}


async def relay_request(bot: Bot, user_id, link):
    for attempt in range(5):
        try:
            await bot.send_message(RELAY_ID, f"{RELAY_REQ} {user_id} {link}", parse_mode=None,
                                   disable_web_page_preview=True)
            return True
        except Exception as e:
            log.warning("не передал ссылку помощнику: %s", e)
            if not is_network(e):
                return False
            await asyncio.sleep(3)
    return False


@router.message(F.from_user.id == RELAY_ID, F.chat.type == "private",
                F.func(lambda m: ((m.caption if m.caption is not None else m.text) or "").startswith(RELAY_RES)))
async def on_relay_result(msg: Message, bot: Bot):
    body = msg.caption if msg.caption is not None else (msg.text or "")
    head, _, rest = body.partition("\n")
    parts = head.split()
    if len(parts) < 2 or parts[0] != RELAY_RES or not parts[1].lstrip("-").isdigit():
        return
    user_id = int(parts[1])
    target = bot_by(RELAY_VIA.get(user_id) or "archive", bot)
    for attempt in range(5):
        try:
            if msg.text is not None:
                await target.send_message(user_id, rest or "(пост без текста)", parse_mode=None,
                                          disable_web_page_preview=True)
            elif target is bot:
                await bot.copy_message(user_id, msg.chat.id, msg.message_id, caption=rest or None, parse_mode=None)
            else:
                await reupload(bot, target, user_id, msg, rest or None)
            return
        except Exception as e:
            if not is_network(e):
                log.warning("не переслал результат помощника: %s", e)
                return
            await asyncio.sleep(3)




async def reupload(src: Bot, dst: Bot, chat_id, msg: Message, caption):
    """Файл пришёл архив-боту, а человек ждёт его от Угу: скачать и отправить заново (у ботов разные file_id)."""
    obj, send, ext = ((msg.photo[-1], dst.send_photo, ".jpg") if msg.photo else
                      (msg.video, dst.send_video, ".mp4") if msg.video else
                      (msg.animation, dst.send_animation, ".mp4") if msg.animation else
                      (msg.audio, dst.send_audio, ".mp3") if msg.audio else
                      (msg.voice, dst.send_voice, ".ogg") if msg.voice else
                      (msg.document, dst.send_document, Path(getattr(msg.document, "file_name", "") or "").suffix))
    if obj is None:
        return
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / f"relay_{chat_id}_{msg.message_id}{ext or ''}"
    try:
        await src.download(obj.file_id, destination=path)
        await send(chat_id, FSInputFile(path), caption=caption, parse_mode=None)
    finally:
        path.unlink(missing_ok=True)


async def send_post(bot: Bot, chat_id, name, text, files, too_big):
    from aiogram.types import InputMediaPhoto, InputMediaVideo
    from userclient import is_media
    if text:
        for i in range(0, len(text), 4000):
            await bot.send_message(chat_id, text[i:i + 4000], parse_mode=None, disable_web_page_preview=True)
    media = [f for f in files if is_media(f)]
    other = [f for f in files if f not in media]
    if len(media) > 1:
        group = []
        for f in media[:10]:
            item = InputMediaVideo if Path(f).suffix.lower() in (".mp4", ".mov") else InputMediaPhoto
            group.append(item(media=FSInputFile(f)))
        await bot.send_media_group(chat_id, group)
    elif media:
        f = media[0]
        if Path(f).suffix.lower() in (".mp4", ".mov"):
            await bot.send_video(chat_id, FSInputFile(f), supports_streaming=True)
        else:
            await bot.send_photo(chat_id, FSInputFile(f))
    for f in other:
        await bot.send_document(chat_id, FSInputFile(f))
    if too_big:
        await bot.send_message(chat_id, f"Не прислал {len(too_big)} файл(а) больше 50 МБ: боту Telegram не даёт отправлять крупнее.",
                               parse_mode=None)
    if not text and not files and not too_big:
        await bot.send_message(chat_id, f"В посте {name} нет текста и файлов.", parse_mode=None)


@router.message(Command("login"), F.func(lambda m: m.from_user and m.from_user.id == OWNER_ID))
async def cmd_login(msg: Message, bot: Bot):
    if await USER.ready():
        await answer(msg, "Аккаунт уже подключён, посты по ссылке качаю сам.")
        return
    png = await USER.qr_png()
    from aiogram.types import BufferedInputFile
    await bot.send_photo(msg.chat.id, BufferedInputFile(png, "login.png"), parse_mode=None,
                         caption="Чтобы я мог открывать каналы как ты: на телефоне Настройки → Устройства → "
                                 "Подключить устройство и наведи камеру на этот код (код открой на компьютере). "
                                 "Код живёт 3 минуты. Если компьютера рядом нет, войди по коду: /phone +7XXXXXXXXXX")
    result = await USER.wait_qr()
    if result == "ok":
        await answer(msg, "Подключил. Теперь кидай ссылки на посты, качаю сам.")
    elif result == "password":
        await answer(msg, "У аккаунта стоит облачный пароль. Пришли его так: /pass твой_пароль "
                          "(сообщение с паролем я сразу удалю).")
    else:
        await answer(msg, "Код истёк. Напиши /login ещё раз.")


@router.message(Command("phone"), F.func(lambda m: m.from_user and m.from_user.id == OWNER_ID))
async def cmd_phone(msg: Message, bot: Bot):
    phone = re.sub(r"[^\d+]", "", (msg.text or "").partition(" ")[2])
    if len(re.sub(r"\D", "", phone)) < 10:
        await answer(msg, "Напиши так: /phone +79991234567")
        return
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        await USER.send_code(phone)
    except Exception as e:
        await answer(msg, f"Не смог запросить код: {html.escape(str(e))}")
        return
    await answer(msg, "Telegram прислал тебе код входа (в чат «Telegram»). Пришли его сюда <b>с пробелами между цифрами</b>, "
                      "например: 1 2 3 4 5. Без пробелов Telegram сочтёт, что код украли, и отменит его.")


@router.message(F.func(lambda m: m.from_user and m.from_user.id == OWNER_ID and USER is not None
                       and getattr(USER, "pending_phone", None) and re.fullmatch(r"[\d\s.\-]{5,20}", m.text or "")))
async def on_login_code(msg: Message, bot: Bot):
    code = re.sub(r"\D", "", msg.text or "")
    try:
        await msg.delete()
    except Exception:
        pass
    try:
        result = await USER.sign_in_code(code)
    except Exception as e:
        await answer(msg, f"Код не подошёл: {html.escape(str(e))}. Напиши /phone ещё раз.")
        return
    USER.pending_phone = None if result == "ok" else USER.pending_phone
    if result == "ok":
        await answer(msg, "Подключил. Теперь кидай ссылки на посты, качаю сам.")
    else:
        await answer(msg, "У аккаунта стоит облачный пароль. Пришли его так: /pass твой_пароль (сообщение сразу удалю).")


@router.message(Command("pass"), F.func(lambda m: m.from_user and m.from_user.id == OWNER_ID))
async def cmd_pass(msg: Message, bot: Bot):
    pwd = (msg.text or "").partition(" ")[2].strip()
    try:
        await msg.delete()
    except Exception:
        pass
    if not pwd:
        await answer(msg, "Напиши так: /pass твой_пароль")
        return
    try:
        await USER.password(pwd)
        await answer(msg, "Подключил. Теперь кидай ссылки на посты, качаю сам.")
    except Exception as e:
        await answer(msg, f"Пароль не подошёл: {html.escape(str(e))}. Попробуй /login заново.")


@router.message(F.chat.type == "private", F.text.regexp(POST_LINK))
async def on_post_link(msg: Message, bot: Bot):
    from userclient import cleanup
    import tiers
    for private, internal, username, mid in POST_LINK.findall(msg.text or ""):
        source = int(f"-100{internal}") if private else f"@{username}"
        name = f"c/{internal}/{mid}" if private else f"{username}/{mid}"
        ok, tier, cap = tiers.use(msg.from_user.id, "posts")
        if not ok:
            await answer(msg, tiers.limit_text("posts", tier, cap).replace("⟪sad⟫", "😔"))
            return
        try:
            n = await copy_post(bot, msg.chat.id, source, int(mid), None if private else username)
            log.info("пост %s скопирован напрямую, сообщений %s", name, n)
            continue
        except Exception as e:
            log.info("пост %s напрямую не взять: %s", name, e)
        if msg.from_user.id != OWNER_ID or not await USER.ready():
            link = f"https://t.me/{'c/' + internal if private else username}/{mid}"
            RELAY_VIA[msg.chat.id] = bot_name(bot)
            if await relay_request(bot_by("archive", bot), msg.chat.id, link):
                await answer(msg, "Качаю пост, пришлю через минуту.")
            else:
                await answer(msg, "Сейчас нет связи с Telegram, пришли ссылку ещё раз через минуту.")
            continue
        files = []
        try:
            await bot.send_chat_action(msg.chat.id, "upload_photo")
            text, files, too_big = await USER.download_post(private, internal, username, mid)
            if text is None:
                await answer(msg, f"Пост {html.escape(name)} не нашёл: удалён, или ты не состоишь в этом канале.")
                continue
            for attempt in range(3):
                try:
                    await send_post(bot, msg.chat.id, name, text, files, too_big)
                    break
                except Exception as e:
                    if not is_network(e) or attempt == 2:
                        raise
                    await asyncio.sleep(3)
            log.info("пост %s скачан аккаунтом, файлов %s", name, len(files))
        except Exception as e:
            log.warning("пост %s: %s", name, e)
            await answer(msg, f"Пост {html.escape(name)} скачать не смог: {html.escape(str(e))}")
        finally:
            cleanup(files)


async def setup_menu(bot: Bot):
    if not WEBAPP_URL:
        return
    from aiogram.types import BotCommand
    for attempt in range(20):
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Архив", web_app=WebAppInfo(url=WEBAPP_URL)))
            await bot.set_my_commands([BotCommand(command="help", description="Все функции помощника"),
                                       BotCommand(command="remind", description="Напоминание: /remind 18:00 созвон"),
                                       BotCommand(command="reminders", description="Мои напоминания"),
                                       BotCommand(command="tasks", description="Мои задачи"),
                                       BotCommand(command="export", description="Выгрузить переписку: /export @username"),
                                       BotCommand(command="summary", description="Пересказ: /summary @username"),
                                       BotCommand(command="promises", description="Обещания: /promises @username"),
                                       BotCommand(command="find", description="Поиск по смыслу"),
                                       BotCommand(command="busy", description="Режим занят: /busy 2ч текст"),
                                       BotCommand(command="birthdays", description="Дни рождения"),
                                       BotCommand(command="digest", description="Итоги дня"),
                                       BotCommand(command="voice", description="ГС в текст: on или off"),
                                       BotCommand(command="chats", description="Листать архив по чатам и дням"),
                                       BotCommand(command="search", description="Поиск: /search слово"),
                                       BotCommand(command="stats", description="Сколько сохранено"),
                                       BotCommand(command="start", description="Как подключить")])
            return
        except Exception as e:
            log.warning("меню-кнопка не встала: %s", e)
            await asyncio.sleep(15)


async def janitor():
    while True:
        cutoff = datetime.now().timestamp() - 15 * 60
        for folder in (TMP, DATA / "cache"):
            if folder.exists():
                for f in folder.iterdir():
                    try:
                        if f.is_file() and f.stat().st_mtime < cutoff and f.name.startswith("c_"):
                            f.unlink()
                    except OSError:
                        pass
        await asyncio.sleep(300)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not BOT_TOKEN or not STORE_CHAT_ID:
        raise SystemExit("нет BOT_TOKEN или STORE_CHAT_ID в .env")
    init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    bots = [bot]
    for b in bots:
        while True:
            try:
                await b.delete_webhook(drop_pending_updates=False)
                await b.me()
                break
            except Exception as e:
                log.warning("Telegram не отвечает на старте (%s), повтор через 15 сек", e)
                await asyncio.sleep(15)
    BOTS["archive"] = bot
    ugu_bot = None
    if UGU_TOKEN:
        ugu_bot = Bot(UGU_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        while True:
            try:
                await ugu_bot.delete_webhook(drop_pending_updates=False)
                await ugu_bot.me()
                break
            except Exception as e:
                log.warning("угу: Telegram не отвечает (%s), повтор через 15 сек", e)
                await asyncio.sleep(15)
        BOTS["ugu"] = ugu_bot
        bots.append(ugu_bot)
    else:
        log.info("угу: UGU_TOKEN не задан, работает только архив-бот")
    if WEB_PORT:
        import web
        await web.start(bot, WEB_PORT)
    dp = build_dispatcher()
    global USER
    from userclient import UserClient
    USER = UserClient(DATA)
    asyncio.create_task(USER.start())
    asyncio.create_task(sender(bot))
    asyncio.create_task(archiver(bot))
    asyncio.create_task(setup_menu(bot))
    asyncio.create_task(janitor())
    import assistant
    asyncio.create_task(assistant.loops(bot))
    if ugu_bot:
        import ugu
        asyncio.create_task(ugu.setup(ugu_bot))
    while True:
        try:
            await dp.start_polling(*bots, allowed_updates=dp.resolve_used_update_types())
            break
        except Exception as e:
            log.warning("опрос Telegram упал (%s), перезапуск через 15 сек", e)
            await asyncio.sleep(15)


def build_dispatcher():
    """Один диспетчер на оба бота. Порядок: приветствие Угу, архив, помощник, inline архива, группы, Угу (последним: ловит всё в личке)."""
    import assistant
    import inline
    import tiers
    import ugu
    assistant.init_db()
    tiers.init_db()
    tiers.router.message.filter(OnBot("ugu"))
    tiers.router.pre_checkout_query.filter(OnBot("ugu"))
    dp = Dispatcher()

    @dp.update.outer_middleware()
    async def remember_bot(handler, event, data):
        user = getattr(data.get("event_from_user"), "id", None)
        if user:
            try:
                seen_user(user, data.get("bot"))
            except Exception as e:
                log.warning("bot_users: %s", e)
        return await handler(event, data)

    dp.include_router(tiers.router)
    dp.include_router(ugu.start_router)
    dp.include_router(router)
    dp.include_router(assistant.router)
    dp.include_router(inline.router)
    try:
        import groups
        dp.include_router(groups.router)
    except ImportError:
        pass
    dp.include_router(ugu.router)
    return dp


if __name__ == "__main__":
    asyncio.run(main())
