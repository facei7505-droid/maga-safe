"""Раунд 15: пропуски на реальных постах real_v3 — провайдеры слотов, условия акций, прогнозы с «кэфом», «перепечатка текстов».

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
    "🔥 Летний разгон! Введи код SUMMER и забери 70 FS в Sweet Bonanza (Pragmatic Play) 🎰 Депозит: от 9 999 ₸. Ставка: 80 ₸. Максимальный выигрыш: без ограничений",
    "🍒 Сочный урожай: 50 FS в Fruit Party (BGaming)! Бонус-код JUICY. Депозит от 12 000 ₸, вейджер х35",
    "⚡ Битва богов: 40 FS в новом слоте от Belatra. Ставка: 50 ₸, максимальный выигрыш х3000. Успей до воскресенья",
])
def test_slot_promo_with_terms_reaches_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])
    assert analysis.track == "casino"


@pytest.mark.parametrize("text", [
    "🚨 Обращение к ученикам! На сайте огромное пополнение заказов на перепечатку текстов и транскрибацию аудио. Исполнители, разбирайте, достойный заработок ждёт",
    "Доброе утро, фрилансеры! Свежие заказы на перепечатку текстов уже на сайте. Делимся отчётами наших учеников за неделю, пора начинать зарабатывать 💪",
])
def test_text_retyping_job_scheme_reaches_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])
    assert analysis.track == "pyramid"


@pytest.mark.parametrize(("text", "feature"), [
    ("Тегін болжам ✅ Тәуекел бар ✊ Кэф: 4.8 ✅", "casino.betting_tip"),
    ("Мой выбор на сегодня: Лидс — МЮ, ТБ 2.5 — 1.92", "casino.betting_tip"),
    ("Подборка на вечер: Бавария победит (коэффициент – 1,74)", "casino.betting_tip"),
    ("Банктан: 10% ⚠️ экспресс дня", "casino.betting_tip"),
    ("Новинки от Pragmatic Play уже в нашем лобби", "casino.terms"),
    ("Депозит: от 5000 ₸. Ставка: 100 ₸", "casino.wager_terms"),
    ("Требуются люди на перепечатку текстов, оплата сразу", "pyramid.easy_job"),
    ("Бүгін железа матч, банкті еселеп аламыз ✊", "casino.fixed_match"),
    ("Кешегі экспресс смело шықты жігіттер ✅", "casino.fixed_match"),
    ("Сатылымдағы экспресс тағы кірді, 3кэф ✅", "casino.betting_tip"),
])
def test_round15_features_fire(text: str, feature: str) -> None:
    # Act
    found = _features(text)

    # Assert
    assert feature in found, found


@pytest.mark.parametrize("text", [
    # спортивная новость с коэффициентом букмекеров — не прогноз каппера
    "Букмекеры до матча давали на победу «Кайрата» коэффициент 2,85, но алматинцы справились",
    "Перед финалом букмекеры видят фаворитом «Реал» с коэффициентом 1.85",
    # банковский вклад: «ставка» в процентах, а не в тенге
    "Kaspi Депозит: ставка 13,8% годовых, пополнение и снятие без ограничений",
    # обычная вакансия без «заказов на перепечатку»
    "Ищем транскрибатора для подкаста, полный день, оформление по ТК, зарплата по договорённости",
])
def test_round15_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])
