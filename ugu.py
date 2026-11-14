import asyncio
import hashlib
import html
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery, InlineQueryResultArticle,
                           InlineQueryResultPhoto, InputMediaPhoto, InputTextMessageContent, LinkPreviewOptions, Message)

import archive_bot as ab
import llm
import slang
import websearch
from textutil import match_score, promises, stems, summary
from timeparse import MSK

log = logging.getLogger("archive.ugu")
router = Router()
UGU = {"bot": None, "username": "ugu_ai", "guest": None}

NAME_ANY = re.compile(r"(?i)(?<![\w@])(?:угу\s*-?\s*бот\w*|угубот\w*)(?!\w)[\s,:!.\-]*")
NAME_LEAD = re.compile(r"(?i)^\s*угу\s*[,:!]\s*(.+)$", re.S)
MENTION = re.compile(r"(?i)@ugu_ai(_bot)?\b[\s,:!.\-]*")
CALL_MAX = 300
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
    ("chat", r"^(привет\w*|здравствуй\w*|добр\w+ (утро|день|вечер|ночи)|как (твои |у тебя )?дела|как ты\b|как сам|как жизнь|"
             r"что делаешь|чем занят|ты (тут|здесь|живой|кто)|кто ты|спасибо|благодар|молодец|красава|умница|"
             r"люблю тебя|ты лучший|ты (дурак|тупой|глупый)|тупой бот|пока\b|спокойной ночи|доброй ночи)"),
    ("remind", r"\bнапомн"),
    ("deleted", r"удал[её]н|удалил|удалили|стёр|стер\b|стерли|стёрли"),
    ("images", r"\b(скинь|покажи|найди|дай|пришли|отправь|го|хочу|нужн\w*|можно)\b.{0,40}\b(картинк\w*|фото|мем\w*|гифк\w*|обои|арт\w*|"
               r"пикч\w*|изображени\w*)\b|^(картинк\w*|фото|мем\w*|обои|пикч\w*)\b|\b(мем|мемы|мемов)\b|как выгляд"),
    ("schedule", r"расписан|\bпланы?\b|по делам|какие (у меня )?дела|мои дела|что (у меня )?(на|по) (сегодня|завтра|недел)|"
                 r"что у меня (сегодня|завтра|на недел)|я (сегодня|завтра) свобод|напоминани|\bзадач"),
    ("promises", r"обещ|договорил|договорён|договорен|уговор|условил"),
    ("summary", r"сводк|пересказ|перескажи|о ч[её]м (мы )?(говорили|болтали|речь|переписк)|что было|кратко|итог"),
    ("voice", r"расшифр|что (он |она )?(сказал|говорит) в (гс|голосов)|текст (гс|голосов)"),
    ("photo", r"что (на|тут на|это на) (фото|картинк|скрин)|прочитай|что (тут|здесь) написано|что (это|тут) такое\??$"),
    ("find", r"^(найди|поищи|где|когда)\b.*\b(он|она|ты|я|мы|скидывал\w*|кидал\w*|писал\w*|присылал\w*|говорил\w*|"
             r"отправлял\w*|адрес\w*|ссылк\w*|номер\w*|телефон\w*)\b|в (этой )?(переписке|чате)"),
    ("web", r"\?\s*$|^(что|кто|как|почему|зачем|сколько|где|когда|какой|какая|какое|какие|каков\w*|чем|отчего|"
            r"найди|поищи|загугли|погугли|расскажи|объясни|подскажи)\b"),
]
INTENTS = [(name, re.compile(rx, re.I)) for name, rx in INTENTS]
EXPLICIT = {"remind", "deleted", "schedule", "images", "summary", "promises", "find"}
STRONG = {"help", "remind", "deleted", "schedule", "promises", "summary", "voice", "images", "photo", "find"}
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
        "что удалили (только тебе в личку), расшифровать ГС, что на фото, ответ из интернета со ссылками.")


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


def deco(text, custom=True):
    """⟪имя⟫ → свой эмодзи-призрак (custom emoji) или обычный эмодзи."""
    def sub(m):
        fallback, eid = EMO.get(m.group(1), "👻"), EMO_IDS.get(m.group(1))
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if custom and eid else fallback
    return EMO_RX.sub(sub, text or "")


async def say(call, text):
    """Шлёт со своими эмодзи; если Telegram их не принял, повторяет с обычными."""
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
        if not explicit and (reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))):
            return "photo"
        if not explicit and (reply.voice or reply.video_note):
            return "voice"
    if not q:
        return "help"
    for name, rx in INTENTS:
        if rx.search(q):
            return name
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


def chat_rows(owner, chat_id, days, deleted=False):
    since = (now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with ab.db() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM messages WHERE owner_id=? AND chat_id=? AND date >= ? AND deleted=? ORDER BY date",
            (owner, chat_id, since, int(deleted)))]


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
    scored = sorted(((match_score(words, r["text"]), r) for r in rows), key=lambda x: (x[0], x[1]["date"]), reverse=True)
    return [r for s, r in scored if s > 0][:limit]


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
            ans.public = "⟪mail⟫ Скинул в личку."
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
    try:
        import vision
    except Exception as e:
        log.warning("угу: распознавание фото недоступно: %s", e)
        return "⟪sad⟫ Смотреть фото сейчас не могу: модуль распознавания не установлен."
    path = await download(ctx.file_bot, obj, f"ugu_{src.chat.id}_{src.message_id}", ".jpg")
    if not path:
        return "⟪sad⟫ Не смог скачать фото, попробуй ещё раз."
    try:
        res = await asyncio.to_thread(vision.analyze, str(path), str(ab.DATA / "vision"))
        return "⟪photo⟫ " + html.escape(vision.describe(res))
    except Exception as e:
        log.warning("угу: фото не разобрал: %s", e)
        return "⟪sad⟫ Не получилось разобрать фото."
    finally:
        path.unlink(missing_ok=True)


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


def image_query(question):
    q = re.sub(r"\s+", " ", IMAGE_WORDS.sub(" ", slang.normalize(question or ""))).strip(" ?!.,")
    return q or "мем"


CHAT = [
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


def chat_reply(question):
    q = slang.normalize(question).lower()
    for rx, answers in CHAT:
        if re.search(rx, q):
            return random.choice(answers)
    return random.choice(CHAT[0][1])


def log_question(owner, question, kind, source):
    try:
        with ab.db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS ugu_log (owner_id INTEGER, ts TEXT, source TEXT, question TEXT, "
                        "normalized TEXT, intent TEXT)")
            con.execute("INSERT INTO ugu_log VALUES (?,?,?,?,?,?)", (owner, now().strftime("%Y-%m-%d %H:%M:%S"), source,
                                                                     question[:500], slang.normalize(question)[:500], kind))
    except Exception as e:
        log.warning("угу: журнал вопросов: %s", e)


async def pick_images(question):
    q = image_query(question)
    found = (await websearch.images(q, 30))[:30]
    random.shuffle(found)
    return q, found[:4 if PLURAL_IMG.search(slang.normalize(question)) else 1]


# ---------- мозг ----------

def on_topic(question, res):
    want = set(stems(websearch.keywords(websearch.clean_query(question))))
    have = set(stems(" ".join([res["text"], res["source"][0] if res["source"] else ""] + [t for t, _ in res["links"]])))
    return bool(want & have)


async def web_answer(question, strict=False):
    res = await websearch.lookup(question)
    if strict and (not res or not on_topic(question, res)):
        return "⟪huh⟫ Не понял. Спроси по-другому или «угубот, что умеешь?»."
    if llm.enabled() and res:
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
          "help": "❓ Что умею", "remind": "⏰ Напомнить", "voice": "🎤 Расшифровать ГС", "photo": "📷 Что на фото"}


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
    kind, alts = (ctx.kind, []) if ctx.kind else understand(ctx.question, ctx.reply)
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
    if kind == "chat":
        return Answer(public=chat_reply(ctx.question))
    if kind == "schedule":
        return Answer(public=schedule_text(ctx.owner, ctx.question))
    if kind == "remind":
        import assistant
        await assistant.create_reminder(ab_bot(), ctx.owner, ctx.question, f"чат с {ctx.chat_title}" if ctx.chat_title else "")
        return Answer(public="⟪alarm⟫ Записал, напомню.")
    if kind in ("deleted", "promises", "summary") and not in_chat:
        return Answer(public="⟪sad⟫ Этот чат я не веду, поэтому по нему не подскажу.")
    if kind == "deleted":
        return Answer(public="⟪mail⟫ Скинул в личку.", private=deleted_answer(ctx))
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
    if kind == "images":
        q, found = await pick_images(ctx.question)
        return Answer(public=f"⟪photo⟫ {html.escape(q)}" if found else "⟪sad⟫ Картинок не нашёл.", images=found)
    if kind == "web":
        return Answer(public=await web_answer(ctx.question))
    return Answer(public=await web_answer(ctx.question, strict=not llm.enabled()))


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
                                                      message_id=msg.message_id, link_preview_options=NO_PREVIEW), text)
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
                                             link_preview_options=NO_PREVIEW), text)
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
    thinking, err = await edit_own(bot, msg, joined(head, THINK))
    try:
        ans = await brain(Ctx(owner, question, msg.chat.id, ab.chat_title(msg.chat), msg.reply_to_message, bot))
    except Exception as e:
        log.exception("угу: ошибка")
        ans = Answer(private=f"⟪sad⟫ Сломался на вопросе «{html.escape(question[:100])}»: {html.escape(str(e)[:200])}")
    if ans.private:
        notify(owner, ans.private)
    public = ans.public
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


def article(text):
    return InlineQueryResultArticle(id=hashlib.md5(text.encode()).hexdigest()[:16], title="Угу",
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
    question = strip_name(msg.text or msg.caption)
    if not allowed(caller):
        await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t)),
                  f"⟪ghost⟫ Я Угу, помощник. Работаю для своих, подключиться: t.me/{UGU['username']}")
        return
    kind, _ = understand(question, msg.reply_to_message)
    if kind == "images":
        log_question(caller, question, kind, "guest")
        q, found = await pick_images(question)
        if found:
            await bot.answer_guest_query(msg.guest_query_id, photo_results(found)[0])
            return
    sent = await say(lambda t: bot.answer_guest_query(msg.guest_query_id, article(t)), THINK)
    chat_id = msg.chat.id if has_chat(caller, msg.chat.id) else None
    try:
        ans = await brain(Ctx(caller, question, chat_id, ab.chat_title(msg.chat), msg.reply_to_message, bot, can_ask=True))
    except Exception as e:
        log.exception("угу: ошибка в гостевом ответе")
        ans = Answer(public="⟪sad⟫ Что-то сломалось, попробуй ещё раз.")
    if ans.private:
        notify(caller, ans.private)
    public = ans.public or ("⟪mail⟫ Скинул в личку." if ans.private else "⟪ok⟫ Готово.")
    if len(public) > 3500:
        public = public[:3490] + "…"
    try:
        await say(lambda t: bot.edit_message_text(t, inline_message_id=sent.inline_message_id, link_preview_options=NO_PREVIEW,
                                                  reply_markup=choice_kb(ans)), public)
    except Exception as e:
        log.warning("угу: не обновил гостевой ответ: %s", e)


@router.inline_query()
async def on_inline(query: InlineQuery, bot: Bot):
    text = (query.query or "").strip()
    if not allowed(query.from_user.id) or len(text) < 2 or intent(text) not in ("unknown", "images"):
        await query.answer([], cache_time=5, is_personal=True)
        return
    found = await websearch.images(image_query(text), 20)
    await query.answer(photo_results(found), cache_time=300, is_personal=False)


@router.message(CommandStart())
async def ugu_start(msg: Message):
    if allowed(msg.from_user.id):
        await say(msg.answer, HELP.replace("👻", "⟪hi⟫", 1) + "\n\nМожно и тут: спроси что угодно, пришли фото или голосовое.")
    else:
        await say(msg.answer, "⟪ghost⟫ Я Угу, призрак-помощник. Работаю для тех, кто подключил архив @mmrool_archive_bot "
                              "(Настройки → Telegram для бизнеса → Чат-боты).")


@router.message(F.chat.type == "private")
async def ugu_private(msg: Message, bot: Bot):
    if not allowed(msg.from_user.id):
        return
    question = strip_name(msg.text or msg.caption or "")
    reply = msg if (msg.photo or msg.voice or msg.video_note or msg.document) else msg.reply_to_message
    wait = await say(msg.answer, THINK)
    ans = await brain(Ctx(msg.from_user.id, question, None, "", reply, bot, can_ask=True))
    text = "\n\n".join(x for x in (ans.public, ans.private) if x) or "⟪ok⟫ Готово."
    text = text if len(text) <= 3500 else text[:3490] + "…"
    if ans.images:
        try:
            await bot.send_media_group(msg.chat.id, [InputMediaPhoto(media=u) for u, *_ in ans.images[:4]])
        except Exception as e:
            log.warning("угу: альбом в личку: %s", e)
    try:
        await say(lambda t: bot.edit_message_text(t, chat_id=msg.chat.id, message_id=wait.message_id,
                                                  link_preview_options=NO_PREVIEW, reply_markup=choice_kb(ans)), text)
    except Exception:
        await say(lambda t: msg.answer(t, link_preview_options=NO_PREVIEW, reply_markup=choice_kb(ans)), text)


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
                                                      link_preview_options=NO_PREVIEW), public)
        elif call.message:
            await say(lambda t: bot.edit_message_text(t, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                                      link_preview_options=NO_PREVIEW), public)
    except Exception as e:
        log.warning("угу: не обновил ответ после выбора: %s", e)
    with ab.db() as con:
        con.execute("DELETE FROM ugu_pending WHERE qid=?", (qid,))


async def setup_profile(bot: Bot):
    from aiogram.types import BotCommand
    for attempt in range(10):
        try:
            await bot.set_my_commands([BotCommand(command="start", description="Кто такой Угу и как звать")])
            await bot.set_my_short_description("Призрак твоих переписок: вижу всё, даже удалённое. Зови «угубот» в переписке или @ugu_ai в любом чате.")
            await bot.set_my_description(HELP)
            return
        except Exception as e:
            log.warning("угу: профиль не обновил (%s): %s", attempt + 1, e)
            await asyncio.sleep(30)


async def run(token, archive_bot: Bot):
    BOTS["archive"] = archive_bot
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    UGU["bot"] = bot
    dp = Dispatcher()
    dp.include_router(router)
    while True:
        try:
            me = await bot.me()
            UGU["username"], UGU["guest"] = me.username, me.supports_guest_queries
            break
        except Exception as e:
            log.warning("угу: Telegram не отвечает (%s), повтор через 15 сек", e)
            await asyncio.sleep(15)
    log.info("угу: @%s на связи, гостевой режим %s", UGU["username"], "включён" if UGU["guest"] else "ВЫКЛЮЧЕН в BotFather")
    asyncio.create_task(setup_profile(bot))
    asyncio.create_task(sem_start())
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)
            break
        except Exception as e:
            log.warning("угу: опрос упал (%s), перезапуск через 15 сек", e)
            await asyncio.sleep(15)
