"""QR-коды на скриншотах и афишах: Kaspi Pay, ссылка на казино, Telegram-канал.

Мошенники кладут ссылку или реквизит в QR, а текст поста оставляют чистым: OCR такой код не прочитает.
Содержимое QR идёт в детектор отдельным источником «qr», поэтому реквизиты и ссылки из него попадают
в реестр, граф и чёрный список так же, как из текста. Декодер — OpenCV (уже стоит как зависимость OCR),
работает офлайн на CPU, около 24 МБ памяти; PRUF_QR=0 выключает.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)
MAX_CODES = 5  # на афише бывает несколько кодов; больше — уже коллаж, остальные не читаем
MAX_PAYLOAD = 1000  # QR вмещает до ~3 КБ; длинное содержимое обрезаем, детектору хватит начала
MAX_SIDE = 2000  # крупные скриншоты уменьшаем: QR от этого не теряется, а поиск идёт в разы быстрее
MIN_SIDE = 1000  # мелкие превью увеличиваем: детектор OpenCV плохо находит модуль QR меньше 3–4 пикселей
_detector = None
_lock = threading.Lock()


def _get_detector():
    global _detector
    with _lock:
        if _detector is None:
            import cv2

            _detector = cv2.QRCodeDetector()
        return _detector


def qr_available() -> bool:
    try:
        _get_detector()
    except (ImportError, OSError):
        return False
    return True


def _prepared(img: Image.Image) -> np.ndarray:
    gray = img.convert("L")
    side = max(gray.size)
    if side > MAX_SIDE or side < MIN_SIDE:
        scale = (MAX_SIDE if side > MAX_SIDE else MIN_SIDE) / side
        gray = gray.resize((max(1, round(gray.width * scale)), max(1, round(gray.height * scale))), Image.LANCZOS)
    return np.asarray(gray)


def decode_qr(img: Image.Image) -> list[str]:
    """Содержимое QR-кодов на изображении, без повторов. Ошибка декодера не ломает анализ: кодов просто нет."""
    try:
        detector = _get_detector()
    except (ImportError, OSError):
        return []
    arr = _prepared(img)
    try:
        # один детектор на процесс: OpenCV-объект не потокобезопасен
        with _lock:
            ok, payloads, _, _ = detector.detectAndDecodeMulti(arr)
            found = list(payloads) if ok else []
            if not any(found):
                single, _, _ = detector.detectAndDecode(arr)
                found = [single]
    except Exception:  # noqa: BLE001 — cv2.error и сбои на битых картинках
        log.warning("QR не прочитан", exc_info=True)
        return []
    out: list[str] = []
    for text in found:
        text = (text or "").strip()[:MAX_PAYLOAD]
        if text and text not in out:
            out.append(text)
    return out[:MAX_CODES]
