"""Извлечение реквизитов: телефоны +7, карты, IBAN KZ, платёжные ссылки Kaspi, промокоды.

Номера карт не хранятся целиком: ключ сопоставления это HMAC от полного номера,
а для показа остаётся маска 6+4.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass

# «+7», «8» или голая «7» перед кодом оператора 7xx: «7 747 318 52 64», «77473185264»
_PHONE_RE = re.compile(r"(?<![\d+])(?:\+7|8|7)[\s\-()]*7\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)")
_IBAN_RE = re.compile(r"\bKZ\d{2}(?:\s?[A-Z0-9]{4}){4}\b", re.IGNORECASE)
_KASPI_LINK_RE = re.compile(r"\b(?:https?://)?(?:pay\.)?kaspi\.(?:kz|me)/(?:pay/)?[\w\-/]+", re.IGNORECASE)
_PROMO_RE = re.compile(r"(?:промокод\w*|promo\s*code|promokod\w*|промо)\s*[:\-]?\s*([A-Za-z0-9_]{4,20})", re.IGNORECASE)


@dataclass(frozen=True)
class Requisite:
    kind: str  # phone | card | iban | kaspi_link | promo
    key: str  # ключ сопоставления (для карты HMAC)
    display: str  # что показывать аналитику
    raw_span: tuple[int, int]


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("8"):
        digits = "7" + digits[1:]
    return "+" + digits


def card_key(digits: str, hmac_key: bytes) -> str:
    return "card:" + hmac.new(hmac_key, digits.encode(), hashlib.sha256).hexdigest()[:32]


def clean_digits(text: str) -> str:
    """Убрать невидимые символы и перевести любые цифры Unicode (полноширинные, арабские) в ASCII.

    Иначе «4400\u200b4301…» проходит мимо маскирования карты, а «+７ ７４７…» не распознаётся как телефон.
    """
    if not text.isascii():
        text = "".join("" if unicodedata.category(ch) == "Cf" else
                       str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() and unicodedata.digit(ch, None) is not None
                       else ch for ch in text)
    return text


def redact_cards(text: str | None) -> str | None:
    """Заменить номера карт (с верной контрольной суммой) маской 6+4 до записи в базу, экспорт или LLM.

    Текст сначала проходит clean_digits: именно этот вид текста хранится и цитируется.
    """
    if not text:
        return text
    text = clean_digits(text)

    def mask(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group())
        return f"{digits[:6]}******{digits[-4:]}" if _luhn_ok(digits) else m.group()

    return _CARD_RE.sub(mask, text)


def extract_requisites(text: str, hmac_key: bytes) -> list[Requisite]:
    """Реквизиты из текста; позиции raw_span указывают в clean_digits(text)."""
    text = clean_digits(text)
    found: list[Requisite] = []
    seen: set[str] = set()

    def add(req: Requisite) -> None:
        if req.key not in seen:
            seen.add(req.key)
            found.append(req)

    for m in _PHONE_RE.finditer(text):
        phone = normalize_phone(m.group())
        add(Requisite("phone", f"phone:{phone}", phone, m.span()))
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if _luhn_ok(digits):
            add(Requisite("card", card_key(digits, hmac_key), f"{digits[:6]}******{digits[-4:]}", m.span()))
    for m in _IBAN_RE.finditer(text):
        iban = re.sub(r"\s", "", m.group()).upper()
        add(Requisite("iban", f"iban:{iban}", iban, m.span()))
    for m in _KASPI_LINK_RE.finditer(text):
        link = re.sub(r"^https?://", "", m.group().lower()).rstrip("/")
        add(Requisite("kaspi_link", f"kaspi:{link}", link, m.span()))
    for m in _PROMO_RE.finditer(text):
        code = m.group(1).upper()
        add(Requisite("promo", f"promo:{code}", code, m.span(1)))
    return found
