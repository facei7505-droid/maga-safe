"""OCR скриншотов через RapidOCR (модели PP-OCR в ONNX, работают офлайн на CPU).

Модель PP-OCRv3 из коробки уверенно читает цифры, даты, суммы и латиницу; кириллица
читается плохо, поэтому для текста скриншота на кириллице есть опциональный Claude vision.
Для реестра ПРУФ важнее всего цифры: именно их подделывают в «скринах выплат».
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.5
_engine = None
_engine_lock = threading.Lock()


@dataclass(frozen=True)
class OcrToken:
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 в долях ширины/высоты
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


def run_ocr(img: Image.Image) -> list[OcrToken]:
    try:
        engine = _get_engine()
    except ImportError:
        log.warning("rapidocr_onnxruntime не установлен, OCR отключён")
        return []
    width, height = img.size
    result, _ = engine(np.asarray(img))
    tokens: list[OcrToken] = []
    for box, text, conf in result or []:
        conf = float(conf)
        if conf < MIN_CONFIDENCE or not str(text).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append(OcrToken(str(text).strip(), (min(xs) / width, min(ys) / height, max(xs) / width, max(ys) / height), conf))
    tokens.sort(key=lambda t: (round(t.center[1], 2), t.center[0]))
    return tokens


def tokens_to_text(tokens: list[OcrToken]) -> str:
    lines: list[list[OcrToken]] = []
    for tok in tokens:
        if lines and abs(lines[-1][0].center[1] - tok.center[1]) < 0.02:
            lines[-1].append(tok)
        else:
            lines.append([tok])
    return "\n".join(" ".join(t.text for t in sorted(line, key=lambda t: t.center[0])) for line in lines)
