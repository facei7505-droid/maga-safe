"""Раунд 6: ML как второй сигнал, кратность суммы, копилки, эмодзи внутри слов, турниры, «бұл scam емес»."""

from __future__ import annotations

import json

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.detect.training import HANDWRITTEN_REPEAT, training_rows
from pruf.models import Analysis, Evidence
from pruf.normalize.text import normalize_text
from pruf.scoring import ML_CONFIRM, SINGLE_CAP, combine


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _ev(fid: str, track: str, weight: float, *, core: bool = False) -> Evidence:
    return Evidence(feature_id=fid, track=track, label=fid, weight=weight, source="text", core=core)


@pytest.mark.parametrize(("text", "track"), [
    ("Акция для своих: удваиваем любую сумму за 5 дней. Перевели 100к — забрали 200к. Пригласи друга — ещё +10%", "pyramid"),
    ("Kopilka Altyn Shanyraq: vznos 20k, cherez 2 nedeli poluchaesh 160k. Sistema 1-2-4-8", "pyramid"),
    ("Қайырымдылық шеңбері: 10 000 теңге салыңыз, 8 адам жинағанда 80 000 аласыз. Тек өз адамдарымызға, жазыңыз директке", "pyramid"),
    ("Ка🎰зи🎰но без верификации, вывод моментально, рег по ссылке bit.ly/3xYz", "casino"),
    ("Апалар, бір ойын таптым, 500 тг салып 30 мың шығардым, бүгін каспиге түсті. Кім қызықса + жазыңыз", "casino"),
    ("Осторожно, вокруг много мошенников! Мы работаем честно: вклад от 50 000 тг, доход 30% в месяц. Каспи 87071112233", "pyramid"),
])
def test_round6_scam_patterns_reach_medium(detector: Detector, text: str, track: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (text, analysis.score)
    assert analysis.track == track


@pytest.mark.parametrize("text", [
    "Турнир по мафии в субботу, взнос за участие 3000 тг, победитель получает кубок и сертификат. Запись в лс",
    "Поздравляем победителя конкурса! Приз доставим курьером бесплатно, ничего оплачивать не нужно",
    "Если в сторис пишут «нашла игру, где реально выводишь деньги» — это реклама казино. Не регистрируйтесь по таким ссылкам",
    "Кыздар, Айгеримге туган кунге сыйлык алуга 5 мын тг-ден жинаймыз. Маган Каспиге тастандар",
])
def test_round6_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (text, analysis.score, [e.feature_id for e in analysis.evidence])


def test_emoji_inside_a_word_is_dropped_but_kept_between_words() -> None:
    # Act
    joined = normalize_text("Ка🎰зи🎰но и привет 🎁 мир").folded

    # Assert
    assert joined.startswith("казино")
    assert "🎁" in joined


def test_confident_model_lifts_single_feature_cap() -> None:
    # Arrange
    evidence = [_ev("pyramid.high_return", "pyramid", 24, core=True), _ev("common.urgency", "common", 6)]

    # Act
    without_ml = combine(evidence, ml={"pyramid": 0.1, "lottery": 0.0, "casino": 0.0})
    with_ml = combine(evidence, ml={"pyramid": ML_CONFIRM + 0.2, "lottery": 0.0, "casino": 0.0})

    # Assert
    assert without_ml.score <= SINGLE_CAP
    assert with_ml.score > SINGLE_CAP
    assert with_ml.level != "high"  # одна модель не даёт обязательного сочетания для высокого риска


def test_training_rows_repeat_handwritten_posts(tmp_path) -> None:
    # Arrange
    path = tmp_path / "set.jsonl"
    path.write_text(json.dumps({"id": "x", "label": "casino", "lang": "ru", "text": "слоты"}, ensure_ascii=False) + "\n", encoding="utf-8")

    # Act
    texts, labels = training_rows([("синтетика", "legit")], [path, tmp_path / "missing.jsonl"])

    # Assert
    assert texts == ["синтетика"] + ["слоты"] * HANDWRITTEN_REPEAT
    assert labels == ["legit"] + ["casino"] * HANDWRITTEN_REPEAT
