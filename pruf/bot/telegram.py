"""Telegram-бот ПРУФ: человек пересылает подозрительный пост, скрин или голосовое и получает
найденные признаки с цитатами. Бот ничего не сохраняет в реестр, только читает его.

Два режима:
  * long polling: python -m pruf.bot.telegram (удобно для демо и разработки);
  * webhook: POST /api/v1/telegram/webhook с заголовком X-Telegram-Bot-Api-Secret-Token.
Логика (BotLogic) не зависит от сети: клиент Telegram подставляется, поэтому всё тестируется офлайн.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from pruf.api.security import RateLimiter, sniff_upload
from pruf.models import LEVEL_LABELS
from pruf.normalize.audio import transcribe, whisper_available
from pruf.pipeline import Pruf

log = logging.getLogger(__name__)
API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4000  # лимит Telegram 4096, оставляем запас
MAX_EVIDENCE_LINES = 6
CHAT_LIMIT_PER_MINUTE = 20
GLOBAL_LIMIT_PER_MINUTE = 120  # общий потолок: много чатов не забьют OCR и исходящую квоту Telegram
MAX_VOICE_SECONDS = 120
POLL_TIMEOUT = 30
LEVEL_ICON = {"high": "🔴", "medium": "🟠", "low": "🟢"}
TRACK_NAME = {"lottery": "платный розыгрыш", "casino": "скрытая реклама казино", "pyramid": "финансовая пирамида"}
HELP = (
    "Я ПРУФ. Перешлите подозрительный пост, скриншот «выплаты» или голосовое, и я покажу, "
    "какие признаки схем в нём есть: платные розыгрыши, скрытая реклама казино, пирамиды.\n\n"
    "Я ищу признаки, а не выношу вердикт. Если сомневаетесь, не переводите деньги и проверьте "
    "организатора по официальным источникам."
)


class TelegramApi(Protocol):
    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None: ...
    def file_size_and_path(self, file_id: str) -> tuple[int, str]: ...
    def download(self, file_path: str, max_bytes: int) -> bytes: ...


@dataclass
class Reply:
    chat_id: int
    text: str
    reply_to: int | None = None


class BotLogic:
    def __init__(self, pruf: Pruf, api: TelegramApi, max_bytes: int, limiter: RateLimiter | None = None,
                 global_limiter: RateLimiter | None = None):
        self._pruf = pruf
        self._api = api
        self._max_bytes = max_bytes
        self._limiter = limiter or RateLimiter(CHAT_LIMIT_PER_MINUTE)
        self._global = global_limiter or RateLimiter(GLOBAL_LIMIT_PER_MINUTE)

    def handle(self, update: dict[str, Any]) -> Reply | None:
        # Только личные сообщения: в группах и каналах бот не отвечает на всё подряд.
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if not isinstance(chat.get("id"), int) or chat.get("type") != "private":
            return None
        try:
            reply = self._answer(chat["id"], msg)
        except Exception:
            log.exception("ошибка проверки сообщения")
            reply = Reply(chat["id"], "Не удалось проверить сообщение, попробуйте позже.", msg.get("message_id"))
        if reply:
            self._api.send_message(reply.chat_id, reply.text[:MAX_MESSAGE], reply.reply_to)
        return reply

    def _answer(self, chat: int, msg: dict[str, Any]) -> Reply | None:
        text = msg.get("text") or msg.get("caption") or ""
        mid = msg.get("message_id")
        try:
            self._limiter.check(f"tg:{chat}")
            self._global.check("tg:all")
        except HTTPException:
            return Reply(chat, "Слишком много сообщений, попробуйте через минуту.", mid)
        if text.strip().split("@")[0] in ("/start", "/help"):
            return Reply(chat, HELP)
        try:
            images, transcript, note = self._media(msg)
        except _MediaError as exc:
            return Reply(chat, str(exc), mid)
        if not text.strip() and not images and not transcript:
            return Reply(chat, note or "Пришлите текст поста, скриншот или голосовое.", mid)
        try:
            result = self._pruf.check(text, images=tuple(images), transcript=transcript, public=True)
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
            return Reply(chat, "Не получилось прочитать изображение. Пришлите JPEG или PNG до 8 МБ.", mid)
        return Reply(chat, format_result(result, note), mid)

    def _media(self, msg: dict[str, Any]) -> tuple[list[bytes], str | None, str | None]:
        images: list[bytes] = []
        transcript = None
        note = None
        photo = _best_photo(msg.get("photo") or [], self._max_bytes)
        doc = msg.get("document") or {}
        if photo:
            images.append(self._fetch(photo["file_id"], "image")[0])
        elif str(doc.get("mime_type", "")).startswith("image/"):
            images.append(self._fetch(doc["file_id"], "image")[0])
        voice = msg.get("voice") or msg.get("audio")
        if voice:
            if not whisper_available():
                note = "Расшифровка голосовых сейчас не включена на сервере, проверил только текст и изображения."
            elif int(voice.get("duration") or 0) > MAX_VOICE_SECONDS:
                raise _MediaError(f"Голосовое длиннее {MAX_VOICE_SECONDS // 60} минут, пришлите фрагмент или текст.")
            else:
                data, ext = self._fetch(voice["file_id"], "audio")
                transcript = transcribe(data, "." + ext)
        return images, transcript, note

    def _fetch(self, file_id: str, kind: str) -> tuple[bytes, str]:
        size, path = self._api.file_size_and_path(file_id)
        if size > self._max_bytes:
            raise _MediaError("Файл слишком большой, пришлите до 8 МБ.")
        data = self._api.download(path, self._max_bytes)
        try:
            got, ext = sniff_upload(data, None, None)
        except HTTPException as exc:
            raise _MediaError("Поддерживаются JPEG, PNG, WEBP и голосовые сообщения.") from exc
        if got != kind:
            raise _MediaError("Формат файла не совпадает с типом сообщения.")
        return data, ext


class _MediaError(Exception):
    pass


def _best_photo(sizes: list[dict[str, Any]], max_bytes: int) -> dict[str, Any] | None:
    """Самый крупный вариант фото, который укладывается в лимит (у мелких OCR хуже)."""
    fitting = [s for s in sizes if int(s.get("file_size") or 0) <= max_bytes]
    return max(fitting, key=lambda s: int(s.get("width", 0)) * int(s.get("height", 0)), default=None)


def format_result(result: dict[str, Any], note: str | None = None) -> str:
    """Ответ простым текстом (без parse_mode): цитаты из поста не могут сломать разметку.
    Сигналы реестра приходят уже обезличенными (Pruf.check(public=True)): без каналов, сумм и счётчиков."""
    a = result["analysis"]
    level = a["level"]
    head = f"{LEVEL_ICON.get(level, '')} Риск: {LEVEL_LABELS.get(level, level)} ({round(a['score'])}/100)"
    if a.get("track"):
        head += f"\nПохоже на: {TRACK_NAME.get(a['track'], a['track'])}"
    lines = [head]
    positive = [e for e in a.get("evidence", []) if e.get("weight", 0) > 0]
    if positive:
        lines.append("\nНайденные признаки:")
        for e in positive[:MAX_EVIDENCE_LINES]:
            quote = f"\n   «{e['quote'][:160]}»" if e.get("quote") else ""
            lines.append(f"• {e['label']}{quote}")
    stops = [e for e in a.get("evidence", []) if e.get("stop")]
    if stops:
        lines.append("\nПризнаки легальности: " + "; ".join(e["label"] for e in stops[:3]))
    for d in a.get("degraded", []):
        lines.append(f"\n⚠️ {d['reason']}")
    if note:
        lines.append(f"\n{note}")
    if level != "low":
        lines.append("\nНе переводите деньги незнакомым организаторам. Это признаки, а не вердикт.")
    elif positive:
        lines.append("\nСочетания признаков для среднего риска нет, но есть сигналы выше: будьте осторожны.")
    else:
        lines.append("\nЯвных признаков схем не нашёл. Это не гарантия: проверяйте организатора.")
    return "\n".join(lines)


class HttpTelegramApi:
    """Клиент Bot API. Токен не попадает в логи: ошибки логируются без URL."""

    def __init__(self, token: str, client: httpx.Client | None = None):
        self._token = token
        self._client = client or httpx.Client(timeout=POLL_TIMEOUT + 10)

    def _call(self, method: str, **params: Any) -> Any:
        try:
            res = self._client.post(f"{API_BASE}/bot{self._token}/{method}", json=params)
            body = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Telegram {method}: {type(exc).__name__}") from None
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description', 'ошибка')}")
        return body["result"]

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        self._call("sendMessage", **params)

    def file_size_and_path(self, file_id: str) -> tuple[int, str]:
        info = self._call("getFile", file_id=file_id)
        return int(info.get("file_size") or 0), str(info["file_path"])

    def download(self, file_path: str, max_bytes: int) -> bytes:
        buf = bytearray()
        try:
            with self._client.stream("GET", f"{API_BASE}/file/bot{self._token}/{file_path}") as res:
                res.raise_for_status()
                for chunk in res.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise _MediaError("Файл слишком большой, пришлите до 8 МБ.")
        except httpx.HTTPError:
            raise RuntimeError("Telegram download failed") from None
        return bytes(buf)

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", **params)


def run_polling(pruf: Pruf, token: str) -> None:
    api = HttpTelegramApi(token)
    logic = BotLogic(pruf, api, pruf.settings.max_upload_bytes)
    offset = None
    log.info("бот запущен (long polling)")
    while True:
        try:
            updates = api.get_updates(offset)
        except RuntimeError as exc:
            log.warning("%s, повтор через 5 с", exc)
            time.sleep(5)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                logic.handle(upd)
            except Exception:
                log.exception("ошибка обработки update %s", upd.get("update_id"))


def main() -> None:
    from pruf.config import Settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx пишет URL с токеном на INFO
    settings = Settings()
    if not settings.telegram_token:
        raise SystemExit("Задайте TELEGRAM_BOT_TOKEN")
    run_polling(Pruf(settings), settings.telegram_token)


if __name__ == "__main__":
    main()
