"""Раунд 10: фейковые госвыплаты, «вывод заморожен — внесите», возврат потерянных денег, официальные лотереи, цитаты в предупреждениях."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.detect.rules import find_features
from pruf.models import Analysis
from pruf.normalize.text import normalize_text


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _features(text: str) -> set[str]:
    return {e.feature_id for e in find_features(normalize_text(text))}


@pytest.mark.parametrize(("text", "feature"), [
    ("Многодетным начата единовременная выплата 70 000 тг. Проверить право: viplata-semyam.site, укажите ИИН и номер карты", "lottery.fake_payout"),
    ("Зейнеткерлерге қосымша төлем 50 000 тг. Тексеру үшін ЖСН мен карта нөмірін ботқа жіберіңіз", "lottery.fake_payout"),
    ("Абонентам положена компенсация до 150 000 тг, оплатите юридическое сопровождение 4 500 и деньги придут за 3 дня", "lottery.fake_payout"),
    ("vyplata kompensacii za svet do 60 000 tg, vvedite IIN i kartu", "lottery.fake_payout"),
    ("Ваш вывод 1 200 USDT заморожен. Для снятия ограничения внесите депозит 150 USDT", "pyramid.entry"),
    ("Вы вкладывали в проект и потеряли деньги? Наши юристы вернут их, нужно оплатить пошлину 20 000 тг", "pyramid.entry"),
    ("vy vkladyvali v proekt i poteryali dengi? Yuristy vernut vse, oplatite poshlinu 15 000 tg", "pyramid.entry"),
    ("Скидываешь USDT на кошелёк — через час х2 обратно", "pyramid.high_return"),
    ("Продаю скрипт для рулетки, алгоритм угадывает 9 из 10", "casino.fixed_match"),
    ("Live-казино: баккара и блэкджек с живыми дилерами", "casino.terms"),
])
def test_round10_patterns_fire(text: str, feature: str) -> None:
    # Act
    found = _features(text)

    # Assert
    assert feature in found, found


@pytest.mark.parametrize("text", [
    "Купил билет лотереи в киоске, вечером проверил тираж по телеканалу — пусто, но весело",
    "Пособие на ребёнка начислено, статус можно проверить на egov.kz по ИИН",
    "Закон: выплата по кредиту теперь не больше 50% дохода, данные карты банки обязаны защищать",
    "Заблокировано более 300 сайтов онлайн-казино за месяц, сообщил регулятор",
    "Компенсация за отключение света: акимат начислит перерасчёт автоматически, данные карты никому не сообщайте",
    "Суд обязал организаторов пирамиды вернуть деньги вкладчикам, которые потеряли сбережения",
])
def test_round10_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_quoted_scam_sms_is_not_the_authors_ask() -> None:
    # Act: просьба «оплатите» стоит в кавычках — это цитата пришедшего смс
    found = _features("Мне сегодня пришло смс «Ваш номер выиграл 500 000 тг, для получения оплатите комиссию». Банки так не делают!")

    # Assert
    assert "common.author_ask" not in found


def test_unquoted_ask_still_counts_as_authors_ask() -> None:
    # Act
    found = _features("Ваш номер выиграл 500 000 тг, для получения оплатите комиссию")

    # Assert
    assert "common.author_ask" in found


def test_quoted_sms_warning_stays_low(detector: Detector) -> None:
    # Act
    analysis = _analyze(detector, "Друзья, осторожно! Мне пришло смс «Ваш номер выиграл 300 000 тг, для получения оплатите комиссию 3 000 тг». "
                                  "Никакие банки так не делают, не переводите ничего!")

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_bank_style_warning_does_not_hide_a_payout_card_ask(detector: Detector) -> None:
    # Act: мошенники подражают банку — «код никому не сообщайте» после просьбы ввести карту
    analysis = _analyze(detector, "Для получения выплаты 80 000 тг введите данные карты. Код из смс никому не сообщайте")

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])
