import asyncio
import hashlib
import html
import logging
import time

from aiogram import Bot, Router
from aiogram.types import (ChosenInlineResult, InlineQuery, InlineQueryResultArticle, InlineQueryResultsButton,
                           InputTextMessageContent, Message)

import archive_bot as ab
import assistant
from timeparse import fmt, parse_when

log = logging.getLogger("archive.inline")
router = Router()

ACTIONS = [
    ("напомни", "⏰", "Напомнить", "Например: 18:00 созвон, через 20 минут, завтра в 9"),
    ("задача", "✅", "Задача", "Что сделать, попадёт в /tasks"),
    ("выгрузи", "📥", "Выгрузить этот чат", "HTML и TXT придут в личку бота"),
    ("пересказ", "🧾", "Пересказ чата", "О чём говорили за неделю"),
    ("обещания", "🤝", "Что обещали", "Договорённости и сроки из этого чата"),
    ("найди", "🔎", "Найти в чате", "Что искать: адрес, оплату, ссылку"),
    ("занят", "💤", "Занят на 2 часа", "Отвечу собеседникам за тебя, по одному разу"),
    ("гс", "📝", "Текст последнего ГС в этом чате", "Расшифрую последнее голосовое собеседника"),
]
BY_ICON = {icon: key for key, icon, *_ in ACTIONS}
CHAT_ONLY = {"выгрузи", "пересказ", "обещания", "найди", "гс"}
RESULTS = {}
HANDLED = {}
FALLBACK_WAIT = 4


def is_allowed(user_id):
    return user_id == ab.OWNER_ID or ab.owner_has_archive(user_id)


def message_text(key, query):
    icon = next(i for k, i, *_ in ACTIONS if k == key)
    query = (query or "").strip()
    return f"{icon} {key}: {query}" if query else f"{icon} {key}"


def parse_text(text):
    text = (text or "").strip()
    if not text:
        return None, ""
    icon, _, rest = text.partition(" ")
    key = BY_ICON.get(icon)
    if not key:
        return None, ""
    rest = rest.strip()
    if rest.lower().startswith(key):
        rest = rest[len(key):]
    return key, rest.lstrip(" :").strip()


def reminder_preview(query):
    when, rest, _ = parse_when(assistant.clean_title(query or ""))
    title = assistant.clean_title(rest)
    if when is None or not title:
        return None
    return f"Напомнить: {title} {fmt(when)}"


def build_results(user_id, query):
    query = (query or "").strip()
    results = []
    for key, icon, title, hint in ACTIONS:
        if key == "занят":
            arg = query or "2ч Сейчас занят, отвечу чуть позже."
        elif key in ("напомни", "задача", "найди"):
            arg = query
        else:
            arg = ""
        if key == "напомни":
            ready = reminder_preview(query)
            desc = ready or hint
        elif key in ("задача", "найди") and query:
            desc = query[:120]
        else:
            desc = hint
        text = message_text(key, arg)
        rid = f"{key}:{hashlib.md5(f'{user_id}|{text}'.encode()).hexdigest()[:16]}"
        RESULTS[rid] = (user_id, text, time.time())
        results.append(InlineQueryResultArticle(
            id=rid, title=f"{icon} {title}", description=desc,
            input_message_content=InputTextMessageContent(message_text=text)))
    return results


@router.inline_query()
async def on_inline(query: InlineQuery):
    uid = query.from_user.id
    if not is_allowed(uid):
        await query.answer([], cache_time=5, is_personal=True,
                           button=InlineQueryResultsButton(text="Подключить бота", start_parameter="connect"))
        return
    await query.answer(build_results(uid, query.query), cache_time=0, is_personal=True)


def mark(owner, text):
    now = time.time()
    for k in [k for k, t in HANDLED.items() if now - t > 120]:
        HANDLED.pop(k, None)
    HANDLED[(owner, (text or "").strip())] = now


def was_handled(owner, text):
    t = HANDLED.get((owner, (text or "").strip()))
    return t is not None and time.time() - t < 120


async def run_action(bot: Bot, owner, key, rest, chat_msg=None):
    title = ab.chat_title(chat_msg.chat) if chat_msg is not None else ""
    if key == "напомни":
        if not rest:
            await assistant.send(bot, owner, "Что и когда напомнить? Набери в чате «@mmrool_archive_bot 18:00 созвон» "
                                             "или напиши мне /remind 18:00 созвон.")
            return
        await assistant.create_reminder(bot, owner, rest, f"чат с {title}" if title else "")
    elif key == "задача":
        if not rest:
            await assistant.send(bot, owner, "Напиши задачу после названия бота, например: "
                                             "«@mmrool_archive_bot скинуть макет до пятницы».")
            return
        await assistant.add_task_text(bot, owner, rest, title)
    elif key == "занят":
        await assistant.send(bot, owner, assistant.set_busy(owner, rest or "2ч", default_hours=2))
    elif chat_msg is None:
        await assistant.send(bot, owner, "Это действие работает в личных чатах, где подключён бот "
                                         "(Настройки → Telegram для бизнеса → Чат-боты).")
    else:
        await assistant.chat_command(bot, owner, chat_msg, key, rest)


async def handle_via(msg: Message, bot: Bot, owner):
    await ab.remove_trigger(msg, bot, owner)
    mark(owner, msg.text)
    key, rest = parse_text(msg.text)
    if not key:
        return
    try:
        await run_action(bot, owner, key, rest, msg)
    except Exception as e:
        log.warning("inline %s: %s", key, e)
        await assistant.send(bot, owner, f"Не получилось: {html.escape(str(e))}")


@router.chosen_inline_result()
async def on_chosen(result: ChosenInlineResult, bot: Bot):
    uid = result.from_user.id
    if not is_allowed(uid):
        return
    saved = RESULTS.get(result.result_id)
    if saved:
        text = saved[1]
    else:
        key = result.result_id.partition(":")[0]
        if key not in BY_ICON.values():
            return
        text = message_text(key, result.query)
    await asyncio.sleep(FALLBACK_WAIT)
    if was_handled(uid, text):
        return
    mark(uid, text)
    key, rest = parse_text(text)
    if key:
        await run_action(bot, uid, key, rest, None)
