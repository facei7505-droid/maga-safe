"""Признаки правки изображения: Error Level Analysis (ELA) по зонам распознанных токенов.

Идея: вставленный фрагмент (перерисованная сумма) пережимался меньше раз, чем остальной
скриншот, и даёт другой уровень ошибки после повторного JPEG-сжатия. Это признак, а не
доказательство: ELA чувствителен к резким краям, поэтому сравниваем токены между собой,
а не с абсолютным порогом.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageChops

from pruf.normalize.ocr import OcrToken

ELA_QUALITY = 90
ANOMALY_RATIO = 1.8
MIN_TOKENS = 3


@dataclass(frozen=True)
class TokenAnomaly:
    text: str
    box: tuple[float, float, float, float]
    ratio: float


def ela_map(img: Image.Image) -> np.ndarray:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=ELA_QUALITY)
    resaved = Image.open(io.BytesIO(buf.getvalue()))
    diff = ImageChops.difference(img.convert("RGB"), resaved)
    return np.asarray(diff, dtype=np.float32).mean(axis=2)


def ela_heatmap_png(img: Image.Image) -> bytes:
    ela = ela_map(img)
    scale = 255.0 / max(float(np.percentile(ela, 99.5)), 1.0)
    heat = np.clip(ela * scale, 0, 255).astype(np.uint8)
    rgb = np.stack([heat, (heat * 0.4).astype(np.uint8), np.zeros_like(heat)], axis=2)
    out = io.BytesIO()
    Image.fromarray(rgb).save(out, "PNG")
    return out.getvalue()


def token_anomalies(img: Image.Image, tokens: list[OcrToken]) -> list[TokenAnomaly]:
    """Токены с цифрами, у которых уровень ошибки заметно выше медианы по другим токенам с цифрами."""
    tokens = [t for t in tokens if any(ch.isdigit() for ch in t.text)]
    if len(tokens) < MIN_TOKENS:
        return []
    ela = ela_map(img)
    h, w = ela.shape
    levels: list[float] = []
    for tok in tokens:
        x0, y0, x1, y1 = tok.box
        patch = ela[int(y0 * h):max(int(y1 * h), int(y0 * h) + 1), int(x0 * w):max(int(x1 * w), int(x0 * w) + 1)]
        levels.append(float(patch.mean()) if patch.size else 0.0)
    median = float(np.median(levels)) or 1e-6
    return [TokenAnomaly(tok.text, tok.box, round(level / median, 2))
            for tok, level in zip(tokens, levels) if level / median >= ANOMALY_RATIO]
