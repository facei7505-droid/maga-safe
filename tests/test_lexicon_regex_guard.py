"""Защита словаря от квадратичного перебора: каждый шаблон на патологических строках растёт линейно.

Словарь — сотни регулярных выражений, и одна неосторожная правка вида «[\\d\\s]*» перед широким окном
даёт квадратичное время на длинном посте (атака на бот и API). Абсолютный лимит зависит от машины CI,
поэтому сравниваем рост: текст вчетверо длиннее — линейный шаблон работает примерно вчетверо дольше, квадратичный
в шестнадцать раз. Большой разрыв между ними делает тест устойчивым к паузам машины. Шаблоны быстрее порога шума
не проверяем.
"""

from __future__ import annotations

import time

import pytest

from pruf.detect.lexicon import FEATURES
from pruf.normalize.text import normalize_text

ATTACKS = {
    "пробелы между цифрами": "1 ",
    "цепочка цифр": "9",
    "суммы подряд": "100 000 тг ",
    "слова схемы подряд": "оплатите доставку приз ",
    "длинное слово": "а",
    "знаки препинания": "!?. ",
    "казахские суммы": "ұтыс жеңімпаз ақысы 5 000 ₸ ",
}
SHORT, LONG = 2000, 8000
NOISE_MS = 10.0  # быстрее — шум таймера, рост не измерить
MAX_GROWTH = 8.0  # линейный рост ~4; квадратичный ~16


def _ms(pattern, text: str) -> float:
    best = float("inf")
    for _ in range(3):  # лучший из трёх: сглаживает паузы сборщика мусора и соседних процессов
        t = time.perf_counter()
        for _match in pattern.finditer(text):
            pass
        best = min(best, (time.perf_counter() - t) * 1000)
    return best


@pytest.mark.parametrize("attack", list(ATTACKS))
def test_every_pattern_grows_linearly(attack: str) -> None:
    unit = ATTACKS[attack]
    short = normalize_text(unit * (SHORT // len(unit))).folded
    long = normalize_text(unit * (LONG // len(unit))).folded
    slow = []
    for feature in FEATURES:
        for i, pattern in enumerate(feature.compiled()):
            t_long = _ms(pattern, long)
            if t_long < NOISE_MS:
                continue
            growth = t_long / max(_ms(pattern, short), 0.1)
            if growth > MAX_GROWTH:
                slow.append(f"{feature.id}[{i}]: ×{growth:.1f} ({t_long:.0f} мс на {LONG} символов)")
    assert slow == [], "квадратичный рост — ограничьте повторы ({0,N} вместо *): " + "; ".join(slow)
