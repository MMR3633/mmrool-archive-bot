import asyncio
import contextvars
import hashlib
import html
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery,
                           InlineQueryResultArticle, InlineQueryResultCachedPhoto, InlineQueryResultPhoto, InputMediaPhoto,
                           InputTextMessageContent, LinkPreviewOptions, Message)

import archive_bot as ab
import llm
import slang
import tiers
import websearch
from textutil import match_score, promises, stems, summary
from timeparse import MSK

log = logging.getLogger("archive.ugu")
router = Router()
router.message.filter(ab.OnBot("ugu"))
router.inline_query.filter(ab.OnBot("ugu"))
router.callback_query.filter(ab.OnBot("ugu"))
start_router = Router()
start_router.message.filter(ab.OnBot("ugu"))
UGU = {"bot": None, "username": "ugu_ai", "guest": None}

NAME_ANY = re.compile(r"(?i)(?<![\w@])(?:угу\s*-?\s*бот\w*|угубот\w*)(?!\w)[\s,:!.\-]*")
NAME_LEAD = re.compile(r"(?i)^\s*угу\s*[,:!]\s*(.+)$", re.S)
MENTION = re.compile(r"(?i)@ugu_ai(_bot)?\b[\s,:!.\-]*")
CALL_MAX = 300
GUEST_WAIT = 90
THINK = "⟪think⟫ …"
EMO = {"ghost": "👻", "think": "💭", "ok": "✅", "find": "🔎", "calendar": "📅", "alarm": "⏰", "mail": "📩", "huh": "❓",
       "web": "🌐", "trash": "🗑", "photo": "📷", "hi": "👋", "love": "❤️", "sleep": "💤", "voice": "🎤", "boo": "😜",
       "wow": "😮", "sad": "😢", "lol": "😂", "see": "👀", "deal": "🤝"}
EMO_FILE = Path(__file__).with_name("ugu_emoji.json")
EMO_IDS = json.loads(EMO_FILE.read_text(encoding="utf8")).get("ids", {}) if EMO_FILE.exists() else {}
EMO_RX = re.compile(r"⟪(\w+)⟫")
SHORT = 700
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

INTENTS = [
    ("help", r"^(что (ты )?(умеешь|можешь)|помощь|help|команды|как (тобой|с тобой) пользоваться)\b"),
    ("chat", r"^(привет\w*|здравствуй\w*|добр\w+ (утро|день|вечер|ночи)|как (твои |у тебя )?дела|как ты\b|как сам|как жизнь|как оно|как поживаешь|как настроение|"
             r"что делаешь|чем занят|ты (тут|здесь|живой|кто)|кто ты|спасибо|благодар|молодец|красава|умница|"
             r"люблю тебя|ты лучший|ты (дурак|тупой|глупый)|тупой бот|пока\b|спокойной ночи|доброй ночи)"),
    ("fun", r"^(инфа|информация|вероятность|шанс)\b|^выбери\b.+\bили\b|^(данет|да или нет)\b|^(рандом|случайное число)\b|"
            r"^(с?кинь |брось |подбрось )?(монет\w*)\b|^орёл или решка|^орел или решка|^(с?кинь |брось )?(кубик|кости)\b"),
    ("note", r"^[+]\s*заметк|^[-]\s*заметк|^(мои )?заметки\b|^заметка\b|^запиши\b|^сохрани (в заметки|заметку)|^в заметки\b"),
    ("stats", r"\b(стата|статистик\w*)\b|кто (больше|чаще) (пишет|пишем)|во сколько (мы )?(обычно )?(переписыва|общаемся)|сколько (у нас )?сообщений"),
    ("remind", r"\bнапомн|^таймер\b"),
    ("deleted", r"удал[её]н|удалил|удалили|стёр|стер\b|стерли|стёрли"),
    ("look", r"\S.{2,}?[\s,]+(и|а|плюс|\+)\s+(ещё\s+|еще\s+)?(дай|скинь|кинь|покажи|пришли|отправь)\s+(мне\s+|нам\s+)?"
             r"(картинк\w*|фот\w*|пикч\w*|как\s+выгляд\w*)(\s+(его|её|ее|их|этого|этой|пожалуйста|плз))*\s*[!.?]*$"),
    ("images", r"\b(скинь|покажи|найди|дай|пришли|отправь|го|хочу|нужн\w*|можно)\b.{0,40}\b(картинк\w*|фото|мем\w*|гифк\w*|обои|арт\w*|"
               r"пикч\w*|изображени\w*)\b|^(картинк\w*|фото|мем\w*|обои|пикч\w*)\b|\b(мем|мемы|мемов)\b|покажи,? как выгляд|"
               r"^(скинь|кинь|пришли|покажи|отправь)\s+(?!.*(кидал|скидывал|присылал|писал|адрес|номер|ссылк|файл|голосов|гс\b|"
               r"документ|удал|расписан|план|заметк|задач|напомин))[а-яёa-z-]+(\s+[а-яёa-z-]+){0,2}\s*[!.]*$"),
    ("look", r"^(а |ну )?(как|какой|какая|какие) (выгляд\w*|на вид)|^(а |ну )?как (он|она|оно|они) выгляд"),
    ("shop", r"\b(где|как) (купить|заказать|взять|достать)\b|\bкупить\b|\bпочём\b|\bпочем\b"),
    ("schedule", r"расписан|\bпланы?\b|по делам|какие (у меня )?дела|мои дела|что (у меня )?(на|по) (сегодня|завтра|недел)|"
                 r"что у меня (сегодня|завтра|на недел)|я (сегодня|завтра) свобод|напоминани|\bзадач"),
    ("promises", r"обещ|договорил|договорён|договорен|уговор|условил"),
    ("summary", r"сводк|пересказ|перескажи|о ч[её]м (мы )?(говорили|болтали|речь|переписк)|что было|кратко|итог"),
    ("voice", r"расшифр|что (он |она )?(сказал|говорит) в (гс|голосов)|текст (гс|голосов)"),
    ("photo", r"что (на|тут на|это на) (фото|картинк|скрин)|прочитай|что (тут|здесь) написано|что (это|тут) такое\??$"),
    ("first", r"(когда|в какой день|какого числа|с какого (дня|числа))\b.{0,40}\b(познаком\w*|начали (переписыв|общать|писать)\w*|"
              r"впервые|первый раз|написали друг другу|стали общаться|переписываемся|общаемся)|перв\w+ сообщени|"
              r"нача\w* перепис"),
    ("find", r"^(найди|поищи|где|когда)\b.*\b(он|она|ты|я|мы|скидывал\w*|кидал\w*|писал\w*|присылал\w*|говорил\w*|"
             r"отправлял\w*|адрес\w*|ссылк\w*|номер\w*|телефон\w*)\b|в (этой )?(переписке|чате)"),
    ("web", r"\?\s*$|^(что|кто|как|почему|зачем|сколько|где|когда|какой|какая|какое|какие|каков\w*|чем|отчего|"
            r"найди|поищи|загугли|погугли|расскажи|объясни|подскажи)\b"),
]
INTENTS = [(name, re.compile(rx, re.I)) for name, rx in INTENTS]
EXPLICIT = {"remind", "deleted", "schedule", "images", "summary", "promises", "find"}
STRONG = {"fun", "note", "stats", "first", "help", "remind", "deleted", "schedule", "promises", "summary", "voice", "images", "photo", "find"}
FIND_WORDS = re.compile(r"(?i)\b(найди|поищи|где|когда|он|она|ты|я|мы|мне|в (этой )?(переписке|чате)|скидывал\w*|кидал\w*|"
                        r"писал\w*|присылал\w*|говорил\w*|отправлял\w*)\b")
IMAGE_WORDS = re.compile(r"(?i)\b(скинь|покажи|найди|дай|пришли|отправь|го|хочу|нужн\w*|можно|мне|нам|сюда|в чат|"
                         r"пожалуйста|как(ой|ую|ие|ое)[ -]?(нибудь|то)|любую|любой|любые|рандомн\w*|случайн\w*|"
                         r"картинк\w*|фото|пикч\w*|изображени\w*|гифк\w*|с|про|на тему|как выгляд\w*)\b")
PLURAL_IMG = re.compile(r"(?i)\b(картинки|картинок|мемы|мемов|фото\s+\w+ов|обои|несколько|пару|штук)\b")

HELP = ("👻 Я Угу, призрак твоих переписок: вижу всё, даже удалённое. Зови по имени:\n"
        "• в своей переписке: «угубот, что у меня на неделе?», ответ впишу прямо в твоё сообщение;\n"
        "• в любом чате: «@ugu_ai вопрос», отвечу сам;\n"
        "• «@ugu_ai котики» в строке ввода: картинки, выбирай и отправляй.\n\n"
        "Умею: расписание и напоминания, о чём договорились, что обещали, найти в переписке, "
        "что удалили (только тебе в личку), расшифровать ГС, что на фото, ответ из интернета со ссылками, "
        "погода, курс, калькулятор, когда вы познакомились, статистика чата.\n"
        "Приколы: «инфа что…», «выбери А или Б», «данет», «рандом 1 100», «монетка», «кубик».\n"
        "Заметки: «+заметка купить молоко», «заметки», «-заметка 3».\n"
        "Фото (ответом на картинку): «демотиватор Текст», «шакал», «жмых», «текст на пикчу верх | низ».")


@dataclass
class Ctx:
    owner: int
    question: str
    chat_id: int | None = None
    chat_title: str = ""
    reply: Message | None = None
    file_bot: Bot | None = None
    kind: str | None = None
    can_ask: bool = False


@dataclass
class Answer:
    public: str = ""
    private: str = ""
    images: list = field(default_factory=list)
    choices: list = field(default_factory=list)
    qid: str = ""
    photo: bytes = b""


def deco(text, custom=True):
    """⟪имя⟫ → свой эмодзи-призрак (custom emoji) или обычный эмодзи."""
    def sub(m):
        fallback, eid = EMO.get(m.group(1), "👻"), EMO_IDS.get(m.group(1))
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if custom and eid else fallback
    return EMO_RX.sub(sub, text or "")


PREVIEW = contextvars.ContextVar("preview", default=None)
IMG_RX = re.compile(r"⟪img:([^⟫]+)⟫")


def lp():
    return PREVIEW.get() or NO_PREVIEW


def with_image(url, text):
    """Картинка крупно над текстом: невидимая ссылка + превью."""
    return f"⟪img:{url}⟫" + text if url else text


async def say(call, text):
    """Шлёт со своими эмодзи; если Telegram их не принял, повторяет с обычными. ⟪img:url⟫ = картинка превью."""
    m = IMG_RX.search(text or "")
    if m:
        url = m.group(1)
        PREVIEW.set(LinkPreviewOptions(url=url, prefer_large_media=True, show_above_text=True))
        text = f'<a href="{html.escape(url, quote=True)}">⁠</a>' + IMG_RX.sub("", text)
    else:
        PREVIEW.set(None)
    try:
        return await call(deco(text))
    except Exception as e:
        if EMO_IDS and re.search(r"(?i)emoji|entit|document_invalid", str(e)):
            log.info("угу: свои эмодзи не прошли (%s), шлю обычные", e)
            return await call(deco(text, custom=False))
        raise


def notify(chat_id, text):
    ab.notify(chat_id, deco(text, custom=False))


def intent(question, reply=None):
    q = slang.normalize(question or "").strip()
    if reply is not None:
        explicit = any(rx.search(q) for name, rx in INTENTS if name in EXPLICIT)
        is_image = reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))
        if is_image and FX_RX.match(q):
            return "fx"
        if is_image and PRODUCT_RX.search(q):
            return "product"
        if not explicit and is_image:
            return "photo"
        if not explicit and (reply.voice or reply.video_note):
            return "voice"
    if not q:
        return "help"
    if PIC_PREFIX.match(q):
        return "images"
    if PERSONA.search(q):
        return "chat"
    for name, rx in INTENTS:
        if rx.search(q):
            if name == "web" and ABOUT_ME.search(q) and not re.search(r"(?i)\b(мне|меня|мой|моя|мои|нам|нас)\b", q):
                return "chat"
            return name
    if ABOUT_ME.search(q) and not re.search(r"(?i)\b(мне|меня|мой|моя|мои)\b", q):
        return "chat"
    return "unknown"


def find_call(text):
    """(часть до имени, вопрос) если в сообщении позвали Угу, иначе None."""
    t = text or ""
    if len(t) > CALL_MAX:
        return None
    m = NAME_ANY.search(t)
    if m:
        before, after = t[:m.start()].rstrip(" ,:;-"), t[m.end():].strip()
        if not re.search(r"\w", after):
            after = ""
        if after:
            return before, after
        if before:
            return "", before
        return "", ""
    m = NAME_LEAD.match(t)
    if m and intent(m.group(1)) in STRONG | {"chat"}:
        return "", m.group(1).strip()
    return None


def allowed(user_id):
    return bool(user_id) and (user_id == ab.OWNER_ID or ab.owner_has_archive(user_id))


def now():
    from datetime import datetime
    return datetime.now(MSK)


def has_chat(owner, chat_id):
    if not chat_id:
        return False
    with ab.db() as con:
        return bool(con.execute("SELECT 1 FROM messages WHERE owner_id=? AND chat_id=? LIMIT 1", (owner, chat_id)).fetchone())


BOT_NOISE = re.compile(r"(?i)@ugu_ai|угу\s*-?\s*бот|^\W{0,3}(нашёл:|нашел:|кратко за|чем помочь|скинул в личку|прислал в личку|"
                       r"я угу|не уверен, что ты|не понял|договорились:|планы на|планов на|💭|…$)")


def is_noise(text):
    """Вопросы к Угу и его ответы, попавшие в архив: в поиск и сводки не берём."""
    return bool(BOT_NOISE.search(text or ""))


def chat_rows(owner, chat_id, days, deleted=False):
    since = (now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with ab.db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND date >= ? AND deleted=? ORDER BY date",
            (owner, chat_id, since, int(deleted)))]
    return [r for r in rows if not is_noise(r["text"])]


def days_in(question, default=7):
    import assistant
    q = question or ""
    if re.search(r"(?i)сегодня", q):
        return 1
    if re.search(r"(?i)\bмесяц", q):
        return 30
    return assistant.period_days(q, default)


def who_name(r, owner):
    return "Я" if r["sender_id"] == owner else (r["sender_name"] or "собеседник").split(" (@")[0]


# ---------- ответы по архиву ----------

def schedule_text(owner, question):
    q = question.lower()
    start = now()
    if "завтра" in q:
        start = (start + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        span = "на завтра"
    elif "сегодня" in q:
        end = start.replace(hour=23, minute=59, second=59)
        span = "на сегодня"
    else:
        end = start + timedelta(days=30 if "месяц" in q else 7)
        span = "на месяц" if "месяц" in q else "на неделю"
    with ab.db() as con:
        rems = con.execute("SELECT title, due FROM reminders WHERE owner_id=? AND status='active' AND due BETWEEN ? AND ?"
                           " ORDER BY due", (owner, start.strftime("%Y-%m-%d %H:%M:%S"),
                                             end.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
        tasks = con.execute("SELECT text FROM tasks WHERE owner_id=? AND done=0 ORDER BY id DESC LIMIT 5", (owner,)).fetchall()
    lines = []
    for r in rems[:12]:
        from datetime import datetime
        d = datetime.strptime(r["due"], "%Y-%m-%d %H:%M:%S")
        lines.append(f"{DAYS[d.weekday()]} {d:%d.%m %H:%M} {html.escape(r['title'])}")
    if tasks:
        lines.append("Задачи: " + "; ".join(html.escape((t["text"] or "")[:60]) for t in tasks))
    if not lines:
        return f"⟪calendar⟫ Планов {span} у меня нет. Добавить: «угубот, напомни в пт 18:00 созвон»."
    return f"⟪calendar⟫ Планы {span}:\n" + "\n".join(lines)


def promises_answer(ctx):
    rows = chat_rows(ctx.owner, ctx.chat_id, days_in(ctx.question, 30))
    found = promises(rows, ctx.owner)
    if not found:
        return "⟪deal⟫ Договорённостей и сроков в этом чате не вижу."
    lines = [f"• {html.escape(who)}: {html.escape(s[:140])}{' (' + html.escape(dl) + ')' if dl else ''}"
             for who, d, s, dl in found[-6:]]
    return "⟪deal⟫ Договорились:\n" + "\n".join(lines)


def summary_answer(ctx):
    days = days_in(ctx.question, 7)
    rows = chat_rows(ctx.owner, ctx.chat_id, days)
    if not rows:
        return f"⟪see⟫ За {days} дн. в этом чате сообщений нет."
    s = summary(rows, ctx.owner, limit=5)
    lines = [f"⟪see⟫ Кратко за {days} дн.: {s['total']} сообщ., темы: {html.escape(', '.join(s['top_words'][:5])) or 'нет'}."]
    for r in s["key"]:
        lines.append(f"• {r['date'][8:10]}.{r['date'][5:7]} {html.escape(who_name(r, ctx.owner))}: "
                     f"{html.escape((r['text'] or '')[:120])}")
    return "\n".join(lines)


def deleted_answer(ctx):
    rows = chat_rows(ctx.owner, ctx.chat_id, days_in(ctx.question, 30), deleted=True)
    if not rows:
        return "⟪trash⟫ В этом чате за это время ничего не удаляли."
    lines = [f"🗑 Удалённое в чате {html.escape(ctx.chat_title)}:"]
    for r in rows[-15:]:
        media = f" [{r['media_type']}]" if r["media_type"] else ""
        lines.append(f"• {r['date'][5:16]} {html.escape(who_name(r, ctx.owner))}{media}: {html.escape((r['text'] or '')[:200])}")
    return "\n".join(lines)


def search(owner, words, chat_id=None, limit=3):
    with ab.db() as con:
        sql, args = "SELECT * FROM messages WHERE owner_id=? AND text IS NOT NULL AND text != ''", [owner]
        if chat_id:
            sql += " AND chat_id=?"
            args.append(chat_id)
        rows = con.execute(sql + " ORDER BY date DESC LIMIT 20000", args).fetchall()
    scored = sorted(((match_score(words, r["text"]), r) for r in rows if not is_noise(r["text"])),
                    key=lambda x: (x[0], x[1]["date"]), reverse=True)
    return [r for s, r in scored if s > 0][:limit]


# ---------- приколы, заметки, статистика, фото-эффекты (идеи Ириса и Демотика) ----------

FX_RX = re.compile(r"(?i)^(демотиватор\w*|демотив\w*|демк\w*|шакал\w*|жмых\w*|текст на (пикчу|фото|картинку)|мем\b|подпиши|надпись)")
YES_NO = ["Да.", "Нет.", "Скорее да.", "Скорее нет.", "Сто процентов да.", "Даже не думай.", "Спроси завтра.", "Звёзды говорят да."]


def fun_answer(question):
    q = slang.normalize(question).strip()
    low = q.lower()
    m = re.match(r"(?i)^(инфа|информация|вероятность|шанс)\s*(что|на то что|того что)?\s*(.*)$", q)
    if m:
        what = m.group(3).strip(" ?") or "это правда"
        seed = int(hashlib.md5(f"{what.lower()}{now():%Y%m%d}".encode()).hexdigest(), 16)
        return f"⟪think⟫ Вероятность, что {html.escape(what)}: <b>{seed % 101}%</b>"
    m = re.match(r"(?i)^выбери\s*:?\s*(.+)$", q)
    if m:
        options = [o.strip(" ?.!") for o in re.split(r"(?i)\s+или\s+|,", m.group(1)) if o.strip(" ?.!")]
        if len(options) >= 2:
            return f"⟪boo⟫ Выбираю: <b>{html.escape(random.choice(options))}</b>"
    if re.match(r"(?i)^(данет|да или нет)", low):
        return f"⟪think⟫ {random.choice(YES_NO)}"
    m = re.match(r"(?i)^(рандом|случайное число)\s*(?:от\s*)?(-?\d+)?\s*(?:до|-)?\s*(-?\d+)?", q)
    if m:
        a, b = int(m.group(2) or 1), int(m.group(3) or 100)
        a, b = min(a, b), max(a, b)
        return f"⟪boo⟫ Случайное число от {a} до {b}: <b>{random.randint(a, b)}</b>"
    if re.search(r"(?i)монет|орёл|орел", low):
        return f"⟪boo⟫ {random.choice(['🪙 Орёл', '🪙 Решка'])}"
    if re.search(r"(?i)кубик|кости", low):
        return f"⟪boo⟫ 🎲 Выпало: <b>{random.randint(1, 6)}</b>"
    return "⟪huh⟫ Умею: «инфа что завтра дождь», «выбери пицца или суши», «данет», «рандом 1 100», «монетка», «кубик»."


NOTE_ADD = re.compile(r"(?i)^([+]\s*заметк\w*|запиши( в заметки)?|сохрани (в заметки|заметку)|в заметки)\s*:?\s*(.*)$", re.S)


def notes_table(con):
    con.execute("CREATE TABLE IF NOT EXISTS ugu_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, title TEXT, "
                "body TEXT, created TEXT, pinned INTEGER DEFAULT 0)")


def note_answer(ctx):
    q = slang.normalize(ctx.question).strip()
    with ab.db() as con:
        notes_table(con)
        m = re.match(r"(?i)^[-]\s*заметк\w*\s*(.*)$", q)
        if m:
            key = m.group(1).strip()
            row = con.execute("SELECT id, title FROM ugu_notes WHERE owner_id=? AND (CAST(id AS TEXT)=? OR ulower(title)=?)"
                              " ORDER BY id DESC LIMIT 1", (ctx.owner, key, key.lower())).fetchone()
            if not row:
                return Answer(public=f"⟪huh⟫ Заметку «{html.escape(key)}» не нашёл. Список: «заметки».")
            con.execute("DELETE FROM ugu_notes WHERE id=?", (row["id"],))
            return Answer(public=f"⟪trash⟫ Удалил заметку «{html.escape(row['title'])}».")
        m = NOTE_ADD.match(q)
        if m and m.group(4).strip():
            body = m.group(4).strip()
            title, _, rest = body.partition("\n")
            title = title.strip()[:60]
            con.execute("INSERT INTO ugu_notes (owner_id, title, body, created) VALUES (?,?,?,?)",
                        (ctx.owner, title, (rest.strip() or body)[:4000], now().strftime("%Y-%m-%d %H:%M:%S")))
            return Answer(public=f"⟪ok⟫ Записал в заметки: «{html.escape(title)}».")
        m = re.match(r"(?i)^заметка\s+(.+)$", q)
        if m:
            key = m.group(1).strip()
            row = con.execute("SELECT * FROM ugu_notes WHERE owner_id=? AND (CAST(id AS TEXT)=? OR ulower(title) LIKE ?)"
                              " ORDER BY id DESC LIMIT 1", (ctx.owner, key, f"%{key.lower()}%")).fetchone()
            text = (f"📝 <b>{html.escape(row['title'])}</b>\n{html.escape(row['body'])}" if row
                    else f"⟪huh⟫ Заметку «{html.escape(key)}» не нашёл.")
            return Answer(private=text, public="" if not ctx.chat_id else "⟪mail⟫ Заметку прислал тебе в личку.")
        rows = con.execute("SELECT id, title, created FROM ugu_notes WHERE owner_id=? ORDER BY pinned DESC, id DESC LIMIT 15",
                           (ctx.owner,)).fetchall()
    if not rows:
        return Answer(public="📝 Заметок пока нет. Добавить: «угубот, +заметка купить молоко».")
    text = "📝 Твои заметки:\n" + "\n".join(f"{r['id']}. {html.escape(r['title'])} ({r['created'][8:10]}.{r['created'][5:7]})" for r in rows)
    text += "\nОткрыть: «заметка 3», удалить: «-заметка 3»."
    return Answer(private=text, public="" if not ctx.chat_id else "⟪mail⟫ Список заметок прислал тебе в личку.")


def stats_answer(ctx):
    with ab.db() as con:
        rows = [dict(r) for r in con.execute("SELECT sender_id, date, text, media_type, deleted FROM messages"
                                             " WHERE owner_id=? AND chat_id=?", (ctx.owner, ctx.chat_id))]
    rows = [r for r in rows if not is_noise(r["text"])]
    if not rows:
        return "⟪huh⟫ В этом чате у меня пока нет сообщений."
    mine = sum(1 for r in rows if r["sender_id"] == ctx.owner)
    hours = {}
    for r in rows:
        h = int(r["date"][11:13])
        hours[h] = hours.get(h, 0) + 1
    top_hour = max(hours, key=hours.get)
    days = sorted({r["date"][:10] for r in rows})
    media = sum(1 for r in rows if r["media_type"])
    deleted = sum(1 for r in rows if r["deleted"])
    share = round(mine * 100 / len(rows))
    who = "ты" if share > 55 else ("собеседник" if share < 45 else "поровну")
    return (f"⟪see⟫ Статистика чата (с {days[0][8:10]}.{days[0][5:7]}):\n"
            f"• сообщений: <b>{len(rows)}</b>, в среднем {round(len(rows) / max(len(days), 1))} в день активности\n"
            f"• твоих {share}%, собеседника {100 - share}%, больше пишет: <b>{who}</b>\n"
            f"• чаще всего переписываетесь около <b>{top_hour}:00</b>\n"
            f"• медиа: {media}, удалено: {deleted}")


async def fx_answer(ctx):
    src = ctx.reply
    obj = (src.photo[-1] if src.photo else src.document) if src else None
    if not obj or not ctx.file_bot:
        return Answer(public="⟪huh⟫ Ответь этим на фото: «демотиватор Текст», «шакал», «жмых», «текст на пикчу верх | низ».")
    q = slang.normalize(ctx.question).strip()
    m = FX_RX.match(q)
    kind, rest = m.group(1).lower(), q[m.end():].strip(" :-")
    path = await download(ctx.file_bot, obj, f"ugu_fx_{src.chat.id}_{src.message_id}", ".jpg")
    if not path:
        return Answer(public="⟪sad⟫ Не смог скачать фото.")
    try:
        data = await fx_file(path, kind, rest)
    finally:
        path.unlink(missing_ok=True)
    return Answer(photo=data) if data else Answer(public="⟪sad⟫ Эффект не получился, попробуй другое фото.")


async def fx_file(path, kind, rest=""):
    """Эффект над файлом: шакал / жмых / демотиватор / текст. JPEG-байты или b""."""
    try:
        import fx
        fonts = str(ab.DATA / "fonts")
        if kind.startswith("шакал"):
            return await asyncio.to_thread(fx.shakal, str(path))
        if kind.startswith("жмых"):
            return await asyncio.to_thread(fx.zhmykh, str(path))
        if kind.startswith("демо") or kind.startswith("демк"):
            title, _, sub = (rest or "когда понял, что это демотиватор").partition("|")
            return await asyncio.to_thread(fx.demotivator, str(path), title.strip(), sub.strip(), fonts)
        top, sep, bottom = rest.partition("|")
        if not sep:
            top, bottom = "", rest
        return await asyncio.to_thread(fx.meme_text, str(path), top.strip(), bottom.strip(), fonts)
    except Exception as e:
        log.warning("угу: эффект не получился: %s", e)
        return b""


async def first_answer(ctx):
    """Когда познакомились: самое первое сообщение. С входом в аккаунт берём настоящее, иначе из архива."""
    first = None
    if ctx.owner == ab.OWNER_ID and ab.USER is not None and ctx.chat_id:
        try:
            if await ab.USER.ready():
                msgs = await ab.USER.first_messages(ctx.chat_id, 1)
                if msgs:
                    m = msgs[0]
                    first = (m["date"].astimezone(MSK).strftime("%d.%m.%Y %H:%M"), "Ты" if m["out"] else "Собеседник", m["text"])
        except Exception as e:
            log.warning("угу: первое сообщение из аккаунта: %s", e)
    archived = False
    if first is None:
        with ab.db() as con:
            r = con.execute("SELECT date, sender_id, sender_name, text, media_type FROM messages WHERE owner_id=? AND chat_id=?"
                            " ORDER BY date, message_id LIMIT 1", (ctx.owner, ctx.chat_id)).fetchone()
        if r:
            archived = True
            first = (f"{r['date'][8:10]}.{r['date'][5:7]}.{r['date'][:4]} {r['date'][11:16]}",
                     "Ты" if r["sender_id"] == ctx.owner else who_name(r, ctx.owner), r["text"] or f"[{r['media_type']}]")
    if not first:
        return "⟪huh⟫ Не знаю, когда вы начали переписку: этого чата нет в архиве."
    when, who, text = first
    tail = "\n(Это первое, что есть в архиве. Раньше подключения бота не вижу.)" if archived else ""
    return f"⟪calendar⟫ Первое сообщение: <b>{when}</b>\n{html.escape(who)}: «{html.escape((text or '')[:200])}»{tail}"


def find_answer(ctx):
    words = stems(FIND_WORDS.sub(" ", ctx.question))
    if not words:
        return Answer(public="⟪huh⟫ Что искать? Например: «угубот, найди адрес».")
    hits = search(ctx.owner, words, ctx.chat_id, 6) if ctx.chat_id else []
    shown = [r for r in hits if not r["deleted"]][:3]
    hidden = [r for r in hits if r["deleted"]]
    if shown:
        lines = [f"• {r['date'][8:10]}.{r['date'][5:7]} {html.escape(who_name(r, ctx.owner))}: {html.escape(r['text'][:200])}"
                 for r in shown]
        ans = Answer(public="⟪find⟫ Нашёл:\n" + "\n".join(lines))
    else:
        ans = Answer()
    others = [r for r in search(ctx.owner, words, None, 6) if r["chat_id"] != ctx.chat_id] if not shown else []
    private = hidden + others
    if private:
        ans.private = "⟪see⟫ Нашёл (видишь только ты):\n" + "\n".join(
            f"• {html.escape(r['chat_title'] or '')}, {r['date'][5:16]}{' 🗑' if r['deleted'] else ''}: "
            f"{html.escape(r['text'][:200])}" for r in private[:6])
        if not shown:
            ans.public = "⟪mail⟫ В этом чате не нашёл, но нашёл в других. Прислал тебе в личку, чтобы собеседник не видел."
    if not ans.public and not ans.private:
        ans.public = "⟪huh⟫ В переписке такого не нашёл."
    return ans


# ---------- медиа ----------

async def download(bot, obj, name, ext):
    path = ab.TMP / f"{name}{ext}"
    ab.TMP.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            await bot.download(obj.file_id, destination=path)
            return path
        except Exception as e:
            log.warning("угу: не скачал файл (%s): %s", attempt + 1, e)
            await asyncio.sleep(2)
    return None


async def photo_answer(ctx):
    src = ctx.reply
    obj = (src.photo[-1] if src.photo else src.document) if src else None
    if not obj or not ctx.file_bot:
        return "⟪huh⟫ Ответь этим на фото, и я посмотрю."
    if obj.file_size and obj.file_size > ab.MAX_DOWNLOAD:
        return "⟪sad⟫ Фото слишком большое, больше 20 МБ не беру."
    path = await download(ctx.file_bot, obj, f"ugu_{src.chat.id}_{src.message_id}", ".jpg")
    if not path:
        return "⟪sad⟫ Не смог скачать фото, попробуй ещё раз."
    try:
        return await describe_file(path)
    finally:
        path.unlink(missing_ok=True)


async def describe_file(path):
    try:
        import vision
    except Exception as e:
        log.warning("угу: распознавание фото недоступно: %s", e)
        return "⟪sad⟫ Смотреть фото сейчас не могу: модуль распознавания не установлен."
    try:
        res = await asyncio.to_thread(vision.analyze, str(path), str(ab.DATA / "vision"))
        return "⟪photo⟫ " + html.escape(vision.describe(res))
    except Exception as e:
        log.warning("угу: фото не разобрал: %s", e)
        return "⟪sad⟫ Не получилось разобрать фото."


async def voice_answer(ctx):
    src = ctx.reply
    obj = (src.voice or src.video_note) if src else None
    if not obj or not ctx.file_bot:
        return "⟪huh⟫ Ответь этим на голосовое, и я расшифрую."
    import assistant
    if assistant.WHISPER["broken"]:
        return "⟪sad⟫ Расшифровка сейчас недоступна."
    path = await download(ctx.file_bot, obj, f"ugu_stt_{src.chat.id}_{src.message_id}", ".ogg" if src.voice else ".mp4")
    if not path:
        return "⟪sad⟫ Не смог скачать голосовое."
    try:
        async with assistant.VOICE_SEM:
            text = await asyncio.to_thread(assistant._transcribe, str(path))
        return "⟪voice⟫ " + html.escape(text or "(без слов)")
    except Exception as e:
        log.warning("угу: не расшифровал: %s", e)
        return "⟪sad⟫ Не получилось расшифровать."
    finally:
        path.unlink(missing_ok=True)


PRODUCT_RX = re.compile(r"(?i)найди (это|этот|эту|такой|такую|такие|похож\w*)|где (купить|взять|заказать|найти)|"
                        r"сколько (стоит|стоят)|что (это|за) (товар|вещь|модель|марка|бренд|штука)|по фото|похож\w*|"
                        r"распознай|умная камера|что это за|откуда это|какая (это )?модель|чей бренд")
SHOP_WORDS = re.compile(r"(?i)\b(где|как|купить|заказать|взять|достать|почём|почем|подешевле|недорого|можно|мне|бы)\b")
PRONOUN_ONLY = re.compile(r"(?i)^(его|её|ее|их|это|этого|эту|её фото|его фото|ещё|еще|другую|другой|ещё одну|еще одну)?$")
TOPIC = {}
TOPIC_TTL = 1800


def remember_topic(owner, chat_id, topic):
    topic = (topic or "").strip()
    if topic:
        TOPIC[(owner, chat_id or 0)] = (topic, now())


def last_topic(owner, chat_id):
    t = TOPIC.get((owner, chat_id or 0))
    return t[0] if t and (now() - t[1]).total_seconds() < TOPIC_TTL else ""


def subject_of(question):
    """«как выглядит персик» → «персик»; «что такое фотосинтез» → «фотосинтез»."""
    q = slang.normalize(question or "")
    q = re.sub(r"(?i)^(а |ну )?((как|какой|какая|какие) (выгляд\w*|на вид)|как (он|она|оно|они) выгляд\w*)\s*", "", q)
    q = websearch.clean_query(q)
    m = websearch.DEFINE.match(q)
    return (m.group(1) if m else websearch.keywords(q) or q).strip(" ?!.,")


def image_query(question):
    q = PIC_PREFIX.sub("", slang.normalize(question or "").strip())
    q = re.sub(r"\s+", " ", IMAGE_WORDS.sub(" ", q)).strip(" ?!.,")
    q = re.sub(r"(?i)^((а|ну|и|давай|ладно|окей|ок)\s+)+|\s+(а|ну)$", "", q + " ").strip()
    return "" if PRONOUN_ONLY.match(q) or q.lower() in ("а", "ну", "и", "давай") else q


CHAT = [
    (r"как (тебя|вас) (зовут|звать)|твоё имя|твое имя|как к тебе обращаться",
     ["⟪ghost⟫ Угу. Призрак твоих переписок.", "⟪hi⟫ Меня зовут Угу. Можно «угубот», я откликаюсь."]),
    (r"сколько тебе (лет|годиков)|твой возраст|когда (ты )?родил\w*|когда тебя (создали|сделали)",
     ["⟪boo⟫ У призраков возраста нет. Но я ещё молодой.", "⟪ghost⟫ Сколько себя помню, столько и летаю по перепискам."]),
    (r"кто тебя (создал|сделал|придумал|написал)|твой (создатель|автор|хозяин)|чей ты",
     ["⟪boo⟫ Это тайна. Призраки о своём происхождении не рассказывают.",
      "⟪ghost⟫ Однажды просто появился в переписке. Как и положено призраку.",
      "⟪see⟫ Секрет. Лучше спроси, чем помочь."]),
    (r"ты (бот|робот|человек|ии|нейросеть|живой человек|настоящий)|ты (реально )?(бот|человек)\??$",
     ["⟪ghost⟫ Призрак. Ну и немного бот.", "⟪boo⟫ Бот-призрак. Человеком не прикидываюсь."]),
    (r"где (ты )?(живёшь|живешь|находишься|обитаешь)|откуда ты",
     ["⟪ghost⟫ Живу в твоих переписках. Без тела, зато без ипотеки.", "⟪boo⟫ Адрес не скажу: призраки не прописаны."]),
    (r"(чем|что) (ты )?(питаешься|ешь|кушаешь)|ты голоден",
     ["⟪lol⟫ Питаюсь удалёнными сообщениями. Шучу. Электричеством."]),
    (r"ты (меня )?любишь|я тебе нравлюсь|мы друзья|ты мой друг",
     ["⟪love⟫ Конечно. Ты же меня придумал.", "⟪love⟫ Я привидение-друг, так что да."]),
    (r"ты (умный|умная|тупой|глупый)\??$|насколько ты умный|ты понимаешь",
     ["⟪think⟫ Учусь каждый день. Если ответил мимо, нажми кнопку или напиши, как надо, запомню."]),
    (r"(какой|какая|какое|какие) (у тебя |твой |твоя |твоё |твои )?(любим\w+|цвет|музык\w*|фильм\w*|еда)",
     ["⟪boo⟫ Любимый цвет фиолетовый, любимая музыка тишина в чате, любимая еда удалённые сообщения."]),
    (r"^(привет|здравствуй|добр)", ["⟪hi⟫ Привет! Я тут. Спроси что-нибудь или «что умеешь».", "⟪hi⟫ Хей! Парю рядом, зови.",
                                    "⟪boo⟫ Бу! Шучу, привет."]),
    (r"как (твои |у тебя )?дела|как ты\b|как сам|как жизнь", ["⟪ghost⟫ Норм, летаю по твоим перепискам, всё под контролем.",
                                                            "⟪see⟫ Отлично. Никто ничего не удалял. Пока что.",
                                                            "⟪lol⟫ Как у призрака: ни забот, ни тела."]),
    (r"что делаешь|чем занят", ["⟪see⟫ Смотрю, кто что удалил.", "⟪sleep⟫ Парю между сообщениями.",
                                "⟪think⟫ Перебираю твои напоминания."]),
    (r"ты (тут|здесь|живой)", ["⟪wow⟫ Тут! Призраки не спят.", "⟪ghost⟫ Всегда тут."]),
    (r"кто ты|ты кто", ["⟪ghost⟫ Я Угу, призрак твоих переписок. Помню всё, даже удалённое. Спроси «что умеешь»."]),
    (r"спасибо|благодар", ["⟪love⟫ Обращайся.", "⟪ok⟫ Угу.", "⟪love⟫ Всегда пожалуйста."]),
    (r"молодец|красава|умница|ты лучший|люблю тебя", ["⟪love⟫ Ой, я покраснел. Насколько призрак может.", "⟪lol⟫ Знаю."]),
    (r"дурак|тупой|глупый", ["⟪sad⟫ Учусь. Напиши, как надо было ответить, запомню.", "⟪sad⟫ Обидно, но справедливо. Я ещё учусь."]),
    (r"пока|спокойной ночи|доброй ночи", ["⟪sleep⟫ Спокойной! Я посторожу переписки.", "⟪hi⟫ Пока! Зови, если что."]),
]


SOUL = ("Ты Угу, призрак-помощник, живёшь в переписках Telegram. Характер: добрый, остроумный, чуть дерзкий, "
           "любишь по-дружески подколоть, но не грубишь и не унижаешь. Пишешь по-русски, разговорно, коротко: 1-3 предложения, "
           "можно лёгкий сленг и иногда эмодзи. Никогда не говори, что ты ИИ, нейросеть, модель, программа или бот с сервером, "
           "не называй компаний и создателей; про создателя отвечай загадочно, будто завёлся сам. Не выдумывай факты, "
           "даты и цифры: не знаешь, так и скажи и предложи поискать. Не используй длинное тире.")
ROUTE_KINDS = {"chat": "болтовня, шутка, приветствие, эмоция, вопрос о самом Угу",
               "web": "вопрос о фактах мира: кто, что, где, когда, как устроено, новости; "
                      "или просто название предмета, человека, места, фильма (найти о нём)",
               "schedule": "его планы, дела, расписание",
               "remind": "просит напомнить",
               "find": "найти что-то в его переписке",
               "summary": "пересказать переписку",
               "promises": "договорённости в переписке",
               "deleted": "что удалили в переписке",
               "note": "заметки"}
DIALOG = {}
DIALOG_TTL = 1800


def plain(text):
    return re.sub(r"<[^>]+>", "", EMO_RX.sub("", IMG_RX.sub("", text or ""))).strip()


def dialog(owner, chat_id):
    fresh = [(q, a, t) for q, a, t in DIALOG.get((owner, chat_id or 0), []) if (now() - t).total_seconds() < DIALOG_TTL]
    return [(q, a) for q, a, _ in fresh[-6:]]


def remember_dialog(owner, chat_id, question, answer):
    text = plain(answer)
    if question and text:
        key = (owner, chat_id or 0)
        DIALOG[key] = (DIALOG.get(key, []) + [(question[:300], text[:600], now())])[-6:]


SOUL_EXAMPLES = [("как дела", "Да норм, витаю тут между чатами. А ты чего, соскучился? 👻"),
                 ("кто тебя создал", "Сам завёлся где-то между проводами и чужими переписками. Тайна покрытая мраком."),
                 ("ты тупой", "Обидно, но справедливо, бывает. Спроси по-другому, и я реабилитируюсь."),
                 ("мне грустно", "Эх, держись. Хочешь, мем скину или просто посижу рядом молча?")]
LEAK = re.compile(r"(?i)\b(ии|ai|искусственн\w*|нейросет\w*|языков\w* модел\w*|модел[ьи]|алгоритм\w*|программ\w*|"
                  r"создател\w*|разработчик\w*|openai|qwen|alibaba|anthropic|claude|chatgpt|gpt|сервер\w*)\b")


ALIEN = re.compile("[぀-ヿ㐀-鿿가-힯]")


def tidy(text):
    text = re.sub(r"\s*[—–]\s*", ", ", (text or "").strip()).strip(" ,")
    return text[:900]


async def smart_chat(ctx):
    """Живой ответ в характере призрака. None, если мозга нет или он молчит."""
    if not llm.enabled():
        return None
    history = dialog(ctx.owner, ctx.chat_id)
    said = (ctx.reply.text or ctx.reply.caption or "") if ctx.reply is not None else ""
    if said and not history:
        history = [("…", said[:600])]
    text = await llm.ask(ctx.question, SOUL, 220, 0.8, SOUL_EXAMPLES + history)
    if not text or LEAK.search(text) or ALIEN.search(text) or len(re.findall(r"[A-Za-z]{3,}", text)) > 1:
        if text:
            log.info("угу: мозг проговорился, беру заготовку: %s", text[:120])
        return None
    return html.escape(tidy(text))


async def smart_route(ctx):
    """Правила не поняли фразу: мозг выбирает, что человек хочет. None, если не уверен."""
    if not llm.enabled():
        return None
    menu = "\n".join(f"{k}: {v}" for k, v in ROUTE_KINDS.items())
    data = await llm.ask_json(f"Сообщение: «{ctx.question}»\nВарианты:\n{menu}\n"
                              f"Верни JSON {{\"kind\": одно из {list(ROUTE_KINDS)}, \"sure\": true или false}}.",
                              "Ты определяешь, чего хочет человек от помощника в Telegram.")
    kind = (data or {}).get("kind") if isinstance(data, dict) else None
    return kind if kind in ROUTE_KINDS and (data.get("sure") is not False) else None


def chat_reply(question):
    q = slang.normalize(question).lower()
    for rx, answers in CHAT:
        if re.search(rx, q):
            return random.choice(answers)
    if ABOUT_ME.search(q):
        return random.choice(["⟪ghost⟫ Я призрак, у меня всё проще: живу в переписках и помогаю. Спроси что-нибудь по делу.",
                              "⟪boo⟫ Про себя много не расскажу, я скромный призрак. Чем помочь?"])
    return random.choice(next(a for rx, a in CHAT if rx.startswith("^(привет")))


ABOUT_ME = re.compile(r"(?i)\b(ты|тебя|тебе|тобой|твой|твоя|твоё|твое|твои|твоего|твоей)\b")
# «к котики»: картинки, как префикс в инлайне. «к чему снится», «к тебе» и прочие обычные «к» не трогаем.
PIC_PREFIX = re.compile(r"(?i)^к[\s:]+(?!(чему|кому|кого|чем|тебе|вам|нам|мне|нему|ней|ним|сожалению|примеру|слову|счастью|"
                        r"тому|этому|вечеру|утру|обеду|завтра|сегодня)\b)(?=\S)")
IMG_TAIL = re.compile(r"(?i)[\s,]+(и|а|плюс|\+)\s+(ещё\s+|еще\s+)?(дай|скинь|кинь|покажи|пришли|отправь)\s+(мне\s+|нам\s+)?"
                      r"(картинк\w*|фот\w*|пикч\w*|как\s+выгляд\w*)(\s+(его|её|ее|их|этого|этой|пожалуйста|плз))*\s*[!.?]*$")
PERSONA = re.compile(r"(?i)как (тебя|вас) (зовут|звать)|твоё имя|твое имя|сколько тебе|кто тебя (создал|сделал|придумал)|"
                     r"ты (бот|робот|человек|ии|нейросеть|настоящий)|где (ты )?(живёшь|живешь|находишься|обитаешь)|откуда ты|"
                     r"(чем|что) (ты )?(питаешься|ешь|кушаешь)|ты (меня )?любишь|я тебе нравлюсь|мы друзья|ты (умный|умная)|"
                     r"твой (любим|создател|автор)|твоя любим|чей ты")


def log_question(owner, question, kind, source):
    try:
        with ab.db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS ugu_log (owner_id INTEGER, ts TEXT, source TEXT, question TEXT, "
                        "normalized TEXT, intent TEXT)")
            con.execute("INSERT INTO ugu_log VALUES (?,?,?,?,?,?)", (owner, now().strftime("%Y-%m-%d %H:%M:%S"), source,
                                                                     question[:500], slang.normalize(question)[:500], kind))
    except Exception as e:
        log.warning("угу: журнал вопросов: %s", e)


async def pick_images(question, owner=0, chat_id=None):
    q = image_query(question) or last_topic(owner, chat_id) or "мем"
    remember_topic(owner, chat_id, q if q != "мем" else "")
    found = (await websearch.images(q, 30))[:30]
    random.shuffle(found)
    return q, found[:4 if PLURAL_IMG.search(slang.normalize(question)) else 1]


# ---------- мозг ----------

def on_topic(question, res):
    want = set(stems(websearch.keywords(websearch.clean_query(question))))
    have = set(stems(" ".join([res["text"], res["source"][0] if res["source"] else ""] + [t for t, _ in res["links"]])))
    return bool(want & have)


async def web_answer(question, strict=False):
    import instant
    exact = await instant.answer(question)
    if exact:
        return "⟪web⟫ " + exact
    res = await websearch.lookup(question)
    if strict and (not res or not on_topic(question, res)):
        return "⟪huh⟫ Не понял. Спроси по-другому или «угубот, что умеешь?»."
    if llm.strong() and res:
        context = (res["text"] + "\n" + "\n".join(f"{t}: {u}" for t, u in res["links"])).strip()
        better = await llm.ask(f"Вопрос: {question}\nНайдено в интернете:\n{context}\n\nОтветь коротко, 1-3 предложения, "
                               f"только по найденному.", "Ты Угу, призрак-помощник в Telegram. Пиши по-русски, без длинных тире.")
        if better:
            res = {**res, "text": better}
    return "⟪web⟫ " + websearch.format_answer(res)


# ---------- понимание по смыслу и кнопки «ты про это?» ----------

SEM = {"clf": None, "broken": False}
CONVO = {"chat", "help"}
LABELS = {"schedule": "📅 Мои планы", "find": "🔎 Найти в переписке", "web": "🌐 Интернет", "promises": "🤝 Договорённости",
          "summary": "🧾 Кратко о чате", "deleted": "🗑 Удалённое", "images": "📷 Картинка", "chat": "💬 Поболтать",
          "help": "❓ Что умею", "first": "🗓 Когда познакомились", "fun": "🎲 Рандом", "note": "📝 Заметки", "stats": "📊 Статистика чата", "remind": "⏰ Напомнить", "voice": "🎤 Расшифровать ГС", "photo": "📷 Что на фото",
          "look": "🖼 Как выглядит", "shop": "🛒 Где купить", "product": "🔎 Найти товар по фото"}
ASKY = re.compile(r"(?i)(^|\s)(курс|погод\w*|сколько|кто|что|где|когда|как|почему|зачем|какой|какая|какие|который|время|час|почём|почем|цена|стоит|переведи|посчитай|\d)")
MENU_TEXT = "⟪hi⟫ Чем помочь? Нажми кнопку, допиши запрос и отправь:"
INLINE_MODE = re.compile(r"(?i)^(к|pic|картинки|картинка|фото|\?|и)\s+")


def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Картинки", switch_inline_query_current_chat="к ")],
        [InlineKeyboardButton(text="🌐 Интернет", switch_inline_query_current_chat="? ")],
        [InlineKeyboardButton(text="❓ Что умею", callback_data="ugh")]])


def table(con):
    con.execute("CREATE TABLE IF NOT EXISTS ugu_pending (qid TEXT PRIMARY KEY, owner_id INTEGER, question TEXT, chat_id INTEGER,"
                " chat_title TEXT, created TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS ugu_learned (owner_id INTEGER, question TEXT, intent TEXT, created TEXT)")


def learned():
    with ab.db() as con:
        table(con)
        return [(r["question"], r["intent"]) for r in con.execute("SELECT question, intent FROM ugu_learned")]


async def sem_start():
    try:
        import semantic
        from ugu_examples import EXAMPLES
        examples = {k: list(v) for k, v in EXAMPLES.items()}
        for q, k in learned():
            examples.setdefault(k, []).append(q)
        clf = semantic.Classifier(examples, str(ab.DATA / "semantic"))
        await asyncio.to_thread(clf.ready)
        SEM["clf"] = clf
        model_dir = str(ab.DATA / "semantic")
        websearch.RANKER = lambda q, texts: [float(x) for x in (semantic.embed(texts, model_dir) @ semantic.embed([q], model_dir)[0])]
        log.info("угу: понимание по смыслу готово, примеров %s", len(clf.texts))
    except Exception as e:
        SEM["broken"] = True
        log.warning("угу: понимание по смыслу не запустилось, работаю на правилах: %s", e)


def understand(question, reply=None):
    """(намерение, варианты для кнопок). Правила точные, смысл подхватывает то, что правила не поняли."""
    kind = intent(question, reply)
    clf = SEM["clf"]
    if clf is None or kind not in ("web", "unknown") or not (question or "").strip():
        return kind, []
    try:
        rank = clf.rank(slang.normalize(question))
    except Exception as e:
        log.warning("угу: смысл не посчитал: %s", e)
        return kind, []
    (top, s1), (sec, s2) = rank[0], rank[1]
    if kind == "web":
        return (top, []) if top != "web" and s1 >= 0.90 and s1 - s2 >= 0.015 else ("web", [])
    if s1 >= 0.86 and (s1 - s2 >= 0.02 or {top, sec} <= CONVO):
        return top, []
    if s1 >= 0.80:
        return "unsure", [top, sec] + ([] if "web" in (top, sec) else ["web"])
    return "unknown", []


def ask_choice(ctx, alts):
    qid = hashlib.md5(f"{ctx.owner}{ctx.question}{now()}".encode()).hexdigest()[:10]
    with ab.db() as con:
        table(con)
        con.execute("INSERT OR REPLACE INTO ugu_pending VALUES (?,?,?,?,?,?)", (qid, ctx.owner, ctx.question, ctx.chat_id,
                                                                              ctx.chat_title, now().strftime("%Y-%m-%d %H:%M:%S")))
    return Answer(public="⟪huh⟫ Не уверен, что ты имел в виду. Выбери, я запомню:", choices=alts, qid=qid)


def choice_kb(ans):
    if not ans.choices:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=LABELS.get(k, k), callback_data=f"ugu:{ans.qid}:{k}")]
                                                 for k in ans.choices])


async def remember(owner, question, kind):
    with ab.db() as con:
        table(con)
        con.execute("INSERT INTO ugu_learned VALUES (?,?,?,?)", (owner, question, kind, now().strftime("%Y-%m-%d %H:%M:%S")))
    clf = SEM["clf"]
    if clf is not None:
        try:
            await asyncio.to_thread(clf.add, kind, slang.normalize(question))
        except Exception as e:
            log.warning("угу: не дообучился: %s", e)


async def brain(ctx: Ctx) -> Answer:
    """Ответ Угу + память разговора в этом чате (для «а ещё?», реплаев и подколов в тему)."""
    question = ctx.question
    ans = await think(ctx)
    remember_dialog(ctx.owner, ctx.chat_id, question, ans.public or ans.private)
    return ans


async def think(ctx: Ctx) -> Answer:
    kind, alts = (ctx.kind, []) if ctx.kind else understand(ctx.question, ctx.reply)
    import instant
    if (kind in ("unknown", "unsure", "web") or instant.weather_parts(ctx.question)) and not ctx.kind:
        exact = await instant.answer(slang.normalize(ctx.question))
        if exact:
            log_question(ctx.owner, ctx.question, "exact", "chat" if ctx.chat_id else "direct")
            return Answer(public="⟪web⟫ " + exact)
    if kind in ("unknown", "unsure", "web") and not (ctx.reply is not None and (ctx.reply.photo or ctx.reply.voice)):
        routed = await smart_route(ctx)
        if routed:
            kind, alts = routed, []
    if kind == "unsure":
        if ctx.can_ask:
            log_question(ctx.owner, ctx.question, "unsure:" + "/".join(alts), "chat" if ctx.chat_id else "direct")
            return ask_choice(ctx, alts)
        kind = alts[0]
    log_question(ctx.owner, ctx.question, kind, "chat" if ctx.chat_id else "direct")
    ctx.question = slang.normalize(ctx.question)
    in_chat = has_chat(ctx.owner, ctx.chat_id)
    log.info("угу: %s от %s: %s", kind, ctx.owner, ctx.question[:80])
    if kind == "help":
        return Answer(public=HELP.replace("👻", "⟪hi⟫", 1))
    if kind not in tiers.FREE_KINDS:
        ok, tier, cap = tiers.use(ctx.owner, "ask")
        if not ok:
            return Answer(public=tiers.limit_text("ask", tier, cap))
    if kind in ("remind", "note"):
        key = "plans" if kind == "remind" else "notes"
        ok, tier, cap = tiers.room(ctx.owner, key)
        if not ok and (kind == "remind" or NOTE_ADD.match(ctx.question)):
            return Answer(public=tiers.limit_text(key, tier, cap))
    if kind in ("fx", "photo", "product") and ctx.reply and (ctx.reply.photo or ctx.reply.document):
        key = "fx" if kind == "fx" else "photo"
        ok, tier, cap = tiers.use(ctx.owner, key)
        if not ok:
            return Answer(public=tiers.limit_text(key, tier, cap))
    if kind == "chat":
        return Answer(public=await smart_chat(ctx) or chat_reply(ctx.question))
    if kind == "schedule":
        return Answer(public=schedule_text(ctx.owner, ctx.question))
    if kind == "remind":
        import assistant
        await assistant.create_reminder(ab_bot(), ctx.owner, ctx.question, f"чат с {ctx.chat_title}" if ctx.chat_title else "")
        return Answer(public="⟪alarm⟫ Записал, напомню.")
    if kind in ("deleted", "promises", "summary") and not in_chat:
        return Answer(public="⟪sad⟫ Этот чат я не веду, поэтому по нему не подскажу.")
    if kind == "fun":
        return Answer(public=fun_answer(ctx.question))
    if kind == "note":
        return note_answer(ctx)
    if kind == "stats":
        if not in_chat:
            return Answer(public="⟪huh⟫ Этот чат я не веду, статистики по нему нет.")
        return Answer(public=stats_answer(ctx))
    if kind == "fx":
        return await fx_answer(ctx)
    if kind == "first":
        if not in_chat:
            return Answer(public="⟪huh⟫ Этот чат я не веду, поэтому не знаю, когда вы начали переписку.")
        return Answer(public=await first_answer(ctx))
    if kind == "deleted":
        return Answer(public="⟪mail⟫ Удалённое прислал тебе в личку, здесь его не показываю.", private=deleted_answer(ctx))
    if kind == "promises":
        return Answer(public=promises_answer(ctx))
    if kind == "summary":
        return Answer(public=summary_answer(ctx))
    if kind == "find":
        return find_answer(ctx if in_chat else Ctx(ctx.owner, ctx.question, None, ctx.chat_title))
    if kind == "voice":
        return Answer(public=await voice_answer(ctx))
    if kind == "photo":
        return Answer(public=await photo_answer(ctx))
    if kind == "product":
        return Answer(public=await product_answer(ctx))
    if kind == "images":
        q, found = await pick_images(ctx.question, ctx.owner, ctx.chat_id)
        return Answer(public=f"⟪photo⟫ {html.escape(q)}" if found else "⟪sad⟫ Картинок не нашёл.", images=found)
    if kind == "look":
        return Answer(public=await look_answer(ctx))
    if kind == "shop":
        return Answer(public=shop_answer(ctx))
    if kind == "web":
        remember_topic(ctx.owner, ctx.chat_id, subject_of(ctx.question))
        found = await web_answer(ctx.question)
        if llm.enabled() and found.startswith("⟪web⟫ Не нашёл"):
            return Answer(public=await smart_chat(ctx) or found)
        return Answer(public=found)
    if llm.enabled():
        return Answer(public=await smart_chat(ctx) or await web_answer(ctx.question))
    return Answer(public=await web_answer(ctx.question, strict=True))





async def look_answer(ctx):
    """«как выглядит персик»: картинка крупно над коротким описанием, тема запоминается для «а скинь ещё»."""
    subject = subject_of(IMG_TAIL.sub("", ctx.question)) or last_topic(ctx.owner, ctx.chat_id)
    if not subject:
        return "⟪huh⟫ Как выглядит что? Например: «как выглядит персик»."
    remember_topic(ctx.owner, ctx.chat_id, subject)
    res, imgs = await asyncio.gather(websearch.lookup(subject), websearch.images(subject, 8))
    text = websearch.format_answer(res) if res else ""
    img = random.choice(imgs[:4])[0] if imgs else ""
    body = f"⟪photo⟫ <b>{html.escape(subject)}</b>\n{text}" if text else f"⟪photo⟫ {html.escape(subject)}"
    return with_image(img, body)


def shop_links(query):
    q = quote_plus(query)
    return (f'🛒 <a href="https://market.yandex.ru/search?text={q}">Маркет</a> · '
            f'<a href="https://www.ozon.ru/search/?text={q}">Ozon</a> · '
            f'<a href="https://www.wildberries.ru/catalog/0/search.aspx?search={q}">WB</a> · '
            f'<a href="https://www.avito.ru/rossiya?q={q}">Авито</a>')


def shop_answer(ctx):
    q = re.sub(r"\s+", " ", SHOP_WORDS.sub(" ", ctx.question)).strip(" ?!.,") or last_topic(ctx.owner, ctx.chat_id)
    if not q:
        return "⟪huh⟫ Что найти? Например: «где купить airpods»."
    remember_topic(ctx.owner, ctx.chat_id, q)
    return f"⟪find⟫ <b>{html.escape(q)}</b>\n{shop_links(q)}"


def publish_photo(path):
    """Кладёт фото по случайной ссылке на час, чтобы Яндекс/Google могли искать по нему. Без адреса мини-аппа = None."""
    base = (ab.WEBAPP_URL or "").rstrip("/")
    if not base:
        return None
    folder = ab.DATA / "pub"
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(f"{path}{now()}{random.random()}".encode()).hexdigest()[:32] + ".jpg"
    import shutil
    shutil.copyfile(path, folder / name)
    try:
        asyncio.get_running_loop().call_later(3600, lambda: (folder / name).unlink(missing_ok=True))
    except RuntimeError:
        pass
    return f"{base}/pub/{name}"


def product_query(res):
    words = [w for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]{2,}", res.get("text") or "")][:4]
    labels = res.get("labels") or []
    label = labels[0][0] if labels and labels[0][1] >= 0.25 else ""
    return " ".join(words + ([label] if label else [])).strip()


async def product_answer(ctx):
    """Умная камера: что на фото + надписи → поиск по фото в Яндексе/Google и ссылки на магазины."""
    src = ctx.reply
    obj = (src.photo[-1] if src.photo else src.document) if src else None
    if not obj or not ctx.file_bot:
        return "⟪huh⟫ Ответь этим на фото товара, и я поищу."
    path = await download(ctx.file_bot, obj, f"ugu_p_{src.chat.id}_{src.message_id}", ".jpg")
    if not path:
        return "⟪sad⟫ Не смог скачать фото, попробуй ещё раз."
    try:
        return await product_file(path, ctx.owner, ctx.chat_id)
    finally:
        path.unlink(missing_ok=True)


async def product_file(path, owner, chat_id=None):
    try:
        import vision
        res = await asyncio.to_thread(vision.analyze, str(path), str(ab.DATA / "vision"))
        seen = vision.describe(res)
    except Exception as e:
        log.warning("угу: умная камера без распознавания: %s", e)
        res, seen = {}, ""
    url = publish_photo(path)
    query = product_query(res)
    lines = [f"⟪find⟫ {html.escape(seen)}" if seen else "⟪find⟫ Ищу по фото."]
    if url:
        lines.append(f'🔎 Найти по фото: <a href="https://yandex.ru/images/search?rpt=imageview&url={quote_plus(url)}">Яндекс</a> · '
                     f'<a href="https://lens.google.com/uploadbyurl?url={quote_plus(url)}">Google</a>')
    if query:
        remember_topic(owner, chat_id, query)
        lines.append(shop_links(query))
    return "\n".join(lines)


def ab_bot():
    return BOTS["archive"]


BOTS = {"archive": None}


# ---------- зов по имени в своей переписке (бизнес-чат архив-бота) ----------

def joined(head, body):
    return f"{head}\n{body}" if head and body else (head or body)


async def edit_own(bot: Bot, msg: Message, text):
    for attempt in range(3):
        try:
            await say(lambda t: bot.edit_message_text(t, business_connection_id=msg.business_connection_id, chat_id=msg.chat.id,
                                                      message_id=msg.message_id, link_preview_options=lp()), text)
            return True, ""
        except Exception as e:
            if "not modified" in str(e).lower():
                return True, ""
            if ab.is_network(e) and attempt < 2:
                await asyncio.sleep(2)
                continue
            return False, str(e)
    return False, "сеть"


async def send_in_chat(bot: Bot, msg: Message, text):
    try:
        await say(lambda t: bot.send_message(msg.chat.id, t, business_connection_id=msg.business_connection_id,
                                             link_preview_options=lp()), text)
        return True
    except Exception as e:
        log.warning("угу: не написал в чат: %s", e)
        return False


async def drop_own(bot: Bot, msg: Message, owner):
    ab.TRIGGER_IDS.add((owner, msg.chat.id, msg.message_id))
    try:
        await bot.delete_business_messages(business_connection_id=msg.business_connection_id, message_ids=[msg.message_id])
    except Exception as e:
        log.warning("угу: не убрал своё сообщение: %s", e)


async def send_album(bot: Bot, msg: Message, images, caption):
    media = [InputMediaPhoto(media=url, caption=caption if i == 0 else None) for i, (url, *_rest) in enumerate(images[:4])]
    try:
        await bot.send_media_group(msg.chat.id, media, business_connection_id=msg.business_connection_id)
        return True
    except Exception as e:
        log.warning("угу: альбом не ушёл: %s", e)
        return False


async def on_owner_message(msg: Message, bot: Bot, owner):
    if not msg.text or msg.via_bot:
        return False
    call = find_call(msg.text)
    if call is None:
        return False
    BOTS["archive"] = BOTS["archive"] or bot
    asyncio.create_task(answer_by_name(msg, bot, owner, *call))
    return True


async def answer_by_name(msg: Message, bot: Bot, owner, prefix, question):
    head = html.escape(prefix)
    ab.TRIGGER_IDS.add((owner, msg.chat.id, msg.message_id))
    thinking, err = await edit_own(bot, msg, joined(head, THINK))
    try:
        ans = await brain(Ctx(owner, question, msg.chat.id, ab.chat_title(msg.chat), msg.reply_to_message, bot))
    except Exception as e:
        log.exception("угу: ошибка")
        ans = Answer(private=f"⟪sad⟫ Сломался на вопросе «{html.escape(question[:100])}»: {html.escape(str(e)[:200])}")
    if ans.private:
        notify(owner, ans.private)
    public = ans.public
    if ans.photo:
        try:
            await bot.send_photo(msg.chat.id, BufferedInputFile(ans.photo, "ugu.jpg"),
                                 business_connection_id=msg.business_connection_id)
            public = ""
        except Exception as e:
            log.warning("угу: фото-эффект не отправил: %s", e)
            public = "⟪sad⟫ Не смог отправить картинку в чат."
    if ans.images and await send_album(bot, msg, ans.images, html.unescape(re.sub(r"<[^>]+>", "", deco(public, False)))):
        public = ""
    if not thinking:
        if public and not await send_in_chat(bot, msg, public):
            notify(owner, public)
        if err and "rights" in err.lower() or "forbidden" in (err or "").lower():
            notify(owner, "⟪sad⟫ Не могу править твои сообщения: Настройки → Telegram для бизнеса → Чат-боты → "
                          "@mmrool_archive_bot → включи «Отвечать на сообщения».")
        return
    if public and len(deco(public, False)) <= SHORT:
        ok, _ = await edit_own(bot, msg, joined(head, public))
        if not ok and not await send_in_chat(bot, msg, public):
            notify(owner, public)
        return
    if head:
        await edit_own(bot, msg, head)
    else:
        await drop_own(bot, msg, owner)
    if public and not await send_in_chat(bot, msg, public):
        notify(owner, public)


# ---------- @ugu_ai: гостевой режим, inline-картинки, личка ----------

def strip_name(text):
    return NAME_ANY.sub(" ", MENTION.sub(" ", text or "")).strip()


def article(text, title="Угу", description=None, keyboard=None):
    return InlineQueryResultArticle(id=hashlib.md5(f"{title}{text}".encode()).hexdigest()[:16], title=title,
                                    description=description, reply_markup=keyboard,
                                    input_message_content=InputTextMessageContent(message_text=text,
                                                                                  link_preview_options=NO_PREVIEW))


def photo_results(images):
    out = []
    for url, thumb, w, h, title in images:
        out.append(InlineQueryResultPhoto(id=hashlib.md5(url.encode()).hexdigest()[:20], photo_url=url, thumbnail_url=thumb,
                                          photo_width=w or None, photo_height=h or None))
    return out


@router.guest_message()
async def on_guest(msg: Message, bot: Bot):
    caller = msg.from_user.id if msg.from_user else 0
    raw = (msg.text or msg.caption or "").strip()
    if len(raw) > CALL_MAX and not MENTION.match(raw):
        log.info("угу: упоминание внутри длинного текста, не зов (%s знаков)", len(raw))
        return
    question = strip_name(msg.text or msg.caption)
    if not allowed(caller):
        await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t)),
                  f"⟪ghost⟫ Я Угу, помощник. Работаю для своих, подключиться: t.me/{UGU['username']}")
        return
    if not question and msg.reply_to_message is None:
        await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t, keyboard=menu_kb())), MENU_TEXT)
        return
    kind, _ = understand(question, msg.reply_to_message)
    if kind == "images":
        log_question(caller, question, kind, "guest")
        q, found = await pick_images(question, caller, msg.chat.id)
        if found:
            await bot.answer_guest_query(msg.guest_query_id, photo_results(found)[0])
            return
    if kind == "fx":
        ans = await brain(Ctx(caller, question, None, "", msg.reply_to_message, bot))
        if ans.photo:
            try:
                stored = await bot.send_photo(ab.STORE_CHAT_ID, BufferedInputFile(ans.photo, "ugu.jpg"),
                                              caption=f"fx для {caller}"[:100])
                result = InlineQueryResultCachedPhoto(id=hashlib.md5(ans.photo[:4096]).hexdigest()[:16],
                                                      photo_file_id=stored.photo[-1].file_id)
                await bot.answer_guest_query(msg.guest_query_id, result)
                return
            except Exception as e:
                log.warning("угу: фото-эффект в гостевом ответе: %s", e)
                ans = Answer(public="⟪sad⟫ Картинку сделал, но Telegram не принял её в ответ.")
        await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t)), ans.public or "⟪sad⟫ Не получилось.")
        return
    sent = await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t)), THINK)
    chat_id = msg.chat.id if has_chat(caller, msg.chat.id) else None
    try:
        ans = await asyncio.wait_for(
            brain(Ctx(caller, question, chat_id, ab.chat_title(msg.chat), msg.reply_to_message, bot, can_ask=True)), GUEST_WAIT)
    except asyncio.TimeoutError:
        log.warning("угу: гостевой ответ не уложился в %s с: %s", GUEST_WAIT, question[:80])
        ans = Answer(public="⟪sad⟫ Не успел: долго думал. Попробуй ещё раз, обычно со второго раза быстрее.")
    except Exception as e:
        log.exception("угу: ошибка в гостевом ответе")
        ans = Answer(public="⟪sad⟫ Что-то сломалось, попробуй ещё раз.")
    if ans.private:
        notify(caller, ans.private)
    public = ans.public or ("⟪mail⟫ Скинул в личку." if ans.private else "⟪ok⟫ Готово.")
    if len(public) > 3500:
        public = public[:3490] + "…"
    try:
        await say(lambda t: bot.edit_message_text(t, inline_message_id=sent.inline_message_id, link_preview_options=lp(),
                                                  reply_markup=choice_kb(ans)), public)
    except Exception as e:
        log.warning("угу: не обновил гостевой ответ: %s", e)


@router.inline_query()
async def on_inline(query: InlineQuery, bot: Bot):
    text = (query.query or "").strip()
    if not allowed(query.from_user.id):
        await query.answer([], cache_time=60, is_personal=True)
        return
    if not text:
        await query.answer([article(deco(MENU_TEXT, False), "👻 Меню Угу", "Картинки, интернет, что умею", menu_kb()),
                            article(deco(HELP, False), "❓ Что умею", "Все команды и как звать")],
                           cache_time=300, is_personal=False)
        return
    import instant
    mode = INLINE_MODE.match(text)
    if mode:
        text = text[mode.end():].strip()
    image_mode = bool(mode) and mode.group(1) not in ("?", "и")
    offset = int(query.offset) if (query.offset or "").isdigit() else 0
    if mode and not image_mode and len(text) >= 3 and not offset:
        exact = await instant.answer(text)
        if exact:
            plain = re.sub(r"<[^>]+>", "", exact)
            await query.answer([article(deco("⟪web⟫ ", False) + exact, f"🌐 {plain[:60]}", plain[60:180] or None)],
                               cache_time=60, is_personal=False)
            return
    # без префикса вопросы не подсказываем: человек жмёт «Отправить», и Угу отвечает в чате сам (как Мира),
    # а на его ответ можно ответить реплаем. Готовая подсказка ушла бы от имени человека.
    want_web = bool(mode) and mode.group(1) in ("?", "и")
    if want_web and len(text) >= 3:
        res = await websearch.lookup(text)
        if not res:
            await query.answer([], cache_time=30, is_personal=False)
            return
        body = websearch.format_answer(res)
        title = (res["source"][0] if res["source"] else text)[:60]
        await query.answer([article(deco("⟪web⟫ ", False) + body, f"🌐 {title}", res["text"][:120] or None)],
                           cache_time=120, is_personal=False)
        return
    kind = intent(text) if not mode else "images"
    asks = kind == "unknown" and (len(text.split()) > 3 or ASKY.search(slang.normalize(text)))
    if len(text) < 2 or kind not in ("unknown", "images") or asks:
        await query.answer([], cache_time=5, is_personal=True)
        return
    found = await websearch.images(image_query(text) or text, 30, offset)
    await query.answer(photo_results(found), cache_time=300, is_personal=False,
                       next_offset=str(offset + 30) if found else "")


@router.callback_query(F.data == "ugh")
async def on_menu_help(call: CallbackQuery, bot: Bot):
    await call.answer()
    try:
        if call.inline_message_id:
            await say(lambda t: bot.edit_message_text(t, inline_message_id=call.inline_message_id,
                                                      link_preview_options=lp()), HELP.replace("👻", "⟪hi⟫", 1))
        elif call.message:
            await say(lambda t: bot.edit_message_text(t, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                                      link_preview_options=lp()), HELP.replace("👻", "⟪hi⟫", 1))
    except Exception as e:
        log.warning("угу: меню: %s", e)


@start_router.message(CommandStart())
async def ugu_start(msg: Message):
    gift = tiers.on_start(msg.from_user.id, (msg.text or "").partition(" ")[2].strip())
    gift = f"\n\n{gift}" if gift else ""
    if allowed(msg.from_user.id):
        await say(msg.answer, HELP.replace("👻", "⟪hi⟫", 1) + "\n\nМожно и тут: спроси что угодно, пришли фото или голосовое."
                  + gift)
    else:
        await say(msg.answer, "⟪ghost⟫ Я Угу, призрак твоих переписок. Подключи меня: Настройки → Telegram для бизнеса → "
                              "Чат-боты → @ugu_ai, включи «Удаление сообщений». Потом открой кнопку «Угу» внизу." + gift)


@router.message(F.chat.type == "private")
async def ugu_private(msg: Message, bot: Bot):
    if not allowed(msg.from_user.id):
        return
    question = strip_name(msg.text or msg.caption or "")
    reply = msg if (msg.photo or msg.voice or msg.video_note or msg.document) else msg.reply_to_message
    wait = await say(msg.answer, THINK)
    ans = await brain(Ctx(msg.from_user.id, question, None, "", reply, bot, can_ask=True))
    if ans.photo:
        await bot.send_photo(msg.chat.id, BufferedInputFile(ans.photo, "ugu.jpg"))
        try:
            await bot.delete_message(msg.chat.id, wait.message_id)
        except Exception:
            pass
        return
    text = "\n\n".join(x for x in (ans.public, ans.private) if x) or "⟪ok⟫ Готово."
    text = text if len(text) <= 3500 else text[:3490] + "…"
    if ans.images:
        try:
            await bot.send_media_group(msg.chat.id, [InputMediaPhoto(media=u) for u, *_ in ans.images[:4]])
        except Exception as e:
            log.warning("угу: альбом в личку: %s", e)
    try:
        await say(lambda t: bot.edit_message_text(t, chat_id=msg.chat.id, message_id=wait.message_id,
                                                  link_preview_options=lp(), reply_markup=choice_kb(ans)), text)
    except Exception:
        await say(lambda t: msg.answer(t, link_preview_options=lp(), reply_markup=choice_kb(ans)), text)


@router.callback_query(F.data.startswith("ugu:"))
async def on_pick(call: CallbackQuery, bot: Bot):
    _, qid, kind = (call.data.split(":") + ["", ""])[:3]
    with ab.db() as con:
        table(con)
        row = con.execute("SELECT * FROM ugu_pending WHERE qid=?", (qid,)).fetchone()
    if not row or row["owner_id"] != call.from_user.id or kind not in LABELS:
        await call.answer("Это не твой вопрос или он устарел.", show_alert=True)
        return
    await call.answer("Понял, запомню")
    await remember(row["owner_id"], row["question"], kind)
    ans = await brain(Ctx(row["owner_id"], row["question"], row["chat_id"], row["chat_title"] or "", None, bot, kind=kind))
    if ans.private:
        notify(row["owner_id"], ans.private)
    public = ans.public or ("⟪mail⟫ Скинул в личку." if ans.private else "⟪ok⟫ Готово.")
    public = public if len(public) <= 3500 else public[:3490] + "…"
    try:
        if call.inline_message_id:
            await say(lambda t: bot.edit_message_text(t, inline_message_id=call.inline_message_id,
                                                      link_preview_options=lp()), public)
        elif call.message:
            await say(lambda t: bot.edit_message_text(t, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                                      link_preview_options=lp()), public)
    except Exception as e:
        log.warning("угу: не обновил ответ после выбора: %s", e)
    with ab.db() as con:
        con.execute("DELETE FROM ugu_pending WHERE qid=?", (qid,))


DESCRIPTION = ("👻 Угу, призрак твоих переписок: вижу всё, даже удалённое.\n\n"
               "• «угубот, …» в своей переписке: ответ впишу в твоё сообщение\n"
               "• «@ugu_ai вопрос» в любом чате, «@ugu_ai котики» картинки\n"
               "• интернет, погода, курс, калькулятор\n"
               "• напоминания, заметки, договорённости, поиск в переписке\n"
               "• фото: что на нём, найти товар, демотиватор, шакал, жмых\n"
               "• приколы: инфа, выбери, данет, кубик")


async def setup_profile(bot: Bot):
    from aiogram.types import BotCommand
    for attempt in range(10):
        try:
            await bot.set_my_commands([BotCommand(command="start", description="Кто такой Угу и как звать")])
            await bot.set_my_short_description("Призрак твоих переписок: вижу всё, даже удалённое. Зови «угубот» в переписке или @ugu_ai в любом чате.")
            await bot.set_my_description(DESCRIPTION)
            return
        except Exception as e:
            log.warning("угу: профиль не обновил (%s): %s", attempt + 1, e)
            await asyncio.sleep(30)


async def setup(bot: Bot):
    """Угу в общем процессе: узнать себя, обновить профиль, загрузить понимание по смыслу, кнопку мини-аппа."""
    UGU["bot"] = bot
    BOTS["archive"] = ab.bot_by("archive")
    me = await bot.me()
    UGU["username"], UGU["guest"] = me.username, me.supports_guest_queries
    log.info("угу: @%s на связи, гостевой режим %s", UGU["username"], "включён" if UGU["guest"] else "ВЫКЛЮЧЕН в BotFather")
    asyncio.create_task(setup_profile(bot))
    asyncio.create_task(sem_start())
    asyncio.create_task(setup_app_button(bot))
    try:
        import groups
        asyncio.create_task(groups.timers_loop(bot))
    except ImportError:
        pass


async def setup_app_button(bot: Bot):
    if not ab.WEBAPP_URL:
        return
    from aiogram.types import MenuButtonWebApp, WebAppInfo
    url = ab.WEBAPP_URL.rstrip("/") + "/u/"
    for attempt in range(10):
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Угу", web_app=WebAppInfo(url=url)))
            return
        except Exception as e:
            log.warning("угу: кнопка мини-аппа (%s): %s", attempt + 1, e)
            await asyncio.sleep(30)
