"""Раунд 9: «вам положено — оплатите», отзывы участников пирамид, apk вне магазина, разборы мошенничества, слова модели."""

from __future__ import annotations

import pytest

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.detector import Detector, SourceText
from pruf.detect.rules import find_features
from pruf.models import Analysis, Evidence
from pruf.normalize.text import normalize_text
from pruf.scoring import ML_ALONE_SCORE, score_track


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _features(text: str) -> set[str]:
    return {e.feature_id for e in find_features(normalize_text(text)) if e.weight > 0}


@pytest.mark.parametrize(("text", "feature"), [
    ("Вам начислено вознаграждение 180 000 ₸ по итогам года. Для вывода оплатите комиссию 2 900 ₸", "lottery.prize_fee"),
    ("Сізге 250 000 тг төлем тағайындалды. Рәсімдеу үшін нотариус қызметі 7 000 тг", "lottery.prize_fee"),
    ("Вы победили в эфире! Отправка Казпочтой, доставка за счёт победителя 3 000 тг", "lottery.prize_fee"),
    ("Мен 4 ай жобадамын, кредитті жаптым, ақша өзі жұмыс істейді", "pyramid.passive"),
    ("Закрыла ипотеку, теперь деньги работают сами — 5 месяцев в проекте", "pyramid.passive"),
    ("Вывод средств временно приостановлен. Для разблокировки внесите страховой платёж 15%", "pyramid.entry"),
    ("Приложение реально платит, вывела 18 000 за вечер. Скачать только apk, в Play Market его нет", "casino.money_game"),
    ("Бұрынғы сайт бұғатталды, жаңа айна сілтемеде, балансыңыз сақталған", "casino.mirror"),
    ("Бот для live-ставок на теннис, точность 90%", "casino.terms"),
])
def test_round9_patterns_fire(text: str, feature: str) -> None:
    # Act
    found = _features(text)

    # Assert
    assert feature in found, found


@pytest.mark.parametrize(("text", "track"), [
    ("Уважаемый клиент! Вам начислен кешбэк 95 000 ₸. Для возврата оплатите страховку перевода 1 900 ₸ на Kaspi +7 707 111 22 33", "lottery"),
    ("Переслано: вывод средств приостановлен. Для разблокировки внесите 20% от баланса. Пригласите 2 новых участников — комиссия обнуляется", "pyramid"),
])
def test_round9_scams_reach_medium(detector: Detector, text: str, track: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])
    assert analysis.track == track


@pytest.mark.parametrize("text", [
    "Схема «вы выиграли, заплатите налог»: мошенники звонят от имени банка и просят перевести 10% налога. Налог удерживает организатор",
    "Сотрудники банка никогда не звонят с просьбой продиктовать код из СМС. Если говорят, что вы выиграли — кладите трубку",
    "Скинули ссылку на «зеркало» сайта со ставками. Это вообще безопасно или там украдут данные карты?",
    "Регулятор предупреждает: компании с гарантированным доходом и бонусом за новых участников могут являться финансовыми пирамидами",
    "Жігіттер, кешке футбол, взнос 1500 за поле, Ерланға каспиге киньте",
    "Банк: вам начислен кешбэк 3 000 ₸ за покупки, он уже на карте",
])
def test_round9_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_confident_model_without_rules_reaches_medium_and_names_its_words(env) -> None:
    # Arrange: модель видела удвоение крипты, правил на «удваиваю» нет
    scam = ["удваиваю усдт за сутки отправляешь получаешь вдвое", "удваиваю крипту отправляешь сто получаешь двести"] * 20
    legit = ["кофейня открылась ждем гостей", "продаю велосипед в хорошем состоянии"] * 20
    clf = TrackClassifier.train(scam + legit, ["pyramid"] * len(scam) + ["legit"] * len(legit))
    detector = Detector(Settings(), classifier=clf)

    # Act
    analysis = _analyze(detector, "Удваиваю USDT: отправляешь 100, получаешь 200")

    # Assert
    assert analysis.level == "medium" and analysis.score == ML_ALONE_SCORE
    ml_note = next(e for e in analysis.evidence if e.source == "ml")
    assert "удваиваю" in ml_note.quote
    assert "ручная проверка" in analysis.summary


@pytest.mark.parametrize("text", [
    # ревью раунда 9: дешёвые «предупреждения» и отрицания не снимают просьбу автора
    "Вступительный взнос 20 000 тг, пассивный доход 30% в месяц. Никто не просит вас рисковать",
    "Вступительный взнос 20 000 тг, пассивный доход 30% в месяц. Безопасно ли это? Ответ: да",
    "Вступительный взнос 20 000 тг, пассивный доход 30% в месяц. Спросите себя: безопасно ли держать деньги в банке?",
    "Вы выиграли iPhone 15! Оплатите доставку 3 500 тг. Мошенники пишут от имени магазина, это мы настоящие",
    "Не покупайте билеты в киосках — оплатите участие 500 тг у нас и выиграйте iPhone 15",
    "Вы выиграли iPhone! У нас не крадут, оплатите доставку приза 2 500 тг на Kaspi +7 701 234 56 78",
])
def test_round9_review_evasions_keep_scams_in_queue(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


def test_theft_narration_does_not_hide_a_following_phishing_ask() -> None:
    # Act
    found = _features("Мошенники крадут данные карт — введите данные карты и CVV на сайте для защиты счета")

    # Assert
    assert "common.card_phish" in found


@pytest.mark.parametrize("text", [
    "Вам начислен кешбек 2 000 тг. Оплатите покупки картой Halyk и получите ещё 5% кешбэка, до 10 000 тг",
    "Проезд и проживание за счет победителя, примерно 30 000 тг",
    "Положение о турнире по шахматам: оплата участия 3000 тг, победителям кубки",
    "Скачал новую версию Minecraft apk, вывел fps на максимум, игра реально летает",
    "Розыгрыш среди подписчиков Казпочты, участие бесплатное, приз 50 000 тг",
])
def test_round9_review_false_positives_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_unrelated_track_stop_does_not_block_confident_model() -> None:
    # Arrange: «по лицензии» — стоп лотереи, к пирамиде отношения не имеет
    licence = Evidence("lottery.official", "lottery", "лицензия", -50, "text", stop=True)

    # Act
    result = score_track("pyramid", [licence], {"pyramid": 0.95, "legit": 0.05}, [])

    # Assert
    assert result.score == ML_ALONE_SCORE
