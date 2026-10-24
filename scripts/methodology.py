"""Генерирует docs/methodology.md из словаря и констант скоринга: документ всегда совпадает с кодом.

Запуск: python scripts/methodology.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PRUF_DEV_MODE", "1")

from pruf import scoring  # noqa: E402
from pruf.config import Settings  # noqa: E402
from pruf.detect.detector import Detector, SourceText  # noqa: E402
from pruf.detect.lexicon import FEATURES, TRACK_LABELS  # noqa: E402
from pruf.detect.rules import NEGATABLE  # noqa: E402
from pruf.models import HIGH_THRESHOLD, MEDIUM_THRESHOLD  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "methodology.md"
EXAMPLE = "Поздравляем! Вы выиграли iPhone 16 в нашем розыгрыше. Чтобы забрать приз, оплатите доставку 2500 тг на Kaspi +7 701 234 56 78"
WARNING = "Полиция предупреждает: мошенники пишут «вы выиграли iPhone, оплатите доставку 2500 тг». Не переводите деньги!"
LINK_FEATURES = (
    ("casino.domain", "casino", "Ссылка на домен казино/букмекера", 20, "ядровой"),
    ("common.brand_lookalike", "common", "Домен похож на бренд (kaspi, halyk, magnum…), но не официальный", 14, ""),
    ("common.shortener", "common", "Сокращённая ссылка скрывает конечный адрес", 6, ""),
    ("common.kaspi_pay_link", "common", "Платёжная ссылка Kaspi в сообщении", 8, ""),
    ("common.requisite", "common", "Реквизиты для перевода в тексте", 6, ""),
)


def _kind(f) -> str:
    return "стоп" if f.stop else "ядровой" if f.core else ""


def _example(detector: Detector, text: str) -> list[str]:
    a = detector.detect([SourceText("text", text)]).analysis
    lines = [f"> {text}", "", "| Признак | Вес | Цитата |", "|---|---|---|"]
    first = {e.feature_id: e for e in reversed(a.evidence) if e.source != "ml"}
    lines += [f"| {e.label} | {e.weight:+g} | {e.quote} |" for e in a.evidence if first.get(e.feature_id) is e]
    lines += ["", f"Итог: **{a.level} · {a.score:g}**. {a.summary}", ""]
    return lines


def render() -> str:
    lines = [
        "# ПРУФ: методика оценки риска", "",
        "Документ сгенерирован `scripts/methodology.py` из `pruf/detect/lexicon.py` и `pruf/scoring.py`.", "",
        "## Как считается балл", "",
        f"1. Признаки трека суммируются, каждый один раз. Общие признаки (`common.*`) добавляются, только если у трека есть "
        f"свой положительный признак, кроме вспомогательных ({', '.join(sorted(scoring.AUX_FEATURES))}).",
        f"2. Балл правил = 100 × (1 − e^(−баллы / {scoring.SATURATION:g})).",
        f"3. Модель на n-граммах может только поднять балл: max(правила, {1 - scoring.ML_WEIGHT:.2f} × правила + "
        f"{scoring.ML_WEIGHT:.2f} × 100 × p). Без признаков модель даёт не больше {scoring.ML_ONLY_CAP:g}.",
        f"4. Уровни: низкий < {MEDIUM_THRESHOLD:g} ≤ средний < {HIGH_THRESHOLD:g} ≤ высокий.",
        "5. Потолки (причина показывается аналитику в сводке):",
        f"   - один признак без просьбы о деньгах: не выше {scoring.SINGLE_CAP:g};",
        f"   - высокий риск только при двух ядровых признаках или ядровом + просьбе о деньгах / связи с рискованными постами, иначе {scoring.NO_COMBO_CAP:g};",
        f"   - стоп-признак легальности: не выше {scoring.STOP_CAP:g};",
        f"   - предупреждение или новость о схеме действует на все треки; без просьбы о деньгах, реквизита или ссылки — не выше {scoring.SINGLE_CAP:g}; "
        f"рядом с реквизитом или ссылкой это маскировка: баллы не снимаются, потолок {scoring.STOP_CAP:g};",
        f"6. Признаки-действия под отрицанием («не переводите», «аудармаңыз») и в пересказе («мошенники просят оплатить») "
        f"не считаются: {', '.join(sorted(NEGATABLE))}. В посте-предупреждении не считаются и признаки внутри кавычек.",
        "7. Связи с другими постами (повтор пруфа, правка суммы, реквизит из рискованных кейсов) добавляются отдельной строкой объяснения.",
        "8. LLM спрашивается в спорной зоне 20–74 (один признак у потолка и нижняя часть высокого риска). Он добавляет признаки только с дословными цитатами. Его «это легально» опускает пост до низкого риска, только если LLM прочитал пост целиком и в нём нет ссылки, реквизита, @ника, номера, «пиши в лс», просьбы о деньгах, уверенной ML-модели и связей с рискованными постами: текст недоверенный, поэтому иначе мнение LLM балл не снижает. Повторные тексты берутся из кэша, на вызовы есть дневной бюджет (PRUF_LLM_DAILY_BUDGET).", "",
        "## Признаки словаря", "",
        "| Признак | Трек | Что означает | Вес | Тип | Шаблонов |", "|---|---|---|---|---|---|",
    ]
    for f in FEATURES:
        track = TRACK_LABELS.get(f.track, "общий")
        lines.append(f"| `{f.id}` | {track} | {f.label} | {f.weight:+g} | {_kind(f)} | {len(f.patterns)} |")
    for fid, track, label, weight, kind in LINK_FEATURES:
        lines.append(f"| `{fid}` | {TRACK_LABELS.get(track, 'общий')} | {label} | {weight:+g} | {kind} | по ссылкам и реквизитам |")
    detector = Detector(Settings(model_path=Path("/nonexistent")))
    lines += ["", "## Пример: схема", ""] + _example(detector, EXAMPLE)
    lines += ["## Пример: предупреждение с той же фразой", ""] + _example(detector, WARNING)
    lines += ["Нормализация перед поиском: NFKC, нижний регистр, латинские двойники и цифры вместо букв, транслит, "
              "казахские буквы к русской основе, удаление невидимых символов и диакритик, склейка «к а з и н о»."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"записано {OUT}")
