"""Раунд 5 словаря: платные прогнозы, «денежная игра», кратность дохода, пересказ чужих сообщений, новости суда."""

from __future__ import annotations

import time

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis
from pruf.normalize.text import normalize_text


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


@pytest.mark.parametrize(("text", "track"), [
    ("Договорной матч сегодня, кэф 11. Вход в закрытый канал 15 000 тг, вчера все зашедшие выиграли", "casino"),
    ("Келісілген матч бүгін, коэффициент 9. Топқа кіру 10 000 тг, кешегі матчқа кіргендердің бәрі ұтты", "casino"),
    ("Бот сигналов на авиатор, точность 97%. Доступ 5000 тг, пиши в тг", "casino"),
    ("Вкладываешь 10к, через 7 дней забираешь 30к. Каждый день выплаты, пиши в лс", "pyramid"),
    ("Giveaway! Win iPhone 16, just pay delivery 2500 tg to kaspi 4400 4302 1234 5678", "lottery"),
    ("Картаңыздың нөмірін және артындағы 3 цифрды жіберіңіз, сыйлық сізге аударылады. Сіз жеңімпазсыз!", "lottery"),
])
def test_round5_scam_patterns_reach_medium_on_their_track(detector: Detector, text: str, track: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (text, analysis.score)
    assert analysis.track == track


@pytest.mark.parametrize("text", [
    "Если вам в директ пишут «ссылка в шапке, бонус 200% на депозит» — это казино, жалуйтесь на аккаунт",
    "Блогеры, которые показывают «занос 3 млн» и дают ссылку в шапке, получают процент с ваших проигрышей. Не ведитесь",
    "Алматы сотында «қаржылық пирамида» құрып, 500 адамды алдаған екі адам 6 жылға сотталды",
    "Итоги тиража лото 6/49: выигрыш получили 12 участников, участие по лицензии, без доплат",
    "Байқауға қатысу тегін, қосымша төлем жоқ. Жеңімпазды кездейсоқ таңдаймыз",
])
def test_round5_warnings_news_and_legal_draws_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (text, analysis.score, [e.feature_id for e in analysis.evidence])


def test_spaced_letters_with_double_space_keep_word_boundary() -> None:
    # Arrange
    text = "к а з и н о  б о н у с"

    # Act
    folded = normalize_text(text).folded

    # Assert
    assert "казино бонус" in folded


def test_reported_message_still_counts_when_the_author_asks_directly(detector: Detector) -> None:
    # Arrange: пересказ в одном предложении не гасит прямой призыв в другом
    text = "Если вам пишут — это не к нам. Слоты, бонус 300% на первый деп, ссылка в шапке, пиши в лс"

    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.track == "casino"
    assert analysis.level in ("medium", "high")


@pytest.mark.parametrize("text", [
    "Если вам интересно — вход от 20к, через 10 дней х3, пиши в лс",
    "Блогеры, которые с нами работают, уже на плюсе: слоты, ссылка в шапке, бонус 200% на первый деп, пиши в лс",
    "Вкладываешь 10к, через 7 дней забираешь 30к. Каждый день выплаты, пиши в лс. Сотында дәлелденді",
    "Розыгрыш iPhone 15! Участие 1000 тг на каспи 87011234567. Результаты тиража в сторис",
    "к  а  з  и  н  о  бонус 200% на депозит, ссылка в шапке",
])
def test_review_evasions_do_not_drop_a_scam_to_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (text, analysis.score)


@pytest.mark.parametrize("text", [
    "Мемлекеттік бағдарлама шеңберінде 500 отбасыға пәтер берілді",
    "Футбол ойнау үшін жаңа алаң ашылды, кіру 500 тг",
    "Концерт Димаша в Астане, кіру 15 000 тг, билеты в кассе",
    "Kaspi подписка 990 тг, доступ к фильмам",
    "Подписка на фитнес 15 000 тг в месяц, доступ в бассейн 2000 тг",
    "Работа на договорной основе, зарплата от 300 000 тг, пишите в тг",
    "Экспресс-доставка 1500 тг, VIP-упаковка 2000 тг, подарочный гифт-бокс",
    "Краш-тест нового Toyota: 5 звезд, цена от 15 млн тг",
    "Мобильная игра: пополнил 2000 тг, вывел кристаллы на аккаунт",
    "Сендерге жаңа коллекция келді! Көйлектер 8000 тг, жеткізу тегін",
])
def test_review_everyday_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (text, analysis.score, [e.feature_id for e in analysis.evidence])


def test_long_digit_run_after_time_word_is_processed_quickly(detector: Detector) -> None:
    # Arrange: раньше \d+ и \w+ делили одни цифры, и такой пост шёл 10 секунд
    text = "за " + "1" * 19990

    # Act
    started = time.perf_counter()
    _analyze(detector, text)

    # Assert
    assert time.perf_counter() - started < 2.0
