"""Синтетические «скрины выплат» и их перепосты с правками. Без реальных логотипов и брендинга."""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
)
_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
W, H = 540, 960


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (_BOLD_CANDIDATES if bold else ()) + _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


@dataclass(frozen=True)
class Receipt:
    amount: str  # «150 000»
    sender: str
    date: str  # «23.10.2026»
    time: str  # «14:35»
    receipt_no: str
    accent: tuple[int, int, int] = (226, 38, 38)


AMOUNT_XY = (60, 300)


def render_receipt(r: Receipt) -> Image.Image:
    img = Image.new("RGB", (W, H), (245, 246, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 120], fill=r.accent)
    d.text((40, 45), "Перевод выполнен", fill="white", font=_font(34, True))
    d.rounded_rectangle([30, 160, W - 30, 760], radius=24, fill="white")
    d.text((60, 200), "Сумма перевода", fill=(120, 120, 120), font=_font(26))
    d.text(AMOUNT_XY, f"+{r.amount} T", fill=(20, 20, 20), font=_font(64, True))
    rows = [("Отправитель", r.sender), ("Дата", r.date), ("Время", r.time), ("Комиссия", "0 T"), ("Квитанция", r.receipt_no)]
    y = 420
    for label, value in rows:
        d.text((60, y), label, fill=(130, 130, 130), font=_font(24))
        d.text((300, y), value, fill=(25, 25, 25), font=_font(26))
        y += 62
    d.rounded_rectangle([60, 800, W - 60, 880], radius=40, fill=r.accent)
    d.text((170, 822), "Готово", fill="white", font=_font(32, True))
    return img


def to_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def edit_amount(jpeg: bytes, new_amount: str) -> Image.Image:
    """Поддельная копия: сумма закрашена и перерисована поверх уже сжатого JPEG."""
    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    d = ImageDraw.Draw(img)
    x, y = AMOUNT_XY
    d.rectangle([x - 4, y + 4, W - 40, y + 78], fill="white")
    d.text((x + 1, y), f"+{new_amount} T", fill=(22, 22, 22), font=_font(64, True))
    return img


def repost_variant(img: Image.Image, rng: random.Random, watermark: str | None = None) -> bytes:
    """Перепост: обрезка, масштаб, яркость, подпись канала, другое качество JPEG."""
    w, h = img.size
    dx, dy = rng.randint(0, 18), rng.randint(0, 30)
    out = img.crop((dx, dy, w - rng.randint(0, 18), h - rng.randint(0, 30)))
    scale = rng.uniform(0.75, 1.1)
    out = out.resize((int(out.width * scale), int(out.height * scale)))
    out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.93, 1.07))
    if watermark:
        ImageDraw.Draw(out).text((12, out.height - 34), watermark, fill=(160, 160, 160), font=_font(20))
    return to_jpeg(out, rng.randint(70, 92))
