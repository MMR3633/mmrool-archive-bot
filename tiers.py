"""Тарифы Угу: Free / Lite / Pro / Ultra, дневные лимиты, оплата Telegram Stars, пробный период и рефералка."""
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

import archive_bot as ab
from timeparse import MSK

log = logging.getLogger("archive")
router = Router()

ORDER = ["free", "lite", "pro", "ultra"]
NAMES = {"free": "Free", "lite": "Lite", "pro": "Pro", "ultra": "Ultra"}
STARS = {"lite": 75, "pro": 230, "ultra": 600}
MONTH = 30
YEAR = 365
SUB_PERIOD = 2592000
FAIR = 3000
TRIAL_DAYS = 3
REF_TRIAL_DAYS = 7
REF_BONUS_DAYS = 7
LEVELS = [(10, "pro", "Pro навсегда"), (50, "ultra", "Ultra навсегда")]

# None = безлимит (с честным потолком FAIR в сутки для дневных). Картинки и поиск в интернете бесплатно всем.
FREE_KINDS = {"help", "chat", "images", "look", "shop", "web", "unknown"}
DAILY = {
    "ask": {"free": 30, "lite": 150, "pro": None, "ultra": None},
    "photo": {"free": 5, "lite": 30, "pro": None, "ultra": None},
    "fx": {"free": 5, "lite": 30, "pro": None, "ultra": None},
    "posts": {"free": 3, "lite": 20, "pro": 100, "ultra": None},
}
TOTAL = {
    "plans": {"free": 5, "lite": 30, "pro": 200, "ultra": None},
    "notes": {"free": 20, "lite": 200, "pro": 2000, "ultra": None},
}
LABELS = {"ask": "Запросы к Угу", "photo": "Что на фото", "fx": "Фото-эффекты",
          "posts": "Посты из каналов",
          "plans": "Напоминания и задачи", "notes": "Заметки"}
AFTER_PAY = {
    "lite": "Попробуй: «угубот, что у меня на неделе».",
    "pro": "Попробуй: «угубот, кратко за месяц» в любой переписке.",
    "ultra": "Теперь без лимитов. Попробуй: «угубот, договорённости за месяц».",
}


def now():
    return datetime.now(MSK)


def iso(dt):
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    with ab.db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS ugu_subs (user_id INTEGER PRIMARY KEY, tier TEXT, until TEXT, trial_used INTEGER DEFAULT 0,
            forever TEXT);
        CREATE TABLE IF NOT EXISTS ugu_usage (user_id INTEGER, day TEXT, key TEXT, n INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, day, key));
        CREATE TABLE IF NOT EXISTS ugu_refs (user_id INTEGER PRIMARY KEY, ref_id INTEGER, ts TEXT, paid INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS ugu_ref_clicks (ref_id INTEGER, user_id INTEGER, ts TEXT);
        CREATE TABLE IF NOT EXISTS ugu_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tier TEXT, period TEXT,
            stars INTEGER, charge_id TEXT UNIQUE, recurring INTEGER DEFAULT 0, ts TEXT);
        CREATE TABLE IF NOT EXISTS ugu_bonus (ref_id INTEGER, user_id INTEGER, days INTEGER, ts TEXT);
        """)


def sub_row(con, uid):
    return con.execute("SELECT * FROM ugu_subs WHERE user_id=?", (uid,)).fetchone()


def tier_of(uid, t=None):
    if uid and uid == ab.OWNER_ID:
        return "ultra"
    with ab.db() as con:
        return tier_of_con(con, uid, t)


def until_of(uid):
    with ab.db() as con:
        r = sub_row(con, uid)
    return r["until"] if r and r["until"] and r["until"] > iso(now()) else None


def extend(con, uid, tier, days):
    """Продлевает тариф: тот же или выше — от конца текущего срока, ниже — не трогаем, копим дни у текущего."""
    r = sub_row(con, uid)
    t = now()
    if r and r["until"] and r["until"] > iso(t):
        cur = r["tier"]
        base = datetime.strptime(r["until"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)
        tier = tier if ORDER.index(tier) >= ORDER.index(cur) else cur
    else:
        base = t
    until = iso(base + timedelta(days=days))
    con.execute("INSERT INTO ugu_subs (user_id, tier, until) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET"
                " tier=excluded.tier, until=excluded.until", (uid, tier, until))
    return until


def start_trial(uid, days=TRIAL_DAYS):
    """Пробный Lite один раз на человека. Возвращает дату конца или None."""
    if not uid or uid == ab.OWNER_ID:
        return None
    with ab.db() as con:
        r = sub_row(con, uid)
        if r and r["trial_used"]:
            return None
        until = extend(con, uid, "lite", days)
        con.execute("UPDATE ugu_subs SET trial_used=1 WHERE user_id=?", (uid,))
    return until


def on_start(uid, arg=""):
    """/start: рефералка r_ID и пробный период. Возвращает строку для приветствия или ""."""
    ref = None
    if arg.startswith("r_") and arg[2:].isdigit():
        ref = int(arg[2:])
        if ref == uid:
            ref = None
    days = TRIAL_DAYS
    with ab.db() as con:
        if ref:
            con.execute("INSERT INTO ugu_ref_clicks VALUES (?,?,?)", (ref, uid, iso(now())))
            known = con.execute("SELECT 1 FROM ugu_refs WHERE user_id=?", (uid,)).fetchone()
            seen = con.execute("SELECT 1 FROM ugu_subs WHERE user_id=?", (uid,)).fetchone()
            if not known and not seen:
                con.execute("INSERT INTO ugu_refs (user_id, ref_id, ts) VALUES (?,?,?)", (uid, ref, iso(now())))
                days = REF_TRIAL_DAYS
    until = start_trial(uid, days)
    if not until:
        return ""
    return f"🎁 Дарю {days} {plural(days, 'день', 'дня', 'дней')} Lite бесплатно, до {until[8:10]}.{until[5:7]}."


def plural(n, one, few, many):
    n = abs(n) % 100
    if 10 < n < 20:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def used(uid, key, day=None):
    with ab.db() as con:
        r = con.execute("SELECT n FROM ugu_usage WHERE user_id=? AND day=? AND key=?",
                        (uid, day or now().strftime("%Y-%m-%d"), key)).fetchone()
    return r["n"] if r else 0


def use(uid, key):
    """Списывает одно дневное действие. (можно, тариф, предел)."""
    tier = tier_of(uid)
    cap = DAILY[key][tier]
    limit = FAIR if cap is None else cap
    day = now().strftime("%Y-%m-%d")
    with ab.db() as con:
        r = con.execute("SELECT n FROM ugu_usage WHERE user_id=? AND day=? AND key=?", (uid, day, key)).fetchone()
        n = r["n"] if r else 0
        if n >= limit:
            return False, tier, cap
        con.execute("INSERT INTO ugu_usage VALUES (?,?,?,1) ON CONFLICT(user_id, day, key) DO UPDATE SET n=n+1",
                    (uid, day, key))
    return True, tier, cap


def count_total(uid, key):
    with ab.db() as con:
        if key == "notes":
            con.execute("CREATE TABLE IF NOT EXISTS ugu_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, title TEXT, "
                        "body TEXT, created TEXT, pinned INTEGER DEFAULT 0)")
            return con.execute("SELECT COUNT(*) FROM ugu_notes WHERE owner_id=?", (uid,)).fetchone()[0]
        return (con.execute("SELECT COUNT(*) FROM reminders WHERE owner_id=? AND status='active'", (uid,)).fetchone()[0]
                + con.execute("SELECT COUNT(*) FROM tasks WHERE owner_id=? AND done=0", (uid,)).fetchone()[0])


def room(uid, key):
    """Можно ли добавить ещё одну заметку / напоминание. (можно, тариф, предел)."""
    tier = tier_of(uid)
    cap = TOTAL[key][tier]
    return cap is None or count_total(uid, key) < cap, tier, cap


def limit_text(key, tier, cap):
    what = LABELS.get(key, "лимит").lower()
    nxt = NAMES[ORDER[min(ORDER.index(tier) + 1, len(ORDER) - 1)]]
    if key in TOTAL:
        return (f"⟪sad⟫ На тарифе {NAMES[tier]} {what}: не больше {cap}. Удали лишнее или перейди на {nxt}: "
                f"кнопка «Угу» внизу → тариф.")
    return (f"⟪sad⟫ {LABELS[key]} на {NAMES[tier]}: {cap} в день, на сегодня всё. Завтра снова можно, "
            f"а без ожидания: {nxt}, кнопка «Угу» внизу → тариф.")


def limits_view(uid):
    tier = tier_of(uid)
    out = []
    for key in ("ask", "photo", "fx", "posts"):
        out.append({"key": key, "name": LABELS[key], "used": used(uid, key), "max": DAILY[key][tier]})
    for key in ("plans", "notes"):
        out.append({"key": key, "name": LABELS[key], "used": count_total(uid, key), "max": TOTAL[key][tier]})
    return out


def price(tier, period):
    month = STARS[tier]
    return month if period == "month" else round(month * 12 * 0.8)


async def invoice_link(bot: Bot, uid, tier, period):
    if tier not in STARS or period not in ("month", "year"):
        raise ValueError("нет такого тарифа")
    amount = price(tier, period)
    title = f"Угу {NAMES[tier]}" + (" на год" if period == "year" else "")
    desc = ("Подписка, Telegram сам продлевает раз в месяц. Отменить можно в любой момент." if period == "month"
            else "Оплата сразу за 12 месяцев со скидкой 20%.")
    extra = {"subscription_period": SUB_PERIOD} if period == "month" else {}
    return await bot.create_invoice_link(title=title, description=desc, payload=f"sub:{tier}:{period}:{uid}",
                                         currency="XTR", prices=[LabeledPrice(label=title, amount=amount)], **extra)


def parse_payload(payload):
    parts = (payload or "").split(":")
    if len(parts) != 4 or parts[0] != "sub" or parts[1] not in STARS or parts[2] not in ("month", "year"):
        return None
    try:
        return parts[1], parts[2], int(parts[3])
    except ValueError:
        return None


def apply_payment(uid, tier, period, stars, charge_id, recurring=False):
    """Зачисляет оплату один раз на charge_id. Возвращает (until, бонус_пригласившему) или None, если уже было."""
    days = YEAR if period == "year" else MONTH
    with ab.db() as con:
        if con.execute("SELECT 1 FROM ugu_payments WHERE charge_id=?", (charge_id,)).fetchone():
            return None
        con.execute("INSERT INTO ugu_payments (user_id, tier, period, stars, charge_id, recurring, ts) VALUES (?,?,?,?,?,?,?)",
                    (uid, tier, period, stars, charge_id, int(recurring), iso(now())))
        until = extend(con, uid, tier, days)
        ref = con.execute("SELECT ref_id, paid FROM ugu_refs WHERE user_id=?", (uid,)).fetchone()
        bonus = None
        if ref and not ref["paid"]:
            con.execute("UPDATE ugu_refs SET paid=1 WHERE user_id=?", (uid,))
            rid = ref["ref_id"]
            cur = tier_of_con(con, rid)
            extend(con, rid, cur if cur != "free" else "lite", REF_BONUS_DAYS)
            con.execute("INSERT INTO ugu_bonus VALUES (?,?,?,?)", (rid, uid, REF_BONUS_DAYS, iso(now())))
            paid = con.execute("SELECT COUNT(*) FROM ugu_refs WHERE ref_id=? AND paid=1", (rid,)).fetchone()[0]
            for need, lvl, _ in LEVELS:
                if paid >= need:
                    con.execute("INSERT INTO ugu_subs (user_id, tier, until, forever) VALUES (?, 'free', NULL, ?)"
                                " ON CONFLICT(user_id) DO UPDATE SET forever=excluded.forever", (rid, lvl))
            bonus = rid
    return until, bonus


def tier_of_con(con, uid, t=None):
    r = sub_row(con, uid)
    if not r:
        return "free"
    best = r["forever"] or "free"
    if r["until"] and r["until"] > iso(t or now()) and ORDER.index(r["tier"]) > ORDER.index(best):
        best = r["tier"]
    return best


def partner_view(uid, username):
    with ab.db() as con:
        clicks = con.execute("SELECT COUNT(DISTINCT user_id) FROM ugu_ref_clicks WHERE ref_id=?", (uid,)).fetchone()[0]
        refs = con.execute("SELECT user_id, paid FROM ugu_refs WHERE ref_id=?", (uid,)).fetchall()
        connected = 0
        for r in refs:
            if con.execute("SELECT 1 FROM connections WHERE user_id=? AND enabled=1", (r["user_id"],)).fetchone():
                connected += 1
        paid = sum(1 for r in refs if r["paid"])
        hist = con.execute("SELECT days, ts FROM ugu_bonus WHERE ref_id=? ORDER BY ts DESC LIMIT 30", (uid,)).fetchall()
        bonus_days = con.execute("SELECT COALESCE(SUM(days),0) FROM ugu_bonus WHERE ref_id=?", (uid,)).fetchone()[0]
    nxt = next(((need, reward) for need, _, reward in LEVELS if paid < need), None)
    return {
        "link": f"https://t.me/{username}?start=r_{uid}",
        "stats": {"clicks": clicks, "connected": connected, "paid": paid, "bonus_days": bonus_days},
        "level": {"paid": paid, "next_target": nxt[0] if nxt else 0, "next_reward": nxt[1] if nxt else ""},
        "history": [{"date": h["ts"][:10], "name": "Друг оплатил", "days": h["days"]} for h in hist],
    }


# ---------- оплата в боте ----------

@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, bot: Bot):
    ok = parse_payload(query.invoice_payload) is not None and query.currency == "XTR"
    await query.answer(ok=ok, error_message=None if ok else "Этот счёт устарел, открой тариф заново.")


@router.message(F.successful_payment)
async def on_paid(msg: Message, bot: Bot):
    pay = msg.successful_payment
    parsed = parse_payload(pay.invoice_payload)
    if not parsed:
        log.warning("оплата с непонятным payload: %s", pay.invoice_payload)
        return
    tier, period, _ = parsed
    uid = msg.from_user.id
    res = apply_payment(uid, tier, period, pay.total_amount, pay.telegram_payment_charge_id,
                        bool(getattr(pay, "is_recurring", False)))
    if not res:
        return
    until, bonus = res
    log.info("оплата: %s %s %s ⭐%s", uid, tier, period, pay.total_amount)
    await msg.answer(f"👻 Теперь ты на {NAMES[tier]}, до {until[8:10]}.{until[5:7]}.{until[:4]}.\n{AFTER_PAY[tier]}")
    if bonus:
        try:
            await bot.send_message(bonus, f"🎁 Друг, которого ты позвал, оплатил Угу. Тебе +{REF_BONUS_DAYS} дней тарифа.")
        except Exception as e:
            log.info("бонус пригласившему не доставлен: %s", e)


def tier_line(uid):
    tier = tier_of(uid)
    until = until_of(uid)
    tail = f" до {until[8:10]}.{until[5:7]}" if until and tier != "free" and uid != ab.OWNER_ID else ""
    return f"Тариф: <b>{NAMES[tier]}</b>{tail}"
