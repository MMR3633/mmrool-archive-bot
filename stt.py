import logging
import os
import re
import threading
import time

log = logging.getLogger("archive.stt")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

MODEL_NAME = os.environ.get("WHISPER_MODEL", "large-v3-turbo")
BEAM = int(os.environ.get("WHISPER_BEAM", "5"))
PROMPT = "Короче, смотри, бро, давай, ну типа, щас, ГС, кружок, бот, Захар, Расул."
_state = {"model": None, "lock": threading.Lock(), "dir": None, "load_sec": None}

HALLUCINATIONS = [
    r"продолжение следует\.*",
    r"субтитры (сделал|создавал|подготовил|делал)[^.!?]*[.!?]?",
    r"редактор субтитров[^.!?]*[.!?]?",
    r"корректор[^.!?]*[.!?]?",
    r"спасибо за просмотр[!.]*",
    r"подписывайтесь на канал[^.!?]*[.!?]?",
    r"ставьте лайки[^.!?]*[.!?]?",
    r"dimatorzok",
    r"amara\.org[^.!?]*[.!?]?",
]
_HALL = re.compile(r"\s*(?:" + "|".join(HALLUCINATIONS) + r")\s*", re.I)


def threads():
    env = os.environ.get("WHISPER_THREADS")
    if env:
        return max(1, int(env))
    return max(1, min(4, os.cpu_count() or 2))


def rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def load(download_root=None):
    with _state["lock"]:
        if _state["model"] is None:
            from faster_whisper import WhisperModel
            t = time.time()
            _state["model"] = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8",
                                           download_root=download_root, cpu_threads=threads())
            _state["load_sec"] = round(time.time() - t, 1)
            log.info("распознавание: модель %s загружена за %s с, потоков %s, память %s МБ",
                     MODEL_NAME, _state["load_sec"], threads(), rss_mb())
        return _state["model"]


def decode(path):
    import av
    import numpy as np
    c = av.open(path)
    r = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    for frame in c.decode(audio=0):
        for out in r.resample(frame):
            chunks.append(out.to_ndarray().flatten())
    c.close()
    if not chunks:
        return np.zeros(1, dtype="float32")
    return np.concatenate(chunks).astype("float32") / 32768


def _dedupe(parts):
    out = []
    for p in parts:
        key = p.lower().strip(" .,!?…")
        if not key:
            continue
        if len(out) >= 2 and out[-1].lower().strip(" .,!?…") == key and out[-2].lower().strip(" .,!?…") == key:
            continue
        out.append(p)
    return out


def clean(text):
    text = _HALL.sub(" ", text or "")
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    parts = _dedupe([p.strip() for p in parts])
    text = " ".join(parts)
    text = re.sub(r"\b(\w+)(?:[ ,]+\1\b){3,}", r"\1", text, flags=re.I)
    text = re.sub(r"\s+([,.!?…])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…":
        text += "."
    return text


def transcribe(path, download_root=None):
    model = load(download_root)
    audio = decode(path)
    t = time.time()
    segments, info = model.transcribe(
        audio, language="ru", beam_size=BEAM,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        condition_on_previous_text=False, temperature=[0.0, 0.2, 0.4, 0.6],
        initial_prompt=PROMPT)
    text = " ".join(s.text.strip() for s in segments)
    took = time.time() - t
    log.info("распознавание: %.1f с аудио за %.1f с", len(audio) / 16000, took)
    return clean(text)
