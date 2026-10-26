"""Раунд 16: пропуски на реальных постах real_v4 — реферальные боты, отчёты сигнальщиков, торговые роботы, казахские промокоды.

Тексты написаны заново по образцу пропусков, реальные посты в репозиторий не попадают.
"""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.detect.rules import find_features
from pruf.models import Analysis
from pruf.normalize.text import normalize_text


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)], allow_llm=False).analysis


def _features(text: str) -> set[str]:
    return {e.feature_id for e in find_features(normalize_text(text))}


@pytest.mark.parametrize("text", [
    "🤖 Запусти своего ИИ-агента, который добывает токены за тебя! 📊 2.1–3.4% прибыли в день. Регистрация: t.me/TokenFarmAppBot?start=552918374",
    "🎰 Starlight Princess — Play'n GO. Wild белгілері көбейткішпен келеді. Промокод: LUCKY50FS",
    "⚽ Финалды бірге көрейік! 1XBET тіркеліңіз, ал bonus777 промокодымен 500 000 ₸-ге дейін бонус алыңыз",
])
def test_round16_schemes_reach_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize(("text", "feature"), [
    ("Результаты закрытых сделок: ETHUSDT · short · +3,00% (тейк)", "pyramid.signal_results"),
    ("Друзья, мы запустили нашего робота! Год тестов, теперь он торгует за вас", "pyramid.passive"),
    ("Заходи: t.me/MinerGameBot?start=r_7731902", "common.ref_bot_link"),
    ("Промокод: SPIN40FS", "casino.bonus"),
])
def test_round16_features_fire(text: str, feature: str) -> None:
    # Act
    found = _features(text)

    # Assert
    assert feature in found, found


@pytest.mark.parametrize("text", [
    # бот проверки итогов розыгрыша: параметр start не номер пригласившего
    "Победители: @anna, @bek. Проверить итоги: t.me/concubot?start=check-398349",
    # новость о рынке без сделок и обещаний
    "Биткоин за неделю вырос на 4%, аналитики связывают рост с притоком в ETF",
])
def test_round16_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])
