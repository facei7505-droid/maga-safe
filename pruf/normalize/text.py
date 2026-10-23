"""Нормализация текста ru/kk/транслит с картой позиций для цитат.

Свёрнутый текст (`folded`) нужен для поиска признаков: нижний регистр, кириллица,
гомоглифы и leet заменены. Карта `spans` сопоставляет каждому символу свёрнутого
текста диапазон исходного, чтобы цитировать оригинал, а не нормализованную форму.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Латинские буквы, похожие на кириллические (подмена внутри кириллического слова).
_HOMOGLYPHS_LOWER = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "k": "к", "i": "і",
}
_HOMOGLYPHS_UPPER = {"B": "в", "H": "н", "M": "м", "T": "т", "K": "к", "A": "а", "E": "е", "O": "о",
                     "P": "р", "C": "с", "X": "х", "Y": "у"}
_LEET = {"0": "о", "3": "з", "4": "ч", "6": "б", "@": "а", "$": "с"}

# Транслит латиницей (русская бытовая и казахская латиница 2021 года). Длинные сочетания первыми.
_TRANSLIT_MULTI = [
    ("shch", "щ"), ("sch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("kh", "х"),
    ("ts", "ц"), ("ya", "я"), ("yu", "ю"), ("yo", "е"), ("ck", "к"), ("ph", "ф"), ("th", "т"),
]
_TRANSLIT_SINGLE = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и",
    "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р",
    "s": "с", "t": "т", "u": "у", "v": "в", "w": "у", "x": "кс", "z": "з",
    "á": "ә", "ä": "ә", "ǵ": "ғ", "ğ": "ғ", "ń": "ң", "ñ": "ң", "ó": "ө", "ö": "ө", "ú": "ұ",
    "ü": "ү", "ý": "ү", "ı": "ы", "ş": "ш", "ç": "ч", "'": "ь", "ū": "ұ",
}
# Казахский часто набирают на русской раскладке (ұ→у, қ→к, і→и): сворачиваем казахские буквы
# к русской основе, тогда «Утыс» и «Ұтыс» дают одно и то же. Шаблоны словаря сворачиваются так же.
KK_TO_RU = str.maketrans({"ұ": "у", "ү": "у", "қ": "к", "ң": "н", "ғ": "г", "ә": "а", "ө": "о", "һ": "х", "і": "и"})
# Категории, которые выбрасываются из свёрнутого текста: невидимые символы и одиночные диакритики
_DROP_CATEGORIES = ("Cf", "Mn")
_VOWELS_LAT = set("aeiouy")
# «к а з и н о», «п.и.р.а.м.и.д.а»: четыре и больше одиночных букв через один разделитель склеиваем в слово
_SPACED_RE = re.compile(r"(?<!\w)[^\W\d_](?:[ .\-*·_][^\W\d_]){3,}(?!\w)")

_TOKEN_RE = re.compile(r"\S+")
_URLISH_RE = re.compile(
    r"(://|^www\.|^@\w|^\+?\d[\d\-()]{6,}$|\.(kz|ru|com|me|io|net|org|bet|xyz|site|online|top|club|app|ly|su|cc|pro)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormText:
    original: str
    folded: str
    spans: tuple[tuple[int, int], ...]

    def quote(self, start: int, end: int, context: int = 0) -> str:
        """Исходный фрагмент для диапазона свёрнутого текста, с контекстом по словам."""
        if not self.folded or start >= end:
            return ""
        o_start = self.spans[start][0]
        o_end = self.spans[min(end, len(self.spans)) - 1][1]
        if context:
            o_start = max(0, o_start - context)
            o_end = min(len(self.original), o_end + context)
            while o_start > 0 and not self.original[o_start - 1].isspace():
                o_start -= 1
            while o_end < len(self.original) and not self.original[o_end].isspace():
                o_end += 1
        return self.original[o_start:o_end].strip()

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        return self.spans[start][0], self.spans[min(end, len(self.spans)) - 1][1]


def _script_counts(token: str) -> tuple[int, int]:
    latin = cyr = 0
    for ch in token:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if "CYRILLIC" in name:
            cyr += 1
        elif "LATIN" in name or ch in _TRANSLIT_SINGLE:
            latin += 1
    return latin, cyr


def _fold_cyrillic_token(token: str, base: int) -> list[tuple[str, int, int]]:
    letters = sum(ch.isalpha() for ch in token)
    digits = sum(ch.isdigit() for ch in token)
    allow_leet = letters >= 2 and digits < letters
    out: list[tuple[str, int, int]] = []
    for i, ch in enumerate(token):
        pos = base + i
        if ch in _HOMOGLYPHS_UPPER:
            out.append((_HOMOGLYPHS_UPPER[ch], pos, pos + 1))
        elif ch.lower() in _HOMOGLYPHS_LOWER and ch.isascii():
            out.append((_HOMOGLYPHS_LOWER[ch.lower()], pos, pos + 1))
        elif allow_leet and ch in _LEET and _inside_word(token, i):
            out.append((_LEET[ch], pos, pos + 1))
        else:
            out.append((ch.lower(), pos, pos + 1))
    return out


def _inside_word(token: str, i: int) -> bool:
    left = token[i - 1].isalpha() if i > 0 else False
    right = token[i + 1].isalpha() if i + 1 < len(token) else False
    return left or right


def _transliterate_token(token: str, base: int) -> list[tuple[str, int, int]]:
    low = token.lower()
    letters = sum(ch.isalpha() for ch in low)
    digits = sum(ch.isdigit() for ch in low)
    allow_leet = letters >= 2 and digits < letters
    out: list[tuple[str, int, int]] = []
    i = 0
    while i < len(low):
        pos = base + i
        matched = False
        for src, dst in _TRANSLIT_MULTI:
            if low.startswith(src, i):
                out.append((dst, pos, pos + len(src)))
                i += len(src)
                matched = True
                break
        if matched:
            continue
        ch = low[i]
        if ch == "i" and i > 0 and low[i - 1] in _VOWELS_LAT and (i + 1 == len(low) or not low[i + 1].isalpha()):
            out.append(("й", pos, pos + 1))
        elif ch == "y":
            prev_vowel = i > 0 and low[i - 1] in _VOWELS_LAT
            out.append(("й" if prev_vowel else "ы", pos, pos + 1))
        elif ch in _TRANSLIT_SINGLE:
            for sub in _TRANSLIT_SINGLE[ch]:
                out.append((sub, pos, pos + 1))
        elif allow_leet and ch in _LEET and _inside_word(low, i):
            out.append((_LEET[ch], pos, pos + 1))
        else:
            out.append((ch, pos, pos + 1))
        i += 1
    return out


def _fold_token(token: str, base: int) -> list[tuple[str, int, int]]:
    if _URLISH_RE.search(token):
        return [(ch.lower(), base + i, base + i + 1) for i, ch in enumerate(token)]
    latin, cyr = _script_counts(token)
    if cyr and cyr >= latin:
        return _fold_cyrillic_token(token, base)
    if latin:
        return _transliterate_token(token, base)
    return [(ch.lower(), base + i, base + i + 1) for i, ch in enumerate(token)]


def _join_spaced_letters(chars: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Убрать разделители внутри «р а з р я д к и»; у букв остаются их позиции в оригинале."""
    text = "".join(c for c, _, _ in chars)
    drop: set[int] = set()
    for match in _SPACED_RE.finditer(text):
        drop.update(range(match.start() + 1, match.end(), 2))
    return [ch for i, ch in enumerate(chars) if i not in drop] if drop else chars


def normalize_text(raw: str) -> NormText:
    """Свернуть текст для поиска признаков, сохранив связь с оригиналом."""
    original = unicodedata.normalize("NFKC", raw or "")
    # «İ» (казахская латиница) в нижнем регистре даёт два символа; та же длина, позиции не сдвигаются
    work = original.replace("İ", "I")
    chars: list[tuple[str, int, int]] = []
    last_end = 0
    for match in _TOKEN_RE.finditer(work):
        if match.start() > last_end:
            chars.append((" ", last_end, match.start()))
        chars.extend(_fold_token(match.group(), match.start()))
        last_end = match.end()
    # Невидимые символы (U+200B, U+00AD, U+200D, U+FEFF) рвут слова и прячут признаки: выбрасываем,
    # карта позиций остаётся верной, т.к. каждый символ хранит свой диапазон в оригинале.
    # lower() может вернуть несколько символов: раскладываем по одному с тем же диапазоном.
    folded_chars = [("е" if c == "ё" else c.translate(KK_TO_RU), s, e)
                    for chunk, s, e in chars for c in chunk if unicodedata.category(c) not in _DROP_CATEGORIES]
    folded_chars = _join_spaced_letters(folded_chars)
    folded = "".join(c for c, _, _ in folded_chars)
    spans = tuple((s, e) for _, s, e in folded_chars)
    return NormText(original=original, folded=folded, spans=spans)
