import asyncio
import io
import logging
import os
import shutil
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

log = logging.getLogger("archive.user")

API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
MAX_SEND = 50 * 1024 * 1024
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".gif"}


class UserClient:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.client = None
        self.pending_qr = None
        self.pending_phone = None
        self.lock = asyncio.Lock()

    async def start(self):
        self.client = TelegramClient(str(self.data_dir / "user"), API_ID, API_HASH,
                                     connection_retries=3, retry_delay=5, auto_reconnect=True,
                                     receive_updates=False)
        try:
            await self.client.connect()
        except Exception as e:
            log.warning("аккаунт: нет связи на старте: %s", e)

    async def ready(self):
        if self.client is None:
            return False
        try:
            if not self.client.is_connected():
                await self.client.connect()
            return await self.client.is_user_authorized()
        except Exception as e:
            log.warning("аккаунт: проверка входа не прошла: %s", e)
            return False

    async def qr_png(self):
        import qrcode
        if not self.client.is_connected():
            await self.client.connect()
        self.pending_qr = await self.client.qr_login()
        img = qrcode.make(self.pending_qr.url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    async def wait_qr(self, timeout=180):
        try:
            await self.pending_qr.wait(timeout)
            return "ok"
        except SessionPasswordNeededError:
            return "password"
        except asyncio.TimeoutError:
            return "timeout"

    async def password(self, pwd):
        await self.client.sign_in(password=pwd)

    async def send_code(self, phone):
        if not self.client.is_connected():
            await self.client.connect()
        sent = await self.client.send_code_request(phone)
        self.pending_phone = (phone, sent.phone_code_hash)

    async def sign_in_code(self, code):
        phone, code_hash = self.pending_phone
        try:
            await self.client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            return "ok"
        except SessionPasswordNeededError:
            return "password"

    async def resolve(self, target):
        target = str(target).strip()
        if target.lstrip("-").isdigit():
            uid = int(target)
            try:
                return await self.client.get_entity(uid)
            except Exception:
                async for d in self.client.iter_dialogs():
                    if d.id == uid:
                        return d.entity
                raise
        return await self.client.get_entity(target.lstrip("@") if not target.startswith("@") else target)

    async def export_dialog(self, target, since=None, until=None, progress=None, image_budget=30 * 1024 * 1024):
        from io import BytesIO
        from PIL import Image
        async with self.lock:
            entity = await self.resolve(target)
            me = await self.client.get_me()
            messages, spent, count = [], 0, 0
            kwargs = {"reverse": True}
            if since:
                kwargs["offset_date"] = since
            async for m in self.client.iter_messages(entity, **kwargs):
                if until and m.date > until:
                    break
                count += 1
                media = media_label(m)
                thumb = None
                if m.photo and spent < image_budget:
                    try:
                        raw = await self.client.download_media(m, file=bytes)
                        img = Image.open(BytesIO(raw)).convert("RGB")
                        img.thumbnail((480, 480))
                        buf = BytesIO()
                        img.save(buf, "JPEG", quality=62)
                        thumb = buf.getvalue()
                        spent += len(thumb)
                    except Exception as e:
                        log.warning("выгрузка: фото %s не взял: %s", m.id, e)
                sender = getattr(m.sender, "first_name", None) or getattr(m.sender, "title", None) or "Собеседник"
                messages.append({"id": m.id, "date": m.date, "out": bool(m.out), "sender": sender,
                                 "text": m.message or "", "media": media, "thumb": thumb,
                                 "reply_to": m.reply_to.reply_to_msg_id if m.reply_to else None})
                if progress and count % 500 == 0:
                    await progress(count)
            name = " ".join(x for x in (getattr(entity, "first_name", None), getattr(entity, "last_name", None)) if x) \
                or getattr(entity, "title", None) or str(target)
            if getattr(entity, "username", None):
                name += f" (@{entity.username})"
            owner = " ".join(x for x in (me.first_name, me.last_name) if x) or "Я"
            return name, owner, messages

    async def download_post(self, private, internal, username, msg_id):
        peer = int(f"-100{internal}") if private else username
        async with self.lock:
            entity = await self.client.get_entity(peer)
            msg = await self.client.get_messages(entity, ids=int(msg_id))
            if not msg:
                return None, [], []
            group = [msg]
            if msg.grouped_id:
                near = await self.client.get_messages(entity, ids=list(range(int(msg_id) - 10, int(msg_id) + 11)))
                group = [m for m in near if m and m.grouped_id == msg.grouped_id]
            text = next((m.message for m in group if m.message), "")
            folder = self.data_dir / "tmp" / f"post_{os.getpid()}_{msg_id}"
            folder.mkdir(parents=True, exist_ok=True)
            files, too_big = [], []
            for m in group:
                if not m.media or not m.file:
                    continue
                if (m.file.size or 0) > MAX_SEND:
                    too_big.append(m.file.name or m.file.mime_type or "файл")
                    continue
                path = await self.client.download_media(m, file=str(folder))
                if path:
                    files.append(path)
            return text, files, too_big


def cleanup(files):
    for f in files:
        try:
            Path(f).unlink()
        except OSError:
            pass
    if files:
        shutil.rmtree(Path(files[0]).parent, ignore_errors=True)


def is_media(path):
    return Path(path).suffix.lower() in MEDIA_EXT


def media_label(m):
    if m.photo:
        return "фото"
    if getattr(m, "video_note", None):
        return "кружок"
    if getattr(m, "voice", None):
        return "голосовое"
    if getattr(m, "video", None):
        return "видео"
    if getattr(m, "sticker", None):
        return "стикер"
    if getattr(m, "gif", None):
        return "гифка"
    if getattr(m, "audio", None):
        return "аудио"
    if m.document:
        return "файл"
    if m.geo:
        return "геолокация"
    if m.contact:
        return "контакт"
    if m.media:
        return "медиа"
    return None
