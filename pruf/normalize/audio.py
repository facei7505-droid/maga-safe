"""Голосовые сообщения → текст. Whisper подключается, если установлен faster-whisper и доступна модель.

Без модели голосовое всё равно попадает в реестр по SHA-256 (точные пересылки), а текст
можно передать готовой расшифровкой (поле transcript в API).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading

log = logging.getLogger(__name__)
_model = None
_lock = threading.Lock()
WHISPER_MODEL = os.environ.get("PRUF_WHISPER_MODEL", "small")


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe(audio: bytes, suffix: str = ".ogg") -> str | None:
    if not whisper_available():
        return None
    global _model
    from faster_whisper import WhisperModel

    with _lock:
        if _model is None:
            try:
                _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            except (OSError, RuntimeError, ValueError) as exc:
                log.warning("Whisper недоступен: %s", exc)
                return None
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio)
        tmp.flush()
        segments, _info = _model.transcribe(tmp.name, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip() or None
