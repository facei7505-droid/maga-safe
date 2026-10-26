"""Обучающая выборка ML-модели: синтетика + ручные dev-наборы.

Синтетика даёт объём, ручные наборы — живой язык (сленг, казахский, транслит, маскировку), которого
генератор не знает. Ручные посты повторяются HANDWRITTEN_REPEAT раз, иначе их перевешивают тысячи
синтетических. Слепой набор текущего раунда сюда не входит никогда: на нём только измеряем.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pruf.config import ROOT

DEV_SETS: tuple[str, ...] = (
    "handwritten", "dev_round2", "dev_round4", "dev_round5", "dev_round6",
    "handwritten_blind", "handwritten_blind_v2", "handwritten_blind_v3", "handwritten_blind_v4", "handwritten_blind_v5",
    "handwritten_blind_v6", "handwritten_blind_v7", "handwritten_blind_v8", "handwritten_blind_v9", "handwritten_blind_v10", "handwritten_blind_v11", "handwritten_blind_v12",
    "handwritten_blind_v13", "handwritten_blind_v14",
    "handwritten_blind_v15", "real_v1",  # real_v1: реальные посты открытых каналов KZ, обезличены (scripts/anonymize_real.py)
)
HANDWRITTEN_REPEAT = 3


def dev_paths(root: Path = ROOT) -> list[Path]:
    return [root / "eval" / f"{name}.jsonl" for name in DEV_SETS]


def read_handwritten(path: Path) -> list[tuple[str, str]]:
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [(r["text"], r["label"]) for r in rows]


def training_rows(synthetic: Iterable[tuple[str, str]], handwritten: Sequence[Path] | None = None) -> tuple[list[str], list[str]]:
    """Тексты и метки для TrackClassifier.train; отсутствующие наборы пропускаются."""
    rows = list(synthetic)
    for path in dev_paths() if handwritten is None else handwritten:
        if path.exists():
            rows += read_handwritten(path) * HANDWRITTEN_REPEAT
    return [t for t, _ in rows], [label for _, label in rows]
