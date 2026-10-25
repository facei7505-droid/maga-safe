"""Голосовые сообщения → текст. Whisper подключается, если установлен faster-whisper и доступна модель.

Без модели голосовое всё равно попадает в реестр по SHA-256 (точные пересылки), а текст
можно передать готовой расшифровкой (поле transcript в API).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time

log = logging.getLogger(__name__)
_model = None
_load_failed_at: float | None = None
_lock = threading.Lock()
WHISPER_MODEL = os.environ.get("PRUF_WHISPER_MODEL", "small")
SAMPLE_RATE = 16_000
# Длительность в Telegram сообщает отправитель, ей нельзя верить: режем уже декодированный звук
MAX_AUDIO_SECONDS = int(os.environ.get("PRUF_MAX_AUDIO_SECONDS", "120"))
LOAD_RETRY_SECONDS = 600  # после неудачной загрузки модели не пытаемся снова каждое сообщение


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe(audio: bytes, suffix: str = ".ogg") -> str | None:
    if not whisper_available():
        return None
    model = _load_model()
    if model is None:
        return None
    from faster_whisper import decode_audio

    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(audio)
            tmp.flush()
            samples = decode_audio(tmp.name, sampling_rate=SAMPLE_RATE)[: MAX_AUDIO_SECONDS * SAMPLE_RATE]
        segments, _info = model.transcribe(samples, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip() or None
    except Exception:  # noqa: BLE001 — битый файл: пост анализируется без расшифровки
        log.exception("Whisper: не удалось расшифровать аудио")
        return None


def _load_model():
    global _model, _load_failed_at
    from faster_whisper import WhisperModel

    with _lock:
        if _model is None and (_load_failed_at is None or time.monotonic() - _load_failed_at > LOAD_RETRY_SECONDS):
            try:
                _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            except (OSError, RuntimeError, ValueError) as exc:
                log.warning("Whisper недоступен: %s", exc)
                _load_failed_at = time.monotonic()
        return _model
