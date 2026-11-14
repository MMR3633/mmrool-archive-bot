"""Понимание по смыслу: фраза → вектор (multilingual-e5-small, ONNX), ближайшие примеры → намерение."""
import hashlib
import logging
import os
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger("archive.semantic")

REPO = "Xenova/multilingual-e5-small"
FILES = {"model.onnx": "onnx/model_quantized.onnx", "tokenizer.json": "tokenizer.json"}
BASES = [b for b in (os.environ.get("HF_ENDPOINT", "").rstrip("/"), "https://huggingface.co", "https://hf-mirror.com") if b]
_state = {"sess": None, "tok": None, "lock": threading.Lock(), "cache": {}}


def _download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "UguBot/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)


def load(model_dir):
    with _state["lock"]:
        if _state["sess"] is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer
        d = Path(model_dir)
        d.mkdir(parents=True, exist_ok=True)
        for name, path in FILES.items():
            dest = d / name
            if dest.exists() and dest.stat().st_size > 0:
                continue
            for base in BASES:
                try:
                    _download(f"{base}/{REPO}/resolve/main/{path}", dest)
                    break
                except Exception as e:
                    log.warning("смысл: не скачал %s с %s: %s", name, base, e)
            else:
                raise RuntimeError(f"не скачал модель смыслов {name}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(os.environ.get("SEMANTIC_THREADS", "2"))
        sess = ort.InferenceSession(str(d / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        tok.enable_truncation(max_length=64)
        tok.enable_padding(pad_id=1, pad_token="<pad>")
        _state["sess"], _state["tok"] = sess, tok
        log.info("смысл: модель загружена")


def embed(texts, model_dir):
    import numpy as np
    load(model_dir)
    sess, tok = _state["sess"], _state["tok"]
    enc = tok.encode_batch([f"query: {t.lower()}" for t in texts])
    ids = np.array([e.ids for e in enc], dtype=np.int64)
    mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
    feeds = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in [i.name for i in sess.get_inputs()]:
        feeds["token_type_ids"] = np.zeros_like(ids)
    out = sess.run(None, feeds)[0]
    m = mask[..., None].astype(np.float32)
    vec = (out * m).sum(1) / np.maximum(m.sum(1), 1e-9)
    return vec / np.linalg.norm(vec, axis=1, keepdims=True)


class Classifier:
    """Примеры намерений → векторы; вопрос → (лучшее намерение, сходство, второе, сходство)."""

    def __init__(self, examples, model_dir):
        self.model_dir = model_dir
        self.labels, texts = [], []
        for label, phrases in examples.items():
            for p in phrases:
                self.labels.append(label)
                texts.append(p)
        self.texts = texts
        self.key = hashlib.md5("\n".join(f"{l}|{t}" for l, t in zip(self.labels, texts)).encode()).hexdigest()[:12]
        self.matrix = None

    def ready(self):
        import numpy as np
        if self.matrix is None:
            cache = Path(self.model_dir) / f"examples_{self.key}.npy"
            if cache.exists():
                self.matrix = np.load(cache)
            else:
                self.matrix = embed(self.texts, self.model_dir)
                np.save(cache, self.matrix)
        return self

    def add(self, label, text):
        import numpy as np
        self.ready()
        self.matrix = np.vstack([self.matrix, embed([text], self.model_dir)])
        self.labels.append(label)
        self.texts.append(text)

    def rank(self, text):
        self.ready()
        sims = self.matrix @ embed([text], self.model_dir)[0]
        best = {}
        for label, s in zip(self.labels, sims):
            best[label] = max(best.get(label, -1.0), float(s))
        return sorted(best.items(), key=lambda x: -x[1])
