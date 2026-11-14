import asyncio
import html
import json
import logging
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

from textutil import match_score, stems

log = logging.getLogger("archive.web")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
BOT_UA = "UguBot/1.0 (https://t.me/ugu_ai) aiohttp"
WIKI = "https://ru.wikipedia.org/w/api.php"
QUESTION = re.compile(r"(?i)^\s*(а\s+)?(скажи|подскажи|расскажи|объясни|найди|поищи|загугли|узнай)(\s+мне)?[,\s]+")
FILLER = re.compile(r"(?i)\b(в интернете|в инете|в гугле|пожалуйста|плиз|пж)\b")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9«\"(])")


def agent(url):
    return BOT_UA if "wikipedia.org" in url or "wikimedia.org" in url else UA


async def http_get(url, params=None, headers=None, timeout=12):
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(url, params=params, headers={"User-Agent": agent(url), "Accept-Language": "ru,en;q=0.8",
                                                          **(headers or {})}) as r:
                return r.status, await r.text()
    except Exception as e:
        log.warning("сеть: %s %s", url, e)
        return 0, ""


DEFINE = re.compile(r"(?i)^(?:что|кто)\s+(?:такое|такой|такая|такие|таков\w*|это|был|была|были)\s+(.+)$")
QWORDS = set("что кто как чем почему зачем сколько где когда какой какая какое какие каков ли же это такое такой "
             "такая такие есть был была были будет можно нужно надо сейчас сегодня".split())
JUNK = ("wiktionary.org", "reverso.net", "translate.", "calculator", "alice.yandex", "gramota.ru", "dic.academic",
        "kartaslov", "sinonim", "wordhunt", "morpher")


def clean_query(text):
    q = QUESTION.sub("", text or "")
    q = FILLER.sub("", q)
    return re.sub(r"\s+", " ", q).strip(" ?!.,")


def keywords(query):
    return " ".join(w for w in re.findall(r"[\wёЁ-]+", query) if w.lower() not in QWORDS)


async def wiki_titles(query, limit=3):
    status, body = await http_get(WIKI, {"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                                         "format": "json", "utf8": 1})
    if status != 200:
        return []
    try:
        return [x["title"] for x in json.loads(body)["query"]["search"]]
    except (ValueError, KeyError):
        return []


async def wiki_text(title):
    status, body = await http_get(WIKI, {"action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "plain",
                                         "redirects": 1, "titles": title, "format": "json", "utf8": 1})
    if status != 200:
        return ""
    try:
        pages = json.loads(body)["query"]["pages"]
        return next(iter(pages.values())).get("extract", "") or ""
    except (ValueError, KeyError, StopIteration):
        return ""


def wiki_url(title):
    return "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def sentences(text):
    out = []
    for para in (text or "").split("\n"):
        para = re.sub(r"\s*\([^()]{0,80}\)", "", para).strip()
        if len(para) < 30 or para.startswith("=="):
            continue
        out += [s.strip() for s in SENTENCE.split(para) if 25 <= len(s.strip()) <= 400]
    return out


def best_sentences(question, text, title="", n=2):
    sents = sentences(text)
    if not sents:
        return []
    subject = set(stems(title))
    focus = [w for w in stems(keywords(question)) if w not in subject]
    if not focus:
        return sents[:n]
    scored = [(match_score(focus, s) * 10 + match_score(list(subject), s) - i * 0.02, i, s)
              for i, s in enumerate(sents[:400])]
    top = sorted(scored, reverse=True)
    if top[0][0] < 9:
        return sents[:n]
    best = top[0]
    if best[1] == 0:
        return sents[:n]
    return [sents[0], best[2]] if len(sents[0]) + len(best[2]) <= 600 else [best[2]]


def bing_url(href):
    href = html.unescape(href)
    q = parse_qs(urlparse(href).query)
    if "bing.com/ck/" in href and "u" in q:
        import base64
        raw = q["u"][0]
        raw = raw[2:] if raw.startswith("a1") else raw
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf8")
        except (ValueError, UnicodeDecodeError):
            return href
    return href


def strip_tags(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def ddg_url(href):
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    return unquote(q["uddg"][0]) if "uddg" in q else href


def good_url(url):
    return url.startswith("http") and not any(j in url for j in JUNK) and not re.search(
        r"(duckduckgo|bing)\.com/(y\.js|ck/|aclick)", url)


def relevant(query, links):
    want = set(stems(keywords(query)))
    return [x for x in links if not want or want & set(stems(x[0] + " " + x[2]))]


async def web_links(query, n=3):
    """[(title, url, snippet)]: DuckDuckGo Lite, запасной Bing; только ссылки со словами из вопроса."""
    return relevant(query, await ddg_links(query, n + 2))[:n] or relevant(query, await bing_links(query, n + 3))[:n]


async def ddg_links(query, n):
    status, body = await http_get("https://lite.duckduckgo.com/lite/", {"q": query, "kl": "ru-ru"})
    if status != 200:
        return []
    links = []
    rows = re.findall(r"href=\"([^\"]+)\" class='result-link'>(.*?)</a>(.*?)(?=class='result-link'|$)", body, re.S)
    for href, title, rest in rows:
        url = ddg_url(href)
        if not good_url(url) or url in [x[1] for x in links]:
            continue
        p = re.search(r"class='result-snippet'>(.*?)</td>", rest, re.S)
        links.append((strip_tags(title), url, strip_tags(p.group(1)) if p else ""))
        if len(links) >= n:
            break
    return links


async def bing_links(query, n):
    status, body = await http_get("https://www.bing.com/search", {"q": query, "mkt": "ru-RU"})
    if status != 200:
        return []
    links = []
    for block in body.split('class="b_algo"')[1:]:
        a = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        url = bing_url(a.group(1))
        if not good_url(url) or "bing.com" in urlparse(url).netloc:
            continue
        p = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        snippet = re.sub(r"^\d{1,2} \w+\.? \d{4} г?\.?\s*·\s*", "", strip_tags(p.group(1)) if p else "")
        if url not in [x[1] for x in links]:
            links.append((strip_tags(a.group(2)), url, snippet))
        if len(links) >= n:
            break
    return links


HOW = re.compile(r"(?i)^(почему|зачем|отчего|как|каким образом)\b")


async def lookup(question):
    """Ответ из интернета: {'text': 1-2 предложения, 'source': (title, url) | None, 'links': [(title, url)]}."""
    query = clean_query(question)
    if not query:
        return None
    m = DEFINE.match(query)
    subject = m.group(1) if m else keywords(query) or query
    titles, found = await asyncio.gather(wiki_titles(subject), web_links(m.group(1) if m else query))
    text, source = "", None
    first = next((x for x in found if len(x[2]) >= 60), None)
    if HOW.match(query) and first:
        text, source = first[2], (first[0], first[1])
    else:
        for title in titles[:2]:
            body = await wiki_text(title)
            best = sentences(body)[:2] if m else best_sentences(query, body, title)
            if best:
                text, source = " ".join(best), (title, wiki_url(title))
                break
        if not text and first:
            text, source = first[2], (first[0], first[1])
    links = [(t, u) for t, u, _ in found if not source or u != source[1]]
    if source and "wikipedia.org" in source[1]:
        links = [x for x in links if "wikipedia.org" not in x[1]]
    if not text and not links:
        return None
    return {"text": text[:600], "source": source, "links": links[:2]}


def format_answer(res):
    if not res:
        return "Не нашёл в интернете, или сеть не отвечает. Спроси по-другому."
    lines = []
    if res["text"]:
        lines.append(html.escape(res["text"]))
    refs = ([res["source"]] if res["source"] else []) + res["links"]
    if refs:
        lines.append("")
        lines += [f'🔗 <a href="{html.escape(u, quote=True)}">{html.escape(t[:70] or u)}</a>' for t, u in refs[:3]]
    return "\n".join(lines)


async def images(query, n=20):
    """Картинки: [(url, thumb, w, h, title)]. DuckDuckGo, запасной путь Wikimedia Commons."""
    for source in (bing_images, ddg_images, commons_images):
        found = await source(query, n)
        if found:
            return found
    return []


async def ddg_images(query, n):
    status, page = await http_get("https://duckduckgo.com/", {"q": query, "iax": "images", "ia": "images"})
    m = re.search(r'vqd=["\']?([\d-]+)', page or "")
    if status != 200 or not m:
        return []
    status, body = await http_get("https://duckduckgo.com/i.js", {"l": "ru-ru", "o": "json", "q": query, "vqd": m.group(1),
                                                                   "f": ",,,", "p": "1"},
                                  headers={"Referer": "https://duckduckgo.com/"})
    if status != 200:
        return []
    try:
        res = json.loads(body).get("results", [])
    except ValueError:
        return []
    out = []
    for r in res:
        url, thumb = r.get("image", ""), r.get("thumbnail", "")
        if url.startswith("https://") and thumb.startswith("http") and re.search(r"\.(jpe?g)(\?|$)", url, re.I):
            out.append((url, thumb, int(r.get("width") or 0), int(r.get("height") or 0), r.get("title", "")))
        if len(out) >= n:
            break
    return out


async def bing_images(query, n):
    status, body = await http_get("https://www.bing.com/images/async", {"q": query, "first": 0, "count": n * 2,
                                                                         "setlang": "ru", "adlt": "strict"})
    if status != 200:
        return []
    out = []
    for raw in re.findall(r'class="iusc"[^>]*m="([^"]+)"', body):
        try:
            m = json.loads(html.unescape(raw))
        except ValueError:
            continue
        url, thumb = m.get("murl", ""), m.get("turl", "")
        if url.startswith("https://") and thumb.startswith("http") and re.search(r"\.(jpe?g)(\?|$)", url, re.I):
            out.append((url, thumb, 0, 0, m.get("t", "")))
        if len(out) >= n:
            break
    return out


async def commons_images(query, n):
    status, body = await http_get("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": f"{query} filetype:bitmap",
        "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 320, "format": "json"})
    if status != 200:
        return []
    try:
        pages = json.loads(body).get("query", {}).get("pages", {})
    except ValueError:
        return []
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") != "image/jpeg":
            continue
        out.append((info["url"], info.get("thumburl") or info["url"], info.get("width", 0), info.get("height", 0),
                    p.get("title", "").removeprefix("File:")))
    return out[:n]
