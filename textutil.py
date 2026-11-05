import re
from collections import Counter

from timeparse import month_of

ENDINGS = sorted("""
иями ями ами ией иях ях ах ою ею ей ой ий ый ая яя ое ее ую юю ые ие ых их ым им ом ем ам ям
ого его ому ему ешь ишь ете ите ет ит ут ют ат ят ал ял ил ыл ла ли ло лся лась лись ться тся
ть ти уть ешься ется ются атся ятся ость ости ов ев ей а я о е и ы у ю ь
""".split(), key=len, reverse=True)
WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от "
           "меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж "
           "вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без "
           "будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один "
           "почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после "
           "над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед "
           "иногда лучше чуть том нельзя такой им более всегда конечно всю между это".split())


def stem(word):
    w = word.lower().replace("ё", "е")
    if len(w) <= 3 or not re.match(r"[а-я]", w):
        return w
    for end in ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[: -len(end)]
    return w


def stems(text):
    return [stem(w) for w in WORD.findall(text or "") if w.lower() not in STOP]


def match_score(query_stems, text):
    if not text:
        return 0
    have = stems(text)
    score = 0
    for q in set(query_stems):
        if any(similar(q, h) for h in have):
            score += 1
    return score


def similar(a, b):
    if a == b or (len(b) >= 4 and a.startswith(b)) or (len(a) >= 3 and b.startswith(a)):
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 4 and n >= min(len(a), len(b)) - 1


SENT = re.compile(r"(?<=[.!?\n])\s+")
PROMISE = re.compile(
    r"\b(сделаю|сделаем|скину|скинем|пришлю|пришлём|пришлем|отправлю|отправим|оплачу|оплатим|переведу|переведём|"
    r"переведем|позвоню|наберу|напишу|отвечу|буду|приеду|приду|заеду|верну|вернём|обещаю|договорились|"
    r"договоримся|подготовлю|займусь|посмотрю|проверю|исправлю|доделаю|успею|постараюсь)\b", re.I)
DEADLINE = re.compile(
    r"\b(завтра|послезавтра|сегодня|вечером|утром|к\s+\d{1,2}|до\s+\d{1,2}|в\s+\d{1,2}[:.]\d{2}|\d{1,2}[:.]\d{2}|"
    r"\d{1,2}\.\d{1,2}|понедельник|вторник|сред[уы]|четверг|пятниц[уы]|суббот[уы]|воскресень[ея]|"
    r"на\s+этой\s+неделе|на\s+следующей\s+неделе|через\s+\S+)\b", re.I)


def promises(rows, owner_id):
    """rows: dict-подобные с sender_id, sender_name, date, text. Возвращает список (кто, дата, фраза, срок)."""
    out = []
    for r in rows:
        text = r["text"] or ""
        for sentence in SENT.split(text):
            s = sentence.strip()
            if len(s) < 4 or not PROMISE.search(s):
                continue
            d = DEADLINE.search(s)
            who = "Я" if r["sender_id"] == owner_id else (r["sender_name"] or "собеседник")
            out.append((who, r["date"], s[:300], d.group(0) if d else ""))
    return out


def summary(rows, owner_id, limit=10):
    rows = [r for r in rows if r["text"] or r["media_type"]]
    if not rows:
        return {"total": 0}
    mine = sum(1 for r in rows if r["sender_id"] == owner_id)
    media = Counter(r["media_type"] for r in rows if r["media_type"])
    days = sorted({r["date"][:10] for r in rows})
    words = Counter(s for r in rows for s in stems(r["text"]) if len(s) >= 4)
    scored = []
    for r in rows:
        t = r["text"] or ""
        score = 0
        if "?" in t:
            score += 2
        if DEADLINE.search(t):
            score += 2
        if PROMISE.search(t):
            score += 2
        score += min(len(t) // 120, 3)
        if score:
            scored.append((score, r))
    key = sorted(sorted(scored, key=lambda x: -x[0])[:limit], key=lambda x: x[1]["date"])
    return {
        "total": len(rows), "mine": mine, "theirs": len(rows) - mine, "media": dict(media),
        "days": days, "top_words": [w for w, _ in words.most_common(8)],
        "key": [x[1] for x in key],
        "deleted": sum(1 for r in rows if r["deleted"]), "edited": sum(1 for r in rows if r["edited"]),
    }


BDAY = re.compile(
    r"(?:у\s+меня|мой|моё|мое)\s+(?:будет\s+)?(?:др|днюха|днюшка|день\s+рожд[а-я]*)\s*(?:будет\s+)?(?:—|-|:)?\s*"
    r"(\d{1,2})(?:\s*[./]\s*(\d{1,2})|\s+([а-яё]+))", re.I)
BDAY2 = re.compile(
    r"(?:день\s+рожд[а-я]*|др)\s+у\s+меня\s+(\d{1,2})(?:\s*[./]\s*(\d{1,2})|\s+([а-яё]+))", re.I)


def birthday_in(text):
    for rx in (BDAY, BDAY2):
        m = rx.search(text or "")
        if not m:
            continue
        day = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else month_of(m.group(3) or "")
        if month and 1 <= month <= 12 and 1 <= day <= 31:
            return day, month
    return None
