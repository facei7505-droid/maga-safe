"""Аутентификация по токенам, лимит запросов, проверка загружаемых файлов."""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from pruf.config import Settings

WINDOW_SECONDS = 60.0
IMAGE_MAGIC = {"jpg": (b"\xff\xd8\xff",), "png": (b"\x89PNG\r\n\x1a\n",)}
AUDIO_EXT = ("ogg", "mp3", "m4a", "wav")


class RateLimiter:
    def __init__(self, per_minute: int):
        self._limit = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= self._limit:
                raise HTTPException(status_code=429, detail="Слишком много запросов, повторите позже")
            hits.append(now)


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key", "").strip()


def _matches(token: str, allowed: tuple[str, ...]) -> bool:
    return any(hmac.compare_digest(token.encode(), a.encode()) for a in allowed if a)


def require_analyst(request: Request, settings: Settings, limiter: RateLimiter) -> str:
    token = _token_from(request)
    client = request.client.host if request.client else "unknown"
    limiter.check(f"analyst:{token[:8] or client}")
    if settings.dev_mode and not settings.analyst_token:
        return "dev"
    if not settings.analyst_token:
        raise HTTPException(status_code=503, detail="Сервер не настроен: задайте PRUF_ANALYST_TOKEN")
    if not _matches(token, (settings.analyst_token,)):
        raise HTTPException(status_code=401, detail="Требуется токен аналитика")
    return "analyst"


def require_bank(request: Request, settings: Settings, limiter: RateLimiter) -> str:
    token = _token_from(request)
    client = request.client.host if request.client else "unknown"
    limiter.check(f"bank:{token[:8] or client}")
    if settings.dev_mode and not settings.bank_tokens:
        return "bank-dev"
    if not _matches(token, settings.bank_tokens):
        raise HTTPException(status_code=401, detail="Требуется токен банка")
    return f"bank:{token[:4]}…"


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
    if data[4:8] == b"ftyp":
        return "audio", "m4a"
    raise HTTPException(status_code=415, detail="Поддерживаются JPEG, PNG, WEBP и аудио OGG/MP3/M4A/WAV")
