import re
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "мая": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
WEEKDAYS = {
    "понедельник": 0, "пн": 0, "вторник": 1, "вт": 1, "сред": 2, "ср": 2, "четверг": 3, "чт": 3,
    "пятниц": 4, "пт": 4, "суббот": 5, "сб": 5, "воскресень": 6, "вс": 6,
}
UNITS = {"мин": 1, "минут": 1, "м": 1, "час": 60, "часа": 60, "часов": 60, "ч": 60,
         "дн": 1440, "день": 1440, "дня": 1440, "дней": 1440, "сек": 0}
WORD_NUM = {"одну": 1, "один": 1, "две": 2, "два": 2, "три": 3, "четыре": 4, "пять": 5, "десять": 10,
            "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40, "полчаса": 30}
PARTS = {"утром": 9, "днём": 13, "днем": 13, "вечером": 19, "ночью": 23}


def month_of(word):
    word = word.lower()
    for stem, num in MONTHS.items():
        if word.startswith(stem) and (stem not in ("ма",) or word in ("мая", "май", "маю")):
            return num
    return None


def _clean(text):
    return re.sub(r"\s+", " ", text).strip(" ,.;:-")


def parse_when(text, now=None):
    """Ищет в тексте момент времени. Возвращает (datetime | None, остаток текста, нужна_ли_точная_минута)."""
    now = now or datetime.now(MSK)
    src = " " + text + " "
    low = src.lower()
    spans = []

    def take(m):
        spans.append(m.span())

    m = re.search(r"\bчерез\s+(полчаса|час|(\d+|[а-яё]+)\s*(минут[уы]?|мин|м|час[аов]*|ч|дн[ейя]*|день))\b", low)
    if m:
        take(m)
        if m.group(1) == "полчаса":
            minutes = 30
        elif m.group(1) == "час":
            minutes = 60
        else:
            raw = m.group(2)
            n = int(raw) if raw.isdigit() else WORD_NUM.get(raw)
            if n is None:
                n = 1
            unit = m.group(3)
            mult = 60 if unit.startswith(("час", "ч")) else 1440 if unit.startswith(("дн", "день")) else 1
            minutes = n * mult
        when = now + timedelta(minutes=minutes)
        return when.replace(second=0, microsecond=0), _cut(src, spans), False

    day = None
    m = re.search(r"\b(послезавтра|завтра|сегодня)\b", low)
    if m:
        take(m)
        day = now.date() + timedelta(days={"сегодня": 0, "завтра": 1, "послезавтра": 2}[m.group(1)])
    if day is None:
        m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", low)
        if m and int(m.group(2)) <= 12 and int(m.group(1)) <= 31:
            take(m)
            year = int(m.group(3)) if m.group(3) else now.year
            if year < 100:
                year += 2000
            day = _safe_date(year, int(m.group(2)), int(m.group(1)))
            if day and not m.group(3) and day < now.date():
                day = _safe_date(year + 1, int(m.group(2)), int(m.group(1)))
    if day is None:
        m = re.search(r"\b(\d{1,2})\s+([а-яё]+)", low)
        if m and month_of(m.group(2)):
            take(m)
            day = _safe_date(now.year, month_of(m.group(2)), int(m.group(1)))
            if day and day < now.date():
                day = _safe_date(now.year + 1, month_of(m.group(2)), int(m.group(1)))
    if day is None:
        m = re.search(r"\b(?:в|во)?\s*(понедельник|вторник|среду|сред[ау]|четверг|пятницу|пятниц[ау]|субботу|суббот[ау]|"
                      r"воскресенье|пн|вт|ср|чт|пт|сб|вс)\b", low)
        if m:
            word = m.group(1)
            wd = next((v for k, v in WEEKDAYS.items() if word.startswith(k)), None)
            if wd is not None:
                take(m)
                ahead = (wd - now.weekday()) % 7
                day = now.date() + timedelta(days=ahead or 7)

    hour = minute = None
    ambiguous = False
    m = next((x for x in re.finditer(r"\b(?:в|к|на)?\s*(\d{1,2})[:.](\d{2})\b", low)
              if not _overlaps(x.span(), spans) and int(x.group(1)) < 24 and int(x.group(2)) < 60), None)
    if m:
        take(m)
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(?:в|к|на)\s+(\d{1,2})(?:\s*(час[аов]*|ч))?(?:\s*(утра|дня|вечера|ночи))?\b", low)
        if m and not _overlaps(m.span(), spans) and int(m.group(1)) < 24:
            take(m)
            hour, minute = int(m.group(1)), 0
            part = m.group(3)
            ambiguous = part is None
            if part in ("дня", "вечера") and hour < 12:
                hour += 12
            if part == "ночи" and hour == 12:
                hour = 0
        else:
            m = re.search(r"\b(утром|днём|днем|вечером|ночью)\b", low)
            if m:
                take(m)
                hour, minute = PARTS[m.group(1)], 0

    if day is None and hour is None:
        return None, _clean(text), False
    if hour is None:
        return datetime(day.year, day.month, day.day, 9, 0, tzinfo=MSK), _cut(src, spans), True
    if day is None:
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= now:
            if ambiguous and hour < 12 and now.hour >= 12 and hour + 12 < 24 and now.replace(hour=hour + 12, minute=minute) > now:
                cand = now.replace(hour=hour + 12, minute=minute, second=0, microsecond=0)
            else:
                cand += timedelta(days=1)
        return cand, _cut(src, spans), False
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK), _cut(src, spans), False


def _safe_date(y, mo, d):
    try:
        return datetime(y, mo, d).date()
    except ValueError:
        return None


def _overlaps(span, spans):
    return any(span[0] < b and a < span[1] for a, b in spans)


def _cut(src, spans):
    out = src
    for a, b in sorted(spans, reverse=True):
        out = out[:a] + " " + out[b:]
    out = re.sub(r"\b(в|во|к|на)\s*$", "", out.strip(), flags=re.I)
    return _clean(out)


def parse_duration(text, now=None):
    """«2ч», «30м», «1.5 часа», «до 18:00», «до завтра 10:00». Возвращает (datetime | None, остаток)."""
    now = now or datetime.now(MSK)
    low = text.strip()
    m = re.match(r"^до\s+(.+?)(?:\s+(?=\S)|$)", low, re.I)
    if m:
        words = low[3:].strip()
        when, rest, _ = parse_when(words, now)
        if when:
            if when <= now:
                when += timedelta(days=1)
            return when, rest
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(ч|час[аов]*|м|мин|минут[ау]?)\b\s*(.*)$", low, re.I | re.S)
    if m:
        n = float(m.group(1).replace(",", "."))
        mult = 60 if m.group(2).lower().startswith("ч") else 1
        return now + timedelta(minutes=n * mult), m.group(3).strip()
    return None, low


def fmt(dt, now=None):
    now = now or datetime.now(MSK)
    dt = dt.astimezone(MSK)
    if dt.date() == now.date():
        day = "сегодня"
    elif dt.date() == now.date() + timedelta(days=1):
        day = "завтра"
    else:
        day = dt.strftime("%d.%m")
    return f"{day} в {dt.strftime('%H:%M')}"
