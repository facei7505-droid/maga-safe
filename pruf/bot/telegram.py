"""Telegram-бот ПРУФ: человек пересылает подозрительный пост, скрин или голосовое и получает
найденные признаки с цитатами. Бот ничего не сохраняет в реестр, только читает его.

Два режима:
  * long polling: python -m pruf.bot.telegram (удобно для демо и разработки);
  * webhook: POST /api/v1/telegram/webhook с заголовком X-Telegram-Bot-Api-Secret-Token.
Логика (BotLogic) не зависит от сети: клиент Telegram подставляется, поэтому всё тестируется офлайн.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from pruf.api.security import RateLimiter, sniff_upload
from pruf.bot.texts import LEVELS, TRACKS, reply_lang, say
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
FEEDBACK_PREFIX = "fp:"
FEEDBACK_TTL = 24 * 3600  # кнопка «Это не мошенничество» живёт сутки
FEEDBACK_MAX_PENDING = 5000  # ответы, по которым ещё можно нажать кнопку; старые вытесняются
RISKY = ("medium", "high")
LEVEL_ICON = {"high": "🔴", "medium": "🟠", "low": "🟢"}
HELP = say("ru", "help")


class TelegramApi(Protocol):
    def send_message(self, chat_id: int, text: str, reply_to: int | None = None,
                     buttons: list[tuple[str, str]] | None = None) -> None: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...
    def clear_buttons(self, chat_id: int, message_id: int) -> None: ...
    def file_size_and_path(self, file_id: str) -> tuple[int, str]: ...
    def download(self, file_path: str, max_bytes: int) -> bytes: ...


@dataclass
class Reply:
    chat_id: int
    text: str
    reply_to: int | None = None
    buttons: list[tuple[str, str]] | None = None  # (надпись, callback_data)


@dataclass(frozen=True)
class _Pending:
    """Что запомнить до нажатия «Это не мошенничество»: признаки без цитат, уровень и балл. Текста нет."""
    created: float
    level: str
    score: float
    track: str | None
    lang: str
    features: tuple[tuple[str, str], ...]


class BotLogic:
    def __init__(self, pruf: Pruf, api: TelegramApi, max_bytes: int, limiter: RateLimiter | None = None,
                 global_limiter: RateLimiter | None = None):
        self._pruf = pruf
        self._api = api
        self._max_bytes = max_bytes
        self._limiter = limiter or RateLimiter(CHAT_LIMIT_PER_MINUTE)
        self._global = global_limiter or RateLimiter(GLOBAL_LIMIT_PER_MINUTE)
        self._pending: OrderedDict[str, _Pending] = OrderedDict()
        self._pending_lock = threading.Lock()

    def handle(self, update: dict[str, Any]) -> Reply | None:
        if "callback_query" in update:
            self._on_button(update["callback_query"] or {})
            return None
        # Только личные сообщения: в группах и каналах бот не отвечает на всё подряд.
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        if not isinstance(chat.get("id"), int) or chat.get("type") != "private":
            return None
        lang = reply_lang(msg.get("text") or msg.get("caption") or "", (msg.get("from") or {}).get("language_code"))
        try:
            reply = self._answer(chat["id"], msg, lang)
        except Exception:
            log.exception("ошибка проверки сообщения")
            reply = Reply(chat["id"], say(lang, "check_failed"), msg.get("message_id"))
        if reply:
            self._api.send_message(reply.chat_id, reply.text[:MAX_MESSAGE], reply.reply_to, reply.buttons)
        return reply

    def _answer(self, chat: int, msg: dict[str, Any], lang: str = "ru") -> Reply | None:
        text = msg.get("text") or msg.get("caption") or ""
        mid = msg.get("message_id")
        try:
            self._limiter.check(f"tg:{chat}")
            self._global.check("tg:all")
        except HTTPException:
            return Reply(chat, say(lang, "too_many"), mid)
        if text.strip().split("@")[0] in ("/start", "/help"):
            return Reply(chat, say(lang, "help"))
        try:
            images, transcript, note_key = self._media(msg)
        except _MediaError as exc:
            return Reply(chat, say(lang, exc.key, **exc.values), mid)
        note = say(lang, note_key) if note_key else None
        if not text.strip() and not images and not transcript:
            return Reply(chat, note or say(lang, "send_something"), mid)
        try:
            result = self._pruf.check(text, images=tuple(images), transcript=transcript, public=True)
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
            return Reply(chat, say(lang, "bad_image"), mid)
        return Reply(chat, format_result(result, note, lang), mid, self._feedback_button(result["analysis"], lang))

    # ---------- «Это не мошенничество» ----------
    def _feedback_button(self, analysis: dict[str, Any], lang: str) -> list[tuple[str, str]] | None:
        """Кнопка под ответом со средним и высоким риском. Нажатие станет разметкой для ревью словаря
        (docs/rollout.md, «Как система учится»), поэтому запоминаем только признаки, а не текст."""
        if analysis["level"] not in RISKY:
            return None
        # один признак может сработать на нескольких цитатах: в разметку идёт один раз
        features = tuple({e["feature_id"]: e["label"] for e in analysis.get("evidence", []) if e.get("weight", 0) > 0}.items())
        if not features:
            return None
        token = secrets.token_urlsafe(9)
        now = time.monotonic()
        with self._pending_lock:
            while self._pending:
                oldest = next(iter(self._pending.values()))
                if len(self._pending) < FEEDBACK_MAX_PENDING and now - oldest.created < FEEDBACK_TTL:
                    break
                self._pending.popitem(last=False)
            self._pending[token] = _Pending(now, analysis["level"], float(analysis["score"]), analysis.get("track"),
                                            lang, features)
        try:
            self._pruf.db.count_bot_features(features)
        except Exception:
            log.exception("не удалось учесть показ признаков")  # счётчик не должен ломать ответ
        return [(say(lang, "not_scam_button"), FEEDBACK_PREFIX + token)]

    def _on_button(self, query: dict[str, Any]) -> None:
        msg = query.get("message") or {}
        chat = msg.get("chat") or {}
        user = (query.get("from") or {}).get("id")
        data = str(query.get("data") or "")
        if not query.get("id") or not isinstance(user, int) or chat.get("type") != "private" \
                or not data.startswith(FEEDBACK_PREFIX):
            return
        token = data[len(FEEDBACK_PREFIX):]
        with self._pending_lock:
            pending = self._pending.get(token)
            if pending and time.monotonic() - pending.created >= FEEDBACK_TTL:
                pending = None
        lang = pending.lang if pending else reply_lang("", (query.get("from") or {}).get("language_code"))
        try:
            self._limiter.check(f"tg:{user}")
        except HTTPException:
            self._api.answer_callback(query["id"], say(lang, "too_many"))
            return
        if pending is None:
            self._api.answer_callback(query["id"], say(lang, "feedback_expired"))
            return
        # Отпечаток человека меняется раз в месяц, как у жалоб из расширения: повтор не считается дважды,
        # но по базе нельзя восстановить, кто именно спорил.
        epoch = time.strftime("%Y-%m", time.gmtime())
        reporter = hmac.new(self._pruf.settings.effective_hmac_key(), f"tg|{user}|{epoch}".encode(), "sha256").hexdigest()[:24]
        accepted = self._pruf.db.add_bot_feedback(reporter=reporter, check_id=token, level=pending.level,
                                                  score=pending.score, track=pending.track, lang=pending.lang,
                                                  features=pending.features)
        with self._pending_lock:
            self._pending.pop(token, None)
        self._api.answer_callback(query["id"], say(lang, "feedback_thanks" if accepted else "feedback_dup"))
        if isinstance(msg.get("message_id"), int):
            try:
                self._api.clear_buttons(chat["id"], msg["message_id"])
            except RuntimeError as exc:
                log.warning("кнопку не убрать: %s", exc)

    def _media(self, msg: dict[str, Any]) -> tuple[list[bytes], str | None, str | None]:
        """Картинки, расшифровка голосового и ключ пояснения (pruf/bot/texts.py), если что-то не проверено."""
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
                note = "whisper_off"
            elif int(voice.get("duration") or 0) > MAX_VOICE_SECONDS:
                raise _MediaError("voice_too_long", minutes=MAX_VOICE_SECONDS // 60)
            else:
                data, ext = self._fetch(voice["file_id"], "audio")
                transcript = transcribe(data, "." + ext)
                if transcript is None:
                    note = "voice_failed"
        return images, transcript, note

    def _fetch(self, file_id: str, kind: str) -> tuple[bytes, str]:
        size, path = self._api.file_size_and_path(file_id)
        if size > self._max_bytes:
            raise _MediaError("too_big")
        data = self._api.download(path, self._max_bytes)
        try:
            got, ext = sniff_upload(data, None, None)
        except HTTPException as exc:
            raise _MediaError("unsupported") from exc
        if got != kind:
            raise _MediaError("type_mismatch")
        return data, ext


class _MediaError(Exception):
    """Файл не проверить; key — текст ответа в pruf/bot/texts.py."""

    def __init__(self, key: str, **values: object):
        super().__init__(say("ru", key, **values))
        self.key = key
        self.values = values


def _best_photo(sizes: list[dict[str, Any]], max_bytes: int) -> dict[str, Any] | None:
    """Самый крупный вариант фото, который укладывается в лимит (у мелких OCR хуже)."""
    fitting = [s for s in sizes if int(s.get("file_size") or 0) <= max_bytes]
    return max(fitting, key=lambda s: int(s.get("width", 0)) * int(s.get("height", 0)), default=None)


def format_result(result: dict[str, Any], note: str | None = None, lang: str = "ru") -> str:
    """Ответ простым текстом (без parse_mode): цитаты из поста не могут сломать разметку.
    Сигналы реестра приходят уже обезличенными (Pruf.check(public=True)): без каналов, сумм и счётчиков."""
    a = result["analysis"]
    level = a["level"]
    head = f"{LEVEL_ICON.get(level, '')} " + say(lang, "risk", level=LEVELS[lang].get(level, level), score=round(a["score"]))
    if a.get("track"):
        head += "\n" + say(lang, "looks_like", track=TRACKS[lang].get(a["track"], a["track"]))
    lines = [head]
    positive = [e for e in a.get("evidence", []) if e.get("weight", 0) > 0]
    if positive:
        lines.append("\n" + say(lang, "found") + (" " + say(lang, "labels_ru") if lang == "kk" else ""))
        for e in positive[:MAX_EVIDENCE_LINES]:
            quote = f"\n   «{e['quote'][:160]}»" if e.get("quote") else ""
            lines.append(f"• {e['label']}{quote}")
    stops = [e for e in a.get("evidence", []) if e.get("stop")]
    if stops:
        lines.append("\n" + say(lang, "legal") + "; ".join(e["label"] for e in stops[:3]))
    for d in a.get("degraded", []):
        lines.append(f"\n⚠️ {d['reason']}")
    if note:
        lines.append(f"\n{note}")
    advice = "advice_risk" if level != "low" else "advice_weak" if positive else "advice_clean"
    lines.append("\n" + say(lang, advice))
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

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None,
                     buttons: list[tuple[str, str]] | None = None) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d}] for t, d in buttons]}
        self._call("sendMessage", **params)

    def answer_callback(self, callback_id: str, text: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self._call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                   reply_markup={"inline_keyboard": []})

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
                        raise _MediaError("too_big")
        except httpx.HTTPError:
            raise RuntimeError("Telegram download failed") from None
        return bytes(buf)

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": POLL_TIMEOUT, "allowed_updates": ["message", "callback_query"]}
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
