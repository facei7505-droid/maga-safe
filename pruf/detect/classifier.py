"""ML-классификатор: char n-gram TF-IDF + логистическая регрессия по свёрнутому тексту.

Классы: legit, lottery, casino, pyramid. Модель дополняет правила, но не заменяет их:
без правил уверенная модель ставит пост максимум в «средний» и показывает слова, на которые опиралась
(см. scoring.py).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from pruf.normalize.text import normalize_text

log = logging.getLogger(__name__)
CLASSES = ("legit", "lottery", "casino", "pyramid")
_WORD_RE = re.compile(r"[^\W\d_]{3,}")  # слова без цифр: «000» и «кс100» аналитику ничего не объясняют


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
            log.error("не удалось загрузить модель %s, ML выключен: %s", path, exc)
            return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._pipeline, path)

    def predict_folded(self, folded: str) -> dict[str, float]:
        probs = self._pipeline.predict_proba([folded])[0]
        return {label: float(p) for label, p in zip(self._pipeline.classes_, probs)}

    def explain(self, folded: str, label: str, top: int = 3) -> list[str]:
        """Слова текста, сильнее всего толкающие модель к label против legit: вклад их char n-грамм."""
        tfidf, clf = self._pipeline.named_steps["tfidf"], self._pipeline.named_steps["clf"]
        classes = list(clf.classes_)
        if label == "legit" or label not in classes or "legit" not in classes:
            return []
        if clf.coef_.shape[0] == 1:  # два класса: одна строка весов «за classes_[1]»
            weights = clf.coef_[0] if classes[1] == label else -clf.coef_[0]
        else:
            weights = clf.coef_[classes.index(label)] - clf.coef_[classes.index("legit")]
        row = tfidf.transform([folded]).tocoo()
        values = dict(zip(row.col, row.data))
        vocab = tfidf.vocabulary_
        scores: dict[str, float] = {}
        for word in dict.fromkeys(_WORD_RE.findall(folded)):
            padded = f" {word} "
            grams = {padded[i:i + n] for n in range(2, 6) for i in range(len(padded) - n + 1)}
            idx = (vocab.get(g) for g in grams)
            scores[word] = sum(values[j] * weights[j] for j in idx if j in values)
        ranked = sorted((w for w, v in scores.items() if v > 0), key=lambda w: -scores[w])
        return ranked[:top]
