"""Раунд 2–3 словаря: маскировка, сленг, плата за приз, поддельные домены брендов и пересказ схем в предупреждениях."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _features(analysis: Analysis) -> set[str]:
    return {e.feature_id for e in analysis.evidence}


@pytest.mark.parametrize(("text", "track"), [
    ("к а з и н о без вериф, деп от 500тг, ссыль в шапке", "casino"),
    ("с 5к поднял 230к на 0лимпе за вечер, ссылку скину в тг", "casino"),
    ("Ищу людей: ставишь 2000, забираешь на нужном коэффициенте. Схему скину в личку", "casino"),
    ("Ставки на спорт с гарантией: договорные матчи, проходимость 95%, сигналы в закрытом тг-канале", "casino"),
    ("Поздравляем! Вы выиграли iPhone 16. Чтобы забрать приз, оплатите комиссию 3500 тенге", "lottery"),
    ("Сіз жеңімпаз атандыңыз! Сыйлықты алу үшін жеткізу ақысын 2000 теңге аударыңыз", "lottery"),
    ("Касса взаимопомощи: вход 7000 тг, через 10 дней получаешь 56 000 тг", "pyramid"),
    ("Kaspi арқылы 10 000 теңге салып, 3 күнде 30 000 теңге алыңыз! Әр досыңыз үшін бонус", "pyramid"),
])
def test_disguised_and_slang_scams_reach_medium_on_their_track(detector: Detector, text: str, track: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (text, analysis.score)
    assert analysis.track == track


@pytest.mark.parametrize("text", [
    "Подарок к каждому заказу! Оплата при доставке, курьер привезёт за день",
    "Промокод SALE на скидку 10% на всё! Каталог и ссылка в шапке профиля",
    "Собираем на операцию, нужно 3,5 млн тенге. Kaspi Gold: +7 701 555 44 33",
    "Требуются курьеры, зарплата от 300 000 тг, без вложений и оплаты обучения — резюме по номеру +7 727 315 40 12",
    "Мы никогда не обманываем клиентов: гарантия на ремонт 12 месяцев",
])
def test_everyday_posts_with_risky_words_stay_low(detector: Detector, text: str) -> None:
    assert _analyze(detector, text).level == "low"


def test_warning_that_quotes_scam_phrases_is_not_flagged(detector: Detector) -> None:
    # Arrange: полиция пересказывает схему в кавычках
    text = ("Полиция Алматы предупреждает: мошенники пишут «вы выиграли iPhone, оплатите доставку 2000 тг» "
            "и просят перевести деньги на Kaspi. Не переводите!")

    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low"
    assert "lottery.prize_fee" not in _features(analysis)
    assert "lottery.awareness" in _features(analysis)


def test_quoted_phrase_still_counts_when_post_is_not_a_warning(detector: Detector) -> None:
    analysis = _analyze(detector, "Розыгрыш! «Вы выиграли приз», осталось оплатить доставку 1990 тг на каспи")
    assert "lottery.prize_fee" in _features(analysis)


def test_brand_lookalike_domain_is_flagged_but_official_domain_is_not(detector: Detector) -> None:
    # Act
    fake = _analyze(detector, "Kaspi раздаёт по 100 000 тг! Переходи kaspi-bonus.top и введи данные карты")
    real = _analyze(detector, "Новые условия рассрочки на kaspi.kz")

    # Assert
    assert "common.brand_lookalike" in _features(fake)
    assert fake.level == "high" and fake.track == "lottery"
    assert "common.brand_lookalike" not in _features(real)


def test_shop_promo_code_counts_only_near_casino_context(detector: Detector) -> None:
    assert "casino.bonus" not in _features(_analyze(detector, "Промокод SALE на скидку 10%"))
    assert "casino.bonus" in _features(_analyze(detector, "Промокод PRUF: бонус 150% на первый деп в слотах"))
