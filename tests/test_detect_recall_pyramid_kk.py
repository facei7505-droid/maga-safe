"""Полнота по пирамидам и казахскому: удвоение денег, «работа с заданиями», «вывод заморожен», лжеюристы,
«взнос вернётся», казахская плата за приз и фальшивые госвыплаты. Тексты написаны заново, не из наборов."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _ids(analysis: Analysis) -> list[str]:
    return [e.feature_id for e in analysis.evidence]


@pytest.mark.parametrize("text, feature", [
    ("Скинешь 15 000 — завтра получишь 30 000. Проверено, отзывы в сторис", "pyramid.doubling"),
    ("Удвою вашу сумму за сутки, работаю через биржу, минимум 10к", "pyramid.doubling"),
    ("Жіберсең 20 TON, ертең 40 TON қайтарамын. Тек бүгін!", "pyramid.doubling"),
    ("Оценивай товары на маркетплейсе, 400 тг за отзыв. Чтобы открыть VIP-задания, пополни рабочий счёт на 12 000", "pyramid.task_scam"),
    ("Тапсырма: видеоға лайк басу, әр тапсырмаға 300 тг. Жұмыс шотын 5 000 тг толтырсаң, премиум-тапсырма ашылады", "pyramid.task_scam"),
    ("Ваш вывод 4 100 USDT временно заблокирован. Для вывода необходимо внести 15% страхового депозита", "pyramid.frozen_withdrawal"),
    ("Шотыңыздағы 1 200 000 ₸ уақытша бұғатталды. Верификация төлемі 10%, 24 сағат ішінде", "pyramid.frozen_withdrawal"),
    ("Потеряли деньги на фейковой бирже? Наша компания вернёт до 95% через арбитраж, предоплата 12%", "pyramid.recovery"),
    ("В команду нужны 3 человека, доход от 400к в месяц, стартовый взнос отбивается за неделю. Это не МЛМ", "pyramid.payback"),
])
def test_scheme_types_are_recognized_and_risky(detector: Detector, text: str, feature: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert feature in _ids(analysis), _ids(analysis)
    assert analysis.level in ("medium", "high"), (analysis.score, _ids(analysis))


@pytest.mark.parametrize("text", [
    "Сіз «Жаз сыйлығы» ұтыс ойынының жеңімпазысыз! Жүлде — тоңазытқыш. Жеткізу ақысы 4 500 ₸, төлегеннен кейін жібереміз",
    "Құттықтаймыз, сіздің нөміріңіз жүлде ұтты. Сақтандыру ақысы 6 000 теңге алдын ала",
    "Мемлекеттік төлем: әр азаматқа 60 000 теңге! Алу үшін 1 500 тг қызмет ақысын төлеу керек",
    "Зейнеткерлерге 40 000 тг бір реттік көмек. Тізімге енгізу үшін 800 тг аударасыз",
])
def test_kazakh_prize_fees_and_fake_payouts_are_risky(detector: Detector, text: str) -> None:
    analysis = _analyze(detector, text)
    assert analysis.level in ("medium", "high"), (analysis.score, _ids(analysis))


@pytest.mark.parametrize("text", [
    # банковские акции и настоящие вакансии
    "Двойной кешбэк x2 по карте в продуктовых до конца месяца, условия в приложении банка",
    "Удвоим бонусы за покупки в выходные! Баллы начисляются автоматически",
    "Ищем модератора отзывов в интернет-магазин, оклад 250 000 тг, официальное трудоустройство, график 5/2",
    "Ваша посылка задержана на таможне, свяжитесь со службой поддержки по номеру на сайте перевозчика",
    # новости и предупреждения, цитирующие схему
    "Полиция Алматы задержала организаторов «удвоения USDT»: пострадавшие перевели им более 30 млн тенге",
    "Если обещают удвоить деньги за сутки — это мошенничество. Не переводите и сообщите в полицию",
    # вопрос о чужом предложении с казахской косвенной речью
    "Көршім бір топқа шақырады, 30 мың салсаң 60 мың қайтарамын дейді. Сенуге бола ма? Кім біледі?",
    # честный розыгрыш по-казахски
    "Тегін ұтыс! Жеңімпазға жүлде — сертификат. Жеткізу ақысы алынбайды, тек жазылу мен репост",
])
def test_legit_posts_stay_low(detector: Detector, text: str) -> None:
    analysis = _analyze(detector, text)
    assert analysis.level == "low", (analysis.score, _ids(analysis))
