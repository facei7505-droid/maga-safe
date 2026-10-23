"""ML-классификатор: char n-gram TF-IDF + логистическая регрессия по свёрнутому тексту.

Классы: legit, lottery, casino, pyramid. Модель дополняет правила, но не заменяет их:
без правил её вклад ограничен средним риском (см. scoring.py).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from pruf.normalize.text import normalize_text

log = logging.getLogger(__name__)
CLASSES = ("legit", "lottery", "casino", "pyramid")


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True, max_features=200_000)),
        ("clf", LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")),
    ])


class TrackClassifier:
    def __init__(self, pipeline: Pipeline):
        self._pipeline = pipeline

    @classmethod
    def train(cls, texts: Sequence[str], labels: Sequence[str]) -> TrackClassifier:
        folded = [normalize_text(t).folded for t in texts]
        pipeline = build_pipeline()
        pipeline.fit(folded, list(labels))
        return cls(pipeline)

    @classmethod
    def load(cls, path: Path) -> TrackClassifier | None:
        if not path.exists():
            return None
        # joblib = pickle: грузим только модель, обученную нашим scripts/train.py и лежащую в каталоге
        # проекта. Путь задаёт оператор через PRUF_MODEL_PATH; файлы от пользователей сюда не попадают.
        try:
            return cls(joblib.load(path))
        except Exception as exc:  # noqa: BLE001 — битый файл модели не должен ронять сервис, работаем без ML
            log.warning("не удалось загрузить модель %s: %s", path, exc)
            return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._pipeline, path)

    def predict_folded(self, folded: str) -> dict[str, float]:
        probs = self._pipeline.predict_proba([folded])[0]
        return {label: float(p) for label, p in zip(self._pipeline.classes_, probs)}
