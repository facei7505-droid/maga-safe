"""Аутентификация по токенам, лимит запросов, проверка загружаемых файлов."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from pruf.config import Settings

WINDOW_SECONDS = 60.0
IMAGE_MAGIC = {"jpg": (b"\xff\xd8\xff",), "png": (b"\x89PNG\r\n\x1a\n",)}
AUDIO_EXT = ("ogg", "mp3", "m4a", "wav")


MAX_BUCKETS = 10_000


class RateLimiter:
    """Скользящее окно в минуту. Ключ: хэш валидного токена или IP клиента для неудачных попыток."""

    def __init__(self, per_minute: int):
        self._limit = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_BUCKETS:
                self._evict(now)
            hits = self._hits[key]
            while hits and now - hits[0] > WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self._limit:
                raise HTTPException(status_code=429, detail="Слишком много запросов, повторите позже")
            hits.append(now)

    def _evict(self, now: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or now - v[-1] > WINDOW_SECONDS]
        for k in stale:
            del self._hits[k]


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()


def _named_tokens(entries: tuple[str, ...], default_name: str) -> list[tuple[str, str]]:
    """Токены в формате «имя:токен» (имя попадает в аудит вместо куска токена) или просто «токен»."""
    out = []
    for i, entry in enumerate(entries):
        name, sep, token = entry.partition(":")
        out.append((name, token) if sep and token else (f"{default_name}{i + 1}", entry))
    return out


def _who(token: str, entries: list[tuple[str, str]]) -> str | None:
    found = None
    for name, expected in entries:
        if expected and hmac.compare_digest(token.encode(), expected.encode()):
            found = name
    return found


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _authorize(request: Request, limiter: RateLimiter, entries: list[tuple[str, str]], role: str) -> str:
    token = _token_from(request)
    who = _who(token, entries) if token else None
    if who is None:
        limiter.check(f"fail:{_client(request)}")  # перебор токенов ограничен по IP
        raise HTTPException(status_code=401, detail=f"Требуется токен ({role})")
    limiter.check(f"{role}:{hashlib.sha256(token.encode()).hexdigest()[:16]}")
    return who


def require_analyst(request: Request, settings: Settings, limiter: RateLimiter) -> str:
    if settings.dev_mode and not settings.analyst_token:
        limiter.check(f"dev:{_client(request)}")
        return "dev"
    if not settings.analyst_token:
        raise HTTPException(status_code=503, detail="Сервер не настроен: задайте PRUF_ANALYST_TOKEN")
    return "analyst:" + _authorize(request, limiter, _named_tokens(settings.analyst_token.split(","), "analyst"), "analyst")


def require_bank(request: Request, settings: Settings, limiter: RateLimiter) -> str:
    if settings.dev_mode and not settings.bank_tokens:
        limiter.check(f"dev:{_client(request)}")
        return "bank:dev"
    if not settings.bank_tokens:
        raise HTTPException(status_code=503, detail="Сервер не настроен: задайте PRUF_BANK_TOKENS")
    return "bank:" + _authorize(request, limiter, _named_tokens(settings.bank_tokens, "bank"), "bank")


def require_extension(request: Request, settings: Settings, limiter: RateLimiter) -> str:
    """Токен расширения ПРУФ Sentinel: только проверка реквизитов и чёрный список доменов."""
    if settings.dev_mode and not settings.extension_tokens:
        limiter.check(f"dev:{_client(request)}")
        return "extension:dev"
    if not settings.extension_tokens:
        raise HTTPException(status_code=503, detail="Сервер не настроен: задайте PRUF_EXTENSION_TOKENS")
    return "extension:" + _authorize(request, limiter, _named_tokens(settings.extension_tokens, "ext"), "extension")


def sniff_upload(data: bytes, filename: str | None, content_type: str | None) -> tuple[str, str]:
    """Определить тип файла по сигнатуре, а не по имени. Возвращает (kind, ext)."""
    for ext, magics in IMAGE_MAGIC.items():
        if any(data.startswith(m) for m in magics):
            return "image", ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "webp"
    if data[:4] == b"OggS":
        return "audio", "ogg"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", "mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio", "wav"
    if data[4:8] == b"ftyp" and data[8:12] in (b"M4A ", b"M4B "):  # только аудио-контейнер, не любое видео MP4
        return "audio", "m4a"
    raise HTTPException(status_code=415, detail="Поддерживаются JPEG, PNG, WEBP и аудио OGG/MP3/M4A/WAV")
