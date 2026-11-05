import base64
import html
from datetime import timedelta, timezone

MSK = timezone(timedelta(hours=3))
PART_LIMIT = 45 * 1024 * 1024

CSS = """
body{margin:0;background:#0e1621;color:#e8edf2;font:15px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
header{position:sticky;top:0;background:#17212b;padding:14px 16px;font-weight:600;border-bottom:1px solid #0b1118}
header small{display:block;font-weight:400;color:#7f91a4;margin-top:2px}
.wrap{max-width:760px;margin:0 auto;padding:12px 12px 40px}
.day{text-align:center;margin:18px 0 8px}
.day span{background:#1e2c3a;color:#aab7c4;padding:3px 10px;border-radius:12px;font-size:13px}
.m{display:flex;margin:4px 0}.m.out{justify-content:flex-end}
.b{max-width:78%;background:#182533;padding:7px 10px 5px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}
.out .b{background:#2b5278}
.who{font-size:13px;font-weight:600;color:#6ab3f3;margin-bottom:2px}
.t{font-size:11px;color:#8ea2b5;text-align:right;margin-top:2px}
.q{border-left:3px solid #6ab3f3;padding:2px 8px;margin:2px 0 5px;font-size:13px;color:#b8c7d6;background:rgba(255,255,255,.04);border-radius:4px}
.md{font-size:13px;color:#9fd29f}
img{display:block;max-width:100%;border-radius:8px;margin:3px 0}
"""


def _day(dt):
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def _bubble(m, by_id, owner_name):
    dt = m["date"].astimezone(MSK)
    who = owner_name if m["out"] else m["sender"]
    parts = [f'<div class="m{" out" if m["out"] else ""}"><div class="b">',
             f'<div class="who">{html.escape(who)}</div>']
    if m.get("reply_to") and m["reply_to"] in by_id:
        q = by_id[m["reply_to"]]
        qt = q["text"] or (f'[{q["media"]}]' if q["media"] else "")
        parts.append(f'<div class="q">{html.escape(qt[:160])}</div>')
    if m.get("thumb"):
        parts.append(f'<img src="data:image/jpeg;base64,{base64.b64encode(m["thumb"]).decode()}" alt="">')
    if m["media"]:
        parts.append(f'<div class="md">[{html.escape(m["media"])}]</div>')
    if m["text"]:
        parts.append(html.escape(m["text"]))
    parts.append(f'<div class="t">{dt.strftime("%H:%M")}</div></div></div>')
    return "".join(parts)


def build_html(messages, title, owner_name, period=""):
    """Возвращает список HTML-документов (частей), каждая не больше PART_LIMIT."""
    by_id = {m["id"]: m for m in messages}
    head = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{CSS}</style>'
            f'</head><body><header>{html.escape(title)}<small>{html.escape(period)} · сообщений: '
            f'{len(messages)}{{PART}}</small></header><div class="wrap">')
    tail = "</div></body></html>"
    parts, cur, size, last_day = [], [], 0, None
    for m in messages:
        chunk = ""
        day = _day(m["date"].astimezone(MSK))
        if day != last_day:
            chunk += f'<div class="day"><span>{day}</span></div>'
            last_day = day
        chunk += _bubble(m, by_id, owner_name)
        n = len(chunk.encode())
        if cur and size + n > PART_LIMIT - 4096:
            parts.append(cur)
            cur, size = [], 0
            chunk = f'<div class="day"><span>{day}</span></div>' + _bubble(m, by_id, owner_name)
            n = len(chunk.encode())
        cur.append(chunk)
        size += n
    parts.append(cur)
    total = len(parts)
    out = []
    for i, body in enumerate(parts, 1):
        mark = f" · часть {i} из {total}" if total > 1 else ""
        out.append(head.replace("{PART}", mark) + "".join(body) + tail)
    return out


def build_txt(messages, title, owner_name):
    by_id = {m["id"]: m for m in messages}
    lines = [title, ""]
    for m in messages:
        dt = m["date"].astimezone(MSK).strftime("%d.%m.%Y %H:%M")
        who = owner_name if m["out"] else m["sender"]
        text = m["text"] or ""
        if m["media"]:
            text = f"[{m['media']}] {text}".strip()
        if m.get("reply_to") and m["reply_to"] in by_id:
            q = by_id[m["reply_to"]]["text"] or ""
            text = f"(в ответ на «{q[:60]}») {text}"
        lines.append(f"[{dt}] {who}: {text}")
    return "\n".join(lines) + "\n"
