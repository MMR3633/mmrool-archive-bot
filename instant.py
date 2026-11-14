"""Быстрые точные ответы без поиска: калькулятор, курс валют и крипты, погода, расстояние, время."""
import ast
import json
import math
import operator
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import websearch

MSK = timezone(timedelta(hours=3))
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# ---------- калькулятор ----------

CALC_HEAD = re.compile(r"(?i)^(сколько будет|посчитай|вычисли|реши|сколько)\s*")
CALC_BODY = re.compile(r"^[\d\s.,+\-*/()x×х÷:^]+$")
PERCENT = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*%\s*(?:от|из)\s*(\d+(?:[.,]\d+)?)")
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("слишком большая степень")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError("не арифметика")


def nice(x):
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        x = int(x)
    if isinstance(x, float):
        x = round(x, 6)
    return f"{x:,}".replace(",", " ").replace(".", ",") if isinstance(x, int) else str(x).replace(".", ",")


def calc(question):
    q = question.strip().rstrip("?=! ")
    m = PERCENT.search(q)
    if m:
        a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return f"{nice(a)}% от {nice(b)} = <b>{nice(a * b / 100)}</b>"
    body = CALC_HEAD.sub("", q)
    if not CALC_BODY.match(body) or not re.search(r"\d\s*[+\-*/x×х÷:^]\s*\(?\d", body):
        return None
    expr = body.replace("×", "*").replace("х", "*").replace("x", "*").replace("÷", "/").replace(":", "/").replace("^", "**")
    expr = expr.replace(",", ".")
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return f"{body.strip()} = <b>{nice(value)}</b>"


# ---------- валюты и крипта ----------

FIAT = {"доллар": "USD", "бакс": "USD", "usd": "USD", "евро": "EUR", "eur": "EUR", "юан": "CNY", "юань": "CNY", "cny": "CNY",
        "фунт": "GBP", "тенге": "KZT", "лир": "TRY", "сум": "UZS", "белорусск": "BYN", "иен": "JPY", "йен": "JPY",
        "франк": "CHF", "дирхам": "AED", "гривн": "UAH", "драм": "AMD", "лари": "GEL", "сомони": "TJS", "сом": "KGS"}
CRYPTO = {"биткоин": "bitcoin", "биток": "bitcoin", "btc": "bitcoin", "эфир": "ethereum", "эфириум": "ethereum",
          "eth": "ethereum", "тон": "the-open-network", "toncoin": "the-open-network", "usdt": "tether",
          "тезер": "tether", "солан": "solana", "sol": "solana", "доге": "dogecoin", "dogecoin": "dogecoin"}
RATE_HINT = re.compile(r"(?i)\b(курс|почём|почем|сколько стоит|стоимость|цена|к рублю|в рублях)\b")


def _find(table, text):
    low = text.lower()
    for key, code in table.items():
        if re.search(rf"(?<![а-яa-z]){re.escape(key)}", low):
            return key, code
    return None


async def rate(question):
    if not RATE_HINT.search(question) and not re.search(r"(?i)^(доллар|евро|юань|биткоин|эфир)\w*\??$", question.strip()):
        return None
    hit = _find(CRYPTO, question)
    if hit:
        status, body = await websearch.http_get("https://api.coingecko.com/api/v3/simple/price",
                                                {"ids": hit[1], "vs_currencies": "usd,rub", "include_24hr_change": "true"})
        try:
            d = json.loads(body)[hit[1]]
        except (ValueError, KeyError):
            return None
        ch = d.get("usd_24h_change")
        arrow = "" if ch is None else (f" ({'▲' if ch >= 0 else '▼'} {abs(ch):.1f}% за сутки)")
        return f"{hit[1].replace('-', ' ').title()}: <b>${nice(d['usd'])}</b> ≈ {nice(round(d['rub']))} ₽{arrow}"
    hit = _find(FIAT, question)
    if not hit:
        return None
    status, body = await websearch.http_get("https://www.cbr-xml-daily.ru/daily_json.js")
    try:
        v = json.loads(body)["Valute"][hit[1]]
    except (ValueError, KeyError):
        return None
    now, prev = v["Value"] / v["Nominal"], v["Previous"] / v["Nominal"]
    diff = now - prev
    return (f"Курс ЦБ: 1 {hit[1]} = <b>{nice(round(now, 4))} ₽</b> "
            f"({'▲' if diff >= 0 else '▼'} {nice(round(abs(diff), 4))} к прошлому дню)")


# ---------- погода и расстояние ----------

ALIASES = {"питер": "Санкт-Петербург", "питере": "Санкт-Петербург", "спб": "Санкт-Петербург", "мск": "Москва",
           "екб": "Екатеринбург", "нск": "Новосибирск", "мхч": "Махачкала", "махачкале": "Махачкала", "каспийске": "Каспийск"}
WEATHER = re.compile(r"(?i)(?:какая\s+)?погод\w*\s*(сейчас|сегодня|завтра)?\s*(?:в|во|на)?\s+([а-яёa-z\- ]{2,40}?)\s*(сейчас|сегодня|завтра)?\??$")
DIST = re.compile(r"(?i)(?:сколько\s+(?:км|километров)|расстояние|как\s+далеко|далеко\s+ли)\s+(?:ехать\s+)?(?:от\s+)?"
                  r"([а-яёa-z\- ]{2,40}?)\s+до\s+([а-яёa-z\- ]{2,40}?)\??$")
CODES = {0: "ясно ☀️", 1: "в основном ясно 🌤", 2: "переменная облачность ⛅", 3: "пасмурно ☁️", 45: "туман 🌫", 48: "туман 🌫",
         51: "морось 🌦", 53: "морось 🌦", 55: "морось 🌦", 56: "ледяная морось", 57: "ледяная морось", 61: "небольшой дождь 🌧",
         63: "дождь 🌧", 65: "сильный дождь 🌧", 66: "ледяной дождь", 67: "ледяной дождь", 71: "небольшой снег 🌨", 73: "снег 🌨",
         75: "сильный снег ❄️", 77: "снежная крупа", 80: "ливень 🌦", 81: "ливень 🌧", 82: "сильный ливень ⛈", 85: "снегопад 🌨",
         86: "сильный снегопад ❄️", 95: "гроза ⛈", 96: "гроза с градом ⛈", 99: "гроза с градом ⛈"}


def city_variants(name):
    name = name.strip(" ?.,").lower()
    if name in ALIASES:
        return [ALIASES[name]]
    out = []
    for end, rep in (("ы", "а"), ("е", "а"), ("и", "ь"), ("и", "а"), ("у", "а"), ("ой", "ая"), ("а", ""), ("е", ""), ("и", "")):
        if name.endswith(end) and len(name) > 3:
            out.append(name[: -len(end)] + rep)
    return out + [name]


async def geocode(name):
    """Город по названию в любом падеже: перебираем формы, берём самый крупный город."""
    variants = city_variants(name)
    best = None
    for variant in variants[:5]:
        status, body = await websearch.http_get("https://geocoding-api.open-meteo.com/v1/search",
                                                {"name": variant, "count": 5, "language": "ru"})
        try:
            results = json.loads(body).get("results") or []
        except ValueError:
            results = []
        for g in results:
            exact = g["name"].lower().replace("ё", "е") == variant.lower().replace("ё", "е")
            score = (exact, g.get("population") or 0)
            if best is None or score > best[0]:
                best = (score, (g["latitude"], g["longitude"], g["name"], g.get("country", "")))
    return best[1] if best else None


WHEN = [(re.compile(r"(?i)\bна\s+(эту\s+|всю\s+)?недел\w*|\bна\s+7\s+дн\w*"), "week"),
        (re.compile(r"(?i)\bна\s+выходн\w*"), "weekend"),
        (re.compile(r"(?i)\bна\s+(\d)\s+(дн\w*|сут\w*)"), "days"),
        (re.compile(r"(?i)\bпослезавтра\b"), "after"),
        (re.compile(r"(?i)\bзавтра\b"), "tomorrow"),
        (re.compile(r"(?i)\b(сейчас|сегодня|щас)\b"), "now")]
WEATHER_WORD = re.compile(r"(?i)\bпогод\w*")
FILLER = re.compile(r"(?i)\b(какая|какой|какую|как|там|будет|скажи|подскажи|покажи|а|ну|прогноз\w*|пожалуйста|плз|в|во|на|для|по|у)\b")
WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def weather_parts(question):
    """«погода в москве на неделю», «дятьково погода», «какая погода завтра в питере» → (срок, город, дней)."""
    q = question.strip(" ?!.,")
    if not WEATHER_WORD.search(q):
        return None
    when, days = "now", 0
    for rx, kind in WHEN:
        m = rx.search(q)
        if m:
            when = when if when != "now" else kind
            if kind == "days":
                days = int(m.group(1))
            q = rx.sub(" ", q)
    city = re.sub(r"\s+", " ", FILLER.sub(" ", WEATHER_WORD.sub(" ", q))).strip(" ,-")
    if len(city) > 40 or len(city.split()) > 3:
        return None
    return when, city or "Москва", days


async def weather(question):
    parts = weather_parts(question)
    if not parts:
        return None
    when, city, days = parts
    place = await geocode(city)
    if not place:
        return f"Не нашёл город «{city}». Напиши, например: «погода в Казани на неделю»."
    lat, lon, name, country = place
    status, body = await websearch.http_get("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "time,temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max"})
    try:
        d = json.loads(body)
        day = d["daily"]
    except (ValueError, KeyError, TypeError):
        return None

    def line(i, label):
        rain = day["precipitation_probability_max"][i]
        return (f"{label}: <b>{round(day['temperature_2m_min'][i])}…{round(day['temperature_2m_max'][i])}°</b>, "
                f"{CODES.get(day['weather_code'][i], '')}" + (f", осадки {rain}%" if rain else ""))

    n = len(day["temperature_2m_max"])
    if when in ("tomorrow", "after") and n > 1:
        i = 1 if when == "tomorrow" else min(2, n - 1)
        return f"{name} " + line(i, "завтра" if i == 1 else "послезавтра")
    if when in ("week", "weekend", "days"):
        dates = day.get("time") or []
        idx = list(range(min(n, days or 7)))
        if when == "weekend" and dates:
            idx = [i for i in range(n) if datetime.fromisoformat(dates[i]).weekday() >= 5] or idx
        labels = []
        for i in idx:
            if dates:
                dt = datetime.fromisoformat(dates[i])
                labels.append(f"{WD[dt.weekday()]} {dt:%d.%m}")
            else:
                labels.append(["сегодня", "завтра", "послезавтра"][i] if i < 3 else f"+{i} дн")
        head = {"week": "на неделю", "weekend": "на выходные", "days": f"на {len(idx)} дн."}[when]
        return f"{name}, погода {head}:\n" + "\n".join(line(i, labels[k]) for k, i in enumerate(idx))
    c = d["current"]
    return (f"{name} сейчас: <b>{round(c['temperature_2m'])}°</b> (ощущается {round(c['apparent_temperature'])}°), "
            f"{CODES.get(c['weather_code'], '')}, ветер {round(c['wind_speed_10m'] / 3.6, 1)} м/с")


async def distance(question):
    m = DIST.search(question.strip())
    if not m:
        return None
    a, b = await geocode(m.group(1)), await geocode(m.group(2))
    if not a or not b:
        return None
    r = 6371
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    km = 2 * r * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
    route = f"https://yandex.ru/maps/?rtext={a[0]},{a[1]}~{b[0]},{b[1]}&rtt=auto"
    return (f"{a[2]} → {b[2]}: <b>≈ {nice(round(km))} км</b> по прямой, по дорогам обычно на 20-30% больше.\n"
            f'🗺 <a href="{route}">Маршрут в Яндекс Картах</a>')


# ---------- время ----------

TIME = re.compile(r"(?i)который час|сколько (сейчас )?времени|сколько время|какое (сегодня )?число|какой (сегодня )?день|какая (сегодня )?дата")


def clock(question):
    if not TIME.search(question):
        return None
    t = datetime.now(MSK)
    return f"Сейчас <b>{t:%H:%M}</b> по Москве, {DAYS[t.weekday()]}, {t.day} {MONTHS[t.month - 1]} {t.year}."


async def answer(question):
    """Точный ответ (HTML) или None, если вопрос не про это."""
    q = (question or "").strip()
    if not q:
        return None
    for fn in (calc, clock):
        res = fn(q)
        if res:
            return res
    for fn in (rate, weather, distance):
        try:
            res = await fn(q)
        except Exception:
            res = None
        if res:
            return res
    return None


def shop_url(query):
    return f"https://market.yandex.ru/search?text={quote_plus(query)}"
