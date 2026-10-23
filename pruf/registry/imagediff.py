"""Дифф двух копий одного пруфа: какие токены (суммы, даты, имена) отличаются при совпадении макета."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pruf.normalize.ocr import OcrToken

MAX_CENTER_DISTANCE = 0.04
_DIGIT_RE = re.compile(r"\d")
_DATE_RE = re.compile(r"\d{1,2}[./:]\d{2}")


@dataclass(frozen=True)
class TokenChange:
    kind: str  # amount | date | text | added | removed
    before: str
    after: str
    box_before: tuple[float, float, float, float] | None
    box_after: tuple[float, float, float, float] | None


def _norm(text: str) -> str:
    return re.sub(r"[\s,]", "", text).lower()


def _classify(before: str, after: str) -> str:
    """amount/date только если цифры есть в обеих версиях, а нецифровая часть совпадает;
    иначе это скорее шум OCR, и такое отличие помечается как text."""
    if not (_DIGIT_RE.search(before) and _DIGIT_RE.search(after)):
        return "text"
    if _DIGIT_RE.sub("", _norm(before)) != _DIGIT_RE.sub("", _norm(after)):
        return "text"
    if _DATE_RE.search(before) and _DATE_RE.search(after):
        return "date"
    return "amount"


def _offset(a: list[OcrToken], b: list[OcrToken]) -> tuple[float, float]:
    """Сдвиг макета между копиями (обрезка) по медиане сдвигов одинаковых токенов."""
    by_text = {}
    for tb in b:
        by_text.setdefault(_norm(tb.text), tb)
    dx, dy = [], []
    for ta in a:
        tb = by_text.get(_norm(ta.text))
        if tb is not None and len(_norm(ta.text)) >= 3:
            dx.append(tb.center[0] - ta.center[0])
            dy.append(tb.center[1] - ta.center[1])
    if not dx:
        return 0.0, 0.0
    return sorted(dx)[len(dx) // 2], sorted(dy)[len(dy) // 2]


def diff_tokens(a: list[OcrToken], b: list[OcrToken]) -> list[TokenChange]:
    """Сопоставить токены по положению центра (с поправкой на обрезку) и вернуть отличия."""
    changes: list[TokenChange] = []
    used: set[int] = set()
    off_x, off_y = _offset(a, b)
    for ta in a:
        best_j, best_d = -1, MAX_CENTER_DISTANCE
        for j, tb in enumerate(b):
            if j in used:
                continue
            d = max(abs(ta.center[0] + off_x - tb.center[0]), abs(ta.center[1] + off_y - tb.center[1]))
            if d < best_d:
                best_j, best_d = j, d
        if best_j < 0:
            changes.append(TokenChange("removed", ta.text, "", ta.box, None))
            continue
        used.add(best_j)
        tb = b[best_j]
        if _norm(ta.text) != _norm(tb.text):
            changes.append(TokenChange(_classify(ta.text, tb.text), ta.text, tb.text, ta.box, tb.box))
    for j, tb in enumerate(b):
        if j not in used:
            changes.append(TokenChange("added", "", tb.text, None, tb.box))
    return changes


def summarize_changes(changes: list[TokenChange]) -> str:
    edits = [c for c in changes if c.kind in ("amount", "date", "text")]
    if not edits:
        return "Копии совпадают по распознанному тексту"
    parts = [f"{c.before} → {c.after}" for c in edits[:4]]
    return "Отличаются: " + "; ".join(parts)
