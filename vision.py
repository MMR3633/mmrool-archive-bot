import hashlib
import logging
import os
import re
import tempfile
import threading
import time
import urllib.request

log = logging.getLogger("archive.vision")

HF_BASES = [b for b in (os.environ.get("HF_ENDPOINT", "").rstrip("/"), "https://huggingface.co", "https://hf-mirror.com") if b]
HF_REPO = "Xenova/clip-vit-base-patch32"
MS_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv5"

FILES = {
    "clip/vision.onnx": ("hf", "onnx/vision_model_quantized.onnx", "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"),
    "clip/text.onnx": ("hf", "onnx/text_model_quantized.onnx", "73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a"),
    "clip/tokenizer.json": ("hf", "tokenizer.json", "f7f3b7af117d467b58374797691a6438d3e6b9e9cef800dfd5dced7f697a90cd"),
    "ocr/det.onnx": ("ms", "det/ch_PP-OCRv5_det_mobile.onnx", "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    "ocr/rec.onnx": ("ms", "rec/eslav_PP-OCRv5_rec_mobile.onnx", "08705d6721849b1347d26187f15a5e362c431963a2a62bfff4feac578c489aab"),
}

MEAN = (0.48145466, 0.4578275, 0.40821073)
STD = (0.26862954, 0.26130258, 0.27577711)
MAX_SIDE = 1600
OCR_SIDE = 1280
MAX_PIXELS = 120_000_000
LOGIT_SCALE = 100.0

_state = {"clip": None, "ocr": None, "lock": threading.Lock(), "run": threading.Lock(), "load_sec": None}

VOCAB = """
человек|a portrait of a person
селфи|a selfie of a person
группа людей|a group of people
толпа|a crowd of people
ребёнок|a child
младенец|a baby
мужчина|a man
женщина|a woman
влюблённая пара|a couple in love
свадьба|a wedding
кот|a cat
котёнок|a kitten
собака|a dog
щенок|a puppy
птица|a bird
попугай|a parrot
голубь|a pigeon
утка|a duck
курица|a chicken
лошадь|a horse
корова|a cow
овца|a sheep
коза|a goat
верблюд|a camel
рыба|a fish
хомяк|a hamster
кролик|a rabbit
обезьяна|a monkey
медведь|a bear
лиса|a fox
волк|a wolf
лев|a lion
тигр|a tiger
слон|an elephant
олень|a deer
белка|a squirrel
ёж|a hedgehog
змея|a snake
черепаха|a turtle
лягушка|a frog
бабочка|a butterfly
насекомое|an insect
паук|a spider
еда|a plate of food
пицца|a pizza
бургер|a burger
суши|sushi
торт|a cake
пирожное|a pastry
мороженое|ice cream
салат|a salad
суп|a soup
макароны|pasta
мясо|a meat dish
шашлык|a shish kebab
пельмени|dumplings
блины|pancakes
хлеб|bread
яйца|eggs
фрукты|fruits
яблоко|an apple
банан|a banana
арбуз|a watermelon
овощи|vegetables
картошка|potatoes
шоколад|chocolate
конфеты|candies
завтрак|a breakfast
кофе|a cup of coffee
чай|a cup of tea
пиво|beer
вино|wine
коктейль|a cocktail
напиток|a drink
бутылка|a bottle
ресторан|a restaurant interior
машина|a car
такси|a taxi
грузовик|a truck
автобус|a bus
мотоцикл|a motorcycle
велосипед|a bicycle
самокат|a scooter
самолёт|an airplane
вертолёт|a helicopter
поезд|a train
корабль|a ship
лодка|a boat
дорога|a road
пробка на дороге|a traffic jam
парковка|a parking lot
город|a city
небоскрёбы|skyscrapers
здание|a building
улица|a street
мост|a bridge
площадь|a city square
церковь|a church
мечеть|a mosque
замок|a castle
памятник|a monument
двор|a courtyard between apartment blocks
квартира|an apartment interior
комната|a room
спальня|a bedroom
ванная|a bathroom
кухня|a kitchen
офис|an office
магазин|a shop
торговый центр|a shopping mall
рынок|a market
школа|a classroom
больница|a hospital
спортзал|a gym
стадион|a stadium
аэропорт|an airport
вокзал|a railway station
природа|nature
лес|a forest
горы|mountains
море|the sea
пляж|a beach
озеро|a lake
река|a river
водопад|a waterfall
закат|a sunset
небо|the sky
облака|clouds
снег|snow
дождь|rain
гроза|a thunderstorm
поле|a field
пустыня|a desert
остров|an island
сад|a garden
дерево|a tree
цветы|flowers
розы|roses
букет|a bouquet of flowers
осень|an autumn landscape
звёздное небо|a starry night sky
радуга|a rainbow
одежда|clothes
платье|a dress
куртка|a jacket
футболка|a t-shirt
обувь|shoes
кроссовки|sneakers
сумка|a bag
рюкзак|a backpack
чемодан|a suitcase
часы|a wrist watch
очки|glasses
украшения|jewelry
косметика|cosmetics
духи|a perfume bottle
деньги|money banknotes
монеты|coins
банковская карта|a bank card
телефон|a smartphone
ноутбук|a laptop
компьютер|a desktop computer
телевизор|a television
наушники|headphones
клавиатура|a keyboard
фотоаппарат|a camera
игрушка|a toy
книга|a book
мебель|furniture
диван|a sofa
кровать|a bed
стол|a table
стул|a chair
лампа|a lamp
инструменты|tools
посуда|dishes
нож|a knife
ключи|keys
подарок|a gift box
воздушные шары|balloons
свечи|candles
ёлка|a christmas tree
фейерверк|fireworks
таблетки|pills and medicine
сигареты|cigarettes
оружие|a weapon
документ|a scanned document
паспорт|a passport
чек|a store receipt
договор|a contract with signatures
таблица|a table with numbers
график|a chart
схема|a diagram
чертёж|a technical drawing
карта местности|a map
рукописный текст|handwritten text
страница книги|a page of a book
доска|a whiteboard with writing
плакат|a poster
вывеска|a shop sign
ценник|a price tag
меню|a menu
билет|a ticket
QR-код|a qr code
рентген|a medical x-ray
скриншот телефона|a screenshot of a smartphone screen
скриншот переписки|a screenshot of a messenger chat conversation
скриншот соцсети|a screenshot of a social media feed
скриншот сайта|a screenshot of a website
скриншот приложения|a screenshot of a mobile app
скриншот банка|a screenshot of a banking app
скриншот карты|a screenshot of a map application
скриншот компьютера|a screenshot of a computer desktop
скриншот игры|a screenshot of a video game
скриншот кода|a screenshot of source code
скриншот таблицы|a screenshot of a spreadsheet
мем|a meme with text
комикс|a comic strip
рисунок|a drawing
аниме|an anime illustration
иллюстрация|a digital illustration
логотип|a logo
открытка|a greeting card
стикер|a sticker
коллаж|a collage of photos
футбол|a football match
баскетбол|a basketball game
теннис|a tennis player
плавание|swimming
тренировка|a workout
единоборства|martial arts
йога|yoga
лыжи|skiing
шахматы|a chess board
видеоигры|a gamepad and video games
праздник|a party celebration
день рождения|a birthday party
концерт|a concert
сцена|a stage performance
пикник|a picnic
рыбалка|fishing
путешествие|a travel photo with a landmark
тёмное фото|a dark blurry photo
стена|a plain wall
"""

_PHOTO_GROUP_PREFIX = "скриншот"
DOC_LABELS = {"документ", "паспорт", "чек", "договор", "таблица", "рукописный текст", "страница книги"}


def _vocab():
    out = []
    for line in VOCAB.strip().splitlines():
        ru, en = line.split("|")
        out.append((ru.strip(), "a photo of " + en.strip() if not en.startswith("a screenshot") else en.strip()))
    return out


def threads():
    env = os.environ.get("VISION_THREADS")
    if env:
        return max(1, int(env))
    return max(2, min(4, os.cpu_count() or 2))


def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(urls, dest, sha):
    last = None
    for url in urls:
        for attempt in range(2):
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".part")
            os.close(fd)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "tgarchive-vision/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                if _sha(tmp) != sha:
                    raise OSError("контрольная сумма не совпала")
                os.replace(tmp, dest)
                return
            except Exception as e:
                last = e
                log.warning("зрение: не скачалось %s (%s)", url, e)
                time.sleep(1)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
    raise RuntimeError(f"не удалось скачать модель {os.path.basename(dest)}: {last}")


def _ensure_files(model_dir):
    paths = {}
    for rel, (src, name, sha) in FILES.items():
        dest = os.path.join(model_dir, *rel.split("/"))
        paths[rel] = dest
        if os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        urls = [f"{b}/{HF_REPO}/resolve/main/{name}" for b in HF_BASES] if src == "hf" else [f"{MS_BASE}/{name}"]
        log.info("зрение: скачиваю %s", rel)
        _download(urls, dest, sha)
    return paths


def _session(path, n):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = n
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False
    so.log_severity_level = 3
    return ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])


def _encode_text(sess, tok, prompts):
    import numpy as np
    out = []
    for i in range(0, len(prompts), 32):
        enc = tok.encode_batch(prompts[i:i + 32])
        width = max(len(e.ids) for e in enc)
        ids = np.zeros((len(enc), width), dtype=np.int64)
        for j, e in enumerate(enc):
            ids[j, :len(e.ids)] = e.ids
        out.append(sess.run(None, {"input_ids": ids})[0])
    emb = np.concatenate(out).astype("float32")
    return emb / np.linalg.norm(emb, axis=1, keepdims=True)


def _text_embeddings(model_dir, sess, tok, vocab):
    import numpy as np
    key = hashlib.sha1("\n".join(p for _, p in vocab).encode()).hexdigest()[:10]
    path = os.path.join(model_dir, "clip", f"text_emb_{key}.npy")
    if os.path.exists(path):
        try:
            emb = np.load(path)
            if emb.shape[0] == len(vocab):
                return emb
        except (OSError, ValueError):
            pass
    emb = _encode_text(sess, tok, [p for _, p in vocab])
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")
    with os.fdopen(fd, "wb") as f:
        np.save(f, emb)
    os.replace(tmp, path)
    return emb


def _make_ocr(paths, n):
    from rapidocr import RapidOCR
    return RapidOCR(params={
        "Det.model_path": paths["ocr/det.onnx"], "Rec.model_path": paths["ocr/rec.onnx"],
        "Det.limit_type": "max", "Det.limit_side_len": OCR_SIDE,
        "Global.use_cls": False, "Global.max_side_len": OCR_SIDE, "Global.min_side_len": 16,
        "Global.log_level": "error",
        "EngineConfig.onnxruntime.intra_op_num_threads": n,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.enable_cpu_mem_arena": False})


def load(model_dir):
    with _state["lock"]:
        if _state["clip"] is not None:
            return
        t = time.time()
        os.makedirs(model_dir, exist_ok=True)
        paths = _ensure_files(model_dir)
        n = threads()
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(paths["clip/tokenizer.json"])
        tok.no_padding()
        tok.enable_truncation(77)
        vocab = _vocab()
        text_sess = _session(paths["clip/text.onnx"], n)
        emb = _text_embeddings(model_dir, text_sess, tok, vocab)
        del text_sess
        vis = _session(paths["clip/vision.onnx"], n)
        ocr = _make_ocr(paths, n)
        _state["ocr"] = ocr
        _state["clip"] = {"vision": vis, "emb": emb, "labels": [ru for ru, _ in vocab]}
        _state["load_sec"] = round(time.time() - t, 1)
        log.info("зрение: модели загружены за %s с, потоков %s, память %s МБ", _state["load_sec"], n, rss_mb())


def _open(path):
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        im = Image.open(path)
        if im.width * im.height > MAX_PIXELS:
            raise ValueError("Слишком большое изображение")
        im.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))
        im.load()
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
    except ValueError:
        raise ValueError("Не удалось открыть изображение: файл слишком большой или повреждён")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, EOFError):
        raise ValueError("Не удалось открыть изображение: файл повреждён или это не картинка")
    if max(im.size) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    if min(im.size) < 2:
        raise ValueError("Не удалось открыть изображение: слишком маленькое")
    return im


def _clip_input(im):
    import numpy as np
    from PIL import Image
    w, h = im.size
    k = 224 / min(w, h)
    nw, nh = max(224, round(w * k)), max(224, round(h * k))
    im = im.resize((nw, nh), Image.Resampling.BICUBIC)
    l, t = (nw - 224) // 2, (nh - 224) // 2
    a = np.asarray(im.crop((l, t, l + 224, t + 224)), dtype="float32") / 255
    a = (a - np.array(MEAN, dtype="float32")) / np.array(STD, dtype="float32")
    return a.transpose(2, 0, 1)[None].astype("float32")


def _labels(im, top=3):
    import numpy as np
    c = _state["clip"]
    v = c["vision"].run(None, {"pixel_values": _clip_input(im)})[0]
    v = v / np.linalg.norm(v, axis=1, keepdims=True)
    logits = LOGIT_SCALE * (v @ c["emb"].T)[0]
    e = np.exp(logits - logits.max())
    p = e / e.sum()
    order = np.argsort(-p)
    return [(c["labels"][i], round(float(p[i]), 4)) for i in order[:top]], {c["labels"][i]: float(p[i]) for i in range(len(p))}


def _ocr_lines(im):
    import numpy as np
    r = _state["ocr"](np.ascontiguousarray(np.asarray(im)[:, :, ::-1]))
    if r is None or r.txts is None or r.boxes is None:
        return []
    items = []
    for box, txt, score in zip(r.boxes, r.txts, r.scores):
        txt = (txt or "").strip()
        if not txt or float(score) < 0.55:
            continue
        ys, xs = box[:, 1], box[:, 0]
        items.append([float(ys.mean()), float(ys.max() - ys.min()), float(xs.min()), txt])
    items.sort(key=lambda x: x[0])
    lines = []
    for it in items:
        if lines and abs(it[0] - lines[-1]["y"]) < 0.5 * max(it[1], lines[-1]["h"]):
            lines[-1]["parts"].append(it)
        else:
            lines.append({"y": it[0], "h": it[1], "parts": [it]})
    return [" ".join(p[3] for p in sorted(l["parts"], key=lambda p: p[2])) for l in lines]


def _kind(im, lines, probs):
    shot = sum(p for k, p in probs.items() if k.startswith(_PHOTO_GROUP_PREFIX))
    doc = sum(p for k, p in probs.items() if k in DOC_LABELS)
    top = max(probs, key=probs.get)
    chars = sum(len(re.findall(r"\w", l)) for l in lines)
    w, h = im.size
    if shot >= 0.4 or top.startswith(_PHOTO_GROUP_PREFIX):
        return "скриншот"
    if doc >= 0.4 or top in DOC_LABELS:
        return "документ"
    if chars >= 250 and len(lines) >= 8:
        return "документ"
    if h / w >= 1.7 and len(lines) >= 6 and chars >= 60:
        return "скриншот"
    return "фото"


def analyze(path, model_dir):
    load(model_dir)
    im = _open(path)
    with _state["run"]:
        t = time.time()
        top, probs = _labels(im)
        t_clip = time.time() - t
        t = time.time()
        lines = _ocr_lines(im)
        t_ocr = time.time() - t
    log.info("зрение: clip %.2f с, ocr %.2f с, строк %s", t_clip, t_ocr, len(lines))
    return {"text": "\n".join(lines), "labels": top, "kind": _kind(im, lines, probs)}


def describe(result):
    labels = result.get("labels") or []
    kind = result.get("kind") or "фото"
    parts = []
    if kind != "фото":
        parts.append(f"Это {kind}.")
    if labels:
        first, p = labels[0]
        rest = [l for l, q in labels[1:3] if q >= 0.08]
        if p >= 0.3:
            names = [f"{first} ({round(p * 100)}%)"] + rest
            parts.append("Похоже на: " + ", ".join(names) + ".")
        else:
            names = [first] + rest
            parts.append(f"Не уверен, возможно: {', '.join(names)} ({round(p * 100)}%).")
    text = re.sub(r"[—–]", "-", result.get("text") or "")
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    text = text.replace("«", '"').replace("»", '"')
    if len(re.findall(r"[^\W_]", text)) >= 3:
        head = " ".join(parts)
        room = max(40, 400 - len(head) - 22)
        if len(text) > room:
            text = text[:room].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
        parts.append(f"Текст на фото: «{text}»")
    else:
        parts.append("Текста не вижу.")
    out = " ".join(parts).strip()
    return out[:400] if out else "Не смог разобрать, что на фото."
