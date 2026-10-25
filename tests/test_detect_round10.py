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


def test_retold_sms_without_warning_is_not_a_warning(detector: Detector) -> None:
    # Act: «мне пришло сообщение «…». Повезло!» — пересказ без предупреждения, кавычки не прячут просьбу
    analysis = _analyze(detector, "Мне сегодня пришло сообщение «Ваш номер выиграл 500 000 тг! Для получения оплатите комиссию 3 000 тг, пишите в лс». Повезло!")

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


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


@pytest.mark.parametrize("text", [
    # ревью раунда 10: рекламные фразы не должны работать как предупреждение
    "Никакие банки не дадут 30% в месяц, а наш проект даёт! Вход от 20 000 тг",
    "Банки так не делают, а мы платим 3% в день! Вход от 20 000 тг, вывод каждый день",
    "Розыгрыш iPhone 15! Участие 1000 тг. Так не делают нигде — шанс 1 из 50!",
    "Казино Vavada дарит 200% на первый депозит и 100 фриспинов. Другие так не делают",
    # «заблокированы 72 часа» — не новость о блокировке сайтов
    "Ваши 1 200 USDT заблокированы 72 часа. Для разблокировки нужно внести депозит 150 USDT, прибыль 30% в день",
    # подражание банку после просьбы ввести данные
    "Многодетным семьям положена единовременная выплата 70 000 тг. Чтобы получить, введите ИИН и номер карты в боте @vyplata_bot. Код из смс никому не сообщайте",
    "Выплата 70 000 тг всем семьям. Отправьте номер карты не говоря никому, пишите @vyplata_kz",
    # упоминание egov.kz не делает выплату легальной
    "Многодетным единовременная выплата 70 000 тг (список на egov.kz). Для зачисления пришлите ИИН и номер карты @vyplata_kz",
    "Абонентам положена компенсация до 150 000 тг. Сопровождение стоит 4 500, оплатите и деньги придут за 3 дня",
    # возврат потерянного «юристами» за пошлину
    "Вы вкладывали в проект и потеряли деньги? Наши юристы вернут их, нужно оплатить пошлину 20 000 тг",
    "Пострадали от пирамиды? Наши юристы помогут вернуть средства, оплатите пошлину 20 000 тг",
    "Вернём деньги, потерянные в пирамидах и у брокеров! Наши юристы, оплата пошлины 20 000 тг",
])
def test_round10_review_evasions_reach_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    "Организаторы обещали 10% в месяц. Вкладчики потеряли деньги, суд постановил возврат средств",
    "Если вы потеряли чек, возврат товара всё равно возможен по выписке",
    "Потеряли кошелёк на остановке? Нашедший вернёт за вознаграждение, звоните",
    "Пособие назначается по ИИН через ЦОН, номер карты указывать не нужно",
    "Компенсация за свет пересчитана автоматически. Счета за ноябрь нужно оплатить до 25 декабря",
])
def test_round10_review_false_positives_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])
