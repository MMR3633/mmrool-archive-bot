"""Фото-эффекты для Угу: демотиватор, шакал, жмых, текст на пикчу. Pillow + numpy, шрифты качаются один раз."""
import io
import logging
import os
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger("archive.fx")

FONTS = {"serif": "https://github.com/google/fonts/raw/main/ofl/ptserif/PT_Serif-Web-Regular.ttf",
         "meme": "https://github.com/google/fonts/raw/main/ofl/oswald/Oswald%5Bwght%5D.ttf"}
LOCAL = {"serif": ["C:/Windows/Fonts/times.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
         "meme": ["C:/Windows/Fonts/impact.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]}
MAX_SIDE = 1280


def font_path(kind, font_dir):
    d = Path(font_dir)
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"{kind}.ttf"
    if not target.exists():
        try:
            tmp = target.with_suffix(".part")
            with urllib.request.urlopen(urllib.request.Request(FONTS[kind], headers={"User-Agent": "UguBot/1.0"}),
                                        timeout=60) as r:
                tmp.write_bytes(r.read())
            tmp.replace(target)
        except Exception as e:
            log.warning("fx: шрифт %s не скачал: %s", kind, e)
            for p in LOCAL[kind]:
                if os.path.exists(p):
                    return p
            return None
    return str(target)


def get_font(kind, size, font_dir):
    path = font_path(kind, font_dir)
    if not path:
        return ImageFont.load_default(size)
    f = ImageFont.truetype(path, size)
    if kind == "meme":
        try:
            f.set_variation_by_axes([700])
        except Exception:
            pass
    return f


def load(path):
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        raise ValueError(f"не открыл картинку: {e}")
    im = im.convert("RGB")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def to_jpeg(im, quality=92):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def demotivator(path, title, subtitle="", font_dir="fonts"):
    im = load(path)
    im.thumbnail((900, 900))
    w, h = im.size
    pad, border = int(w * 0.09), 3
    big = get_font("serif", max(28, int(w * 0.085)), font_dir)
    small = get_font("serif", max(18, int(w * 0.045)), font_dir)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    t_lines = wrap(probe, title.upper() if len(title) < 40 else title, big, w + pad)
    s_lines = wrap(probe, subtitle, small, w + pad) if subtitle else []
    line_h, sline_h = int(big.size * 1.25), int(small.size * 1.35)
    W = w + pad * 2
    H = pad + h + int(pad * 0.6) + line_h * len(t_lines) + sline_h * len(s_lines) + pad
    canvas = Image.new("RGB", (W, H), "black")
    canvas.paste(im, (pad, pad))
    d = ImageDraw.Draw(canvas)
    gap = border + 4
    d.rectangle([pad - gap, pad - gap, pad + w + gap - 1, pad + h + gap - 1], outline="white", width=border)
    y = pad + h + int(pad * 0.6)
    for line in t_lines:
        d.text((W / 2, y), line, font=big, fill="white", anchor="ma")
        y += line_h
    for line in s_lines:
        d.text((W / 2, y), line, font=small, fill="#dddddd", anchor="ma")
        y += sline_h
    return to_jpeg(canvas)


def shakal(path, level=3):
    """«Шакальное» качество: уменьшение, пережатие JPEG по кругу, пересвет."""
    im = load(path)
    w, h = im.size
    for _ in range(level):
        small = im.resize((max(40, w // 5), max(40, h // 5)), Image.NEAREST)
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=4)
        im = Image.open(io.BytesIO(buf.getvalue())).convert("RGB").resize((w, h), Image.NEAREST)
    arr = np.asarray(im).astype(np.float32)
    arr = np.clip((arr - 128) * 1.35 + 140, 0, 255).astype(np.uint8)
    return to_jpeg(Image.fromarray(arr), quality=8)


def _energy(gray):
    gx = np.abs(np.diff(gray, axis=1, append=gray[:, -1:]))
    gy = np.abs(np.diff(gray, axis=0, append=gray[-1:, :]))
    return gx + gy


def _carve(arr, n):
    """Убирает n вертикальных швов с наименьшей «энергией» (seam carving): так и получается «жмых»."""
    for _ in range(n):
        h, w = arr.shape[:2]
        gray = arr.mean(axis=2)
        cost = _energy(gray).astype(np.float64)
        for y in range(1, h):
            prev = cost[y - 1]
            left = np.concatenate(([np.inf], prev[:-1]))
            right = np.concatenate((prev[1:], [np.inf]))
            cost[y] += np.minimum(np.minimum(left, prev), right)
        seam = np.empty(h, dtype=np.int64)
        seam[-1] = int(np.argmin(cost[-1]))
        for y in range(h - 2, -1, -1):
            x = seam[y + 1]
            lo, hi = max(0, x - 1), min(w, x + 2)
            seam[y] = lo + int(np.argmin(cost[y, lo:hi]))
        mask = np.ones((h, w), dtype=bool)
        mask[np.arange(h), seam] = False
        arr = arr[mask].reshape(h, w - 1, 3)
    return arr


def zhmykh(path, strength=0.72):
    im = load(path)
    im.thumbnail((260, 260))
    w, h = im.size
    arr = np.asarray(im).astype(np.uint8)
    arr = _carve(arr, int(w * strength))
    arr = _carve(arr.transpose(1, 0, 2), int(h * strength)).transpose(1, 0, 2)
    out = Image.fromarray(np.ascontiguousarray(arr)).resize((w * 3, h * 3), Image.BICUBIC)
    return to_jpeg(out.filter(ImageFilter.SHARPEN))


def meme_text(path, top="", bottom="", font_dir="fonts"):
    """Белые буквы с чёрной обводкой сверху и снизу, как в классических мемах."""
    im = load(path)
    w, h = im.size
    d = ImageDraw.Draw(im)
    for text, at_top in ((top, True), (bottom, False)):
        text = (text or "").strip().upper()
        if not text:
            continue
        size = max(24, int(h * 0.11))
        while size > 16:
            font = get_font("meme", size, font_dir)
            lines = wrap(d, text, font, int(w * 0.94))
            if len(lines) <= 3:
                break
            size = int(size * 0.85)
        line_h = int(font.size * 1.12)
        y = int(h * 0.03) if at_top else h - int(h * 0.04) - line_h * len(lines)
        for line in lines:
            d.text((w / 2, y), line, font=font, fill="white", anchor="ma", stroke_width=max(2, font.size // 14),
                   stroke_fill="black")
            y += line_h
    return to_jpeg(im)
