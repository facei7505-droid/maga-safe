"""Дообучение модели на решениях аналитика: «чемпион и претендент».

Мошенники меняют слова быстрее, чем пополняется словарь. Решения аналитика — уже разметка: посты
подтверждённого кейса — схема своего трека, отклонённого — легальные. Раз в неделю (docs/rollout.md)
scripts/retrain_feedback.py обучает претендента на прежних данных плюс эти посты и сравнивает с текущей
моделью (чемпионом) на отложенной части решений и на всех dev-наборах. Претендент заменяет чемпиона,
только если на решениях он не хуже, а на dev-наборах нет регрессии: одно ошибочное решение не должно
испортить модель для всех. Словарь сам не меняется: признаки, которые люди оспаривают в боте, идут
в отчёт для ручного ревью.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.detector import Detector, SourceText
from pruf.detect.training import HANDWRITTEN_REPEAT, read_handwritten, training_rows
from pruf.graph.builder import CaseGraph
from pruf.normalize.text import normalize_text
from pruf.storage.db import Database

POSITIVE = ("medium", "high")
MIN_FEEDBACK = 20  # меньше — претендент учится на шуме, сравнение ничего не значит
HOLDOUT_SHARE = 0.25
MAX_FPR_RISE = 0.01  # допуск на dev-наборах: один пост из сотни
MAX_RECALL_DROP = 0.01


@dataclass(frozen=True)
class Labeled:
    post_id: int
    text: str
    label: str


def analyst_rows(db: Database, graph: CaseGraph) -> list[Labeled]:
    """Посты кейсов с решением аналитика. Подтверждён — трек поста (или кейса), отклонён — legit.
    Посты низкого риска в подтверждённом кейсе — контекст, а не схема: их не берём."""
    out: list[Labeled] = []
    for key, st in db.case_statuses().items():
        case = graph.case(key)
        if case is None or st["status"] not in ("confirmed", "dismissed"):
            continue
        levels = db.post_levels(case.post_ids)
        major = Counter(t for lvl, t, _ in levels.values() if t and lvl in POSITIVE).most_common(1)
        for post in db.get_posts(case.post_ids):
            text = "\n".join(x for x in (post.get("text"), post.get("ocr_text"), post.get("transcript")) if x)
            if not text.strip():
                continue
            if st["status"] == "dismissed":
                out.append(Labeled(post["id"], text, "legit"))
            elif post["level"] in POSITIVE and (post.get("track") or major):
                out.append(Labeled(post["id"], text, post.get("track") or major[0][0]))
    return out


def in_holdout(post_id: int) -> bool:
    """Детерминированное деление: пост всегда в одной и той же части, повторный запуск сравним с прошлым."""
    return hashlib.sha256(f"holdout:{post_id}".encode()).digest()[0] < 256 * HOLDOUT_SHARE


@dataclass(frozen=True)
class Score:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def fpr(self) -> float:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else 0.0

    @property
    def errors(self) -> int:
        return self.fp + self.fn


def score(detector: Detector, rows: Iterable[tuple[str, str]]) -> Score:
    tp = fp = fn = tn = 0
    for text, label in rows:
        pos = detector.detect([SourceText("text", text)], allow_llm=False).analysis.level in POSITIVE
        scam = label != "legit"
        tp += pos and scam
        fp += pos and not scam
        fn += scam and not pos
        tn += not scam and not pos
    return Score(tp, fp, fn, tn)


def ml_errors(clf: TrackClassifier, rows: Iterable[tuple[str, str]]) -> int:
    """Ошибки самой модели (без правил): «схема или нет» по самому вероятному классу. Правила ловят
    знакомые слова и без модели, поэтому испорченная модель видна только здесь — на новом сленге она подведёт."""
    errors = 0
    for text, label in rows:
        probs = clf.predict_folded(normalize_text(text).folded)
        errors += (max(probs, key=probs.get) == "legit") != (label == "legit")
    return errors


@dataclass(frozen=True)
class Verdict:
    accept: bool
    reason: str
    champion_holdout: Score | None = None
    challenger_holdout: Score | None = None
    champion_dev: Score | None = None
    challenger_dev: Score | None = None
    champion_ml_errors: int | None = None
    challenger_ml_errors: int | None = None


def compare(settings: Settings, champion: TrackClassifier | None, challenger: TrackClassifier,
            holdout: Sequence[Labeled], dev_rows: Sequence[tuple[str, str]]) -> Verdict:
    """Ворота: на отложенных решениях претендент ошибается не чаще, на dev-наборах нет регрессии."""
    if champion is None:
        return Verdict(True, "текущей модели нет: претендент становится первой моделью")
    champ, chall = Detector(settings, classifier=champion), Detector(settings, classifier=challenger)
    hold = [(r.text, r.label) for r in holdout]
    ch_hold, cl_hold = score(champ, hold), score(chall, hold)
    ch_dev, cl_dev = score(champ, dev_rows), score(chall, dev_rows)
    ch_ml, cl_ml = ml_errors(champion, hold), ml_errors(challenger, hold)
    scores = dict(champion_holdout=ch_hold, challenger_holdout=cl_hold, champion_dev=ch_dev, challenger_dev=cl_dev,
                  champion_ml_errors=ch_ml, challenger_ml_errors=cl_ml)
    if cl_ml > ch_ml:
        return Verdict(False, f"модель без правил ошибается на отложенных решениях чаще: {cl_ml} против {ch_ml}", **scores)
    if cl_hold.errors > ch_hold.errors:
        return Verdict(False, f"на отложенных решениях аналитика ошибок больше: {cl_hold.errors} против {ch_hold.errors}", **scores)
    if cl_dev.fpr > ch_dev.fpr + MAX_FPR_RISE:
        return Verdict(False, f"ложных тревог на dev-наборах больше: {cl_dev.fpr:.3f} против {ch_dev.fpr:.3f}", **scores)
    if cl_dev.recall < ch_dev.recall - MAX_RECALL_DROP:
        return Verdict(False, f"полнота на dev-наборах ниже: {cl_dev.recall:.3f} против {ch_dev.recall:.3f}", **scores)
    return Verdict(True, f"ошибок на отложенных решениях {cl_hold.errors} (было {ch_hold.errors}), dev-наборы без регрессии", **scores)


def train_challenger(synthetic: Iterable[tuple[str, str]], feedback: Sequence[Labeled],
                     dev_paths: Sequence[Path] | None = None) -> TrackClassifier:
    """Прежние данные (синтетика + dev-наборы) плюс решения аналитика с тем же весом, что ручные наборы."""
    texts, labels = training_rows(synthetic, dev_paths)
    texts += [r.text for r in feedback] * HANDWRITTEN_REPEAT
    labels += [r.label for r in feedback] * HANDWRITTEN_REPEAT
    return TrackClassifier.train(texts, labels)


def dev_rows(paths: Sequence[Path]) -> list[tuple[str, str]]:
    return [row for p in paths if p.exists() for row in read_handwritten(p)]
