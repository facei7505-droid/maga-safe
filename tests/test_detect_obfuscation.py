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
    assert "common.awareness" in _features(analysis)


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


# ---------- раунд 4: отрицание, пересказ, новости, сленг ----------
@pytest.mark.parametrize("text", [
    "Kaspi никогда не просит переводить деньги за выигрыш. Не переводите деньги незнакомцам!",
    "Мошенники проводят «розыгрыши» и просят оплатить доставку приза. Будьте внимательны",
    "Сыйлық үшін ешқашан ақша төлемеңіз, каспиге аудармаңыз!",
    "Расследование: как блогеры рекламируют казино под видом игр. Мы разобрали 20 аккаунтов — промокоды, фриспины, ссылки в шапке",
    "АРРФР выявило 15 финансовых пирамид: обещали 30% в месяц и платили за приглашённых",
    "Бір таныс «айына 40% пайда» беретін жобаға шақырып жатыр. Бұл қаржы пирамидасы ма?",
    "Фонд «Добро» проводит благотворительную лотерею по лицензии, билет 1000 тг",
])
def test_warnings_news_and_licensed_lotteries_stay_low(detector: Detector, text: str) -> None:
    assert _analyze(detector, text).level == "low", _analyze(detector, text).summary


@pytest.mark.parametrize(("text", "track"), [
    ("Гив на AirPods! Условия: подписка + донат 500тг на каспи 8 707 555 12 34", "lottery"),
    ("Продаю схему на Mines, 99% проходимость, работает на любом казике. Цена 15000тг", "casino"),
    ("Кешбэк-клуб: 15 000 теңгеге пакет сатып алып, күн сайын 700 теңге аласыз. Үш дос шақырсаңыз бонус", "pyramid"),
])
def test_slang_scams_reach_medium(detector: Detector, text: str, track: str) -> None:
    analysis = _analyze(detector, text)
    assert analysis.level in ("medium", "high") and analysis.track == track, (analysis.score, analysis.summary)


def test_scam_that_pretends_to_warn_but_gives_a_requisite_is_still_flagged(detector: Detector) -> None:
    # Arrange: «осторожно, мошенники» как маскировка, но с номером для оплаты участия
    text = "Осторожно, мошенники копируют наш канал! Настоящий розыгрыш iPhone только у нас: участие 1000 тг на каспи +7 701 234 56 78"

    # Act / Assert
    assert _analyze(detector, text).level in ("medium", "high")


def test_summary_names_cap_reason_and_legality_signs(detector: Detector) -> None:
    text = "Розыгрыш iPhone! Участие 2000 тг, переведи на каспи +7 701 234 56 78. Полные правила розыгрыша на сайте"
    summary = _analyze(detector, text).summary
    assert "признаки легальности" in summary and "Балл ограничен" in summary


def test_methodology_doc_lists_every_feature() -> None:
    import importlib.util
    from pathlib import Path

    from pruf.detect.lexicon import FEATURES
    path = Path(__file__).resolve().parent.parent / "scripts" / "methodology.py"
    spec = importlib.util.spec_from_file_location("methodology", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    doc = module.render()
    assert all(f"`{f.id}`" in doc for f in FEATURES)
    assert "low · 0" in doc and "high ·" in doc


# ---------- уклонения, найденные ревью: вопрос, «осторожно», кавычки, «не переживайте» ----------
@pytest.mark.parametrize(("text", "track"), [
    ('Это пирамида? Нет! Платформа платит каждый день 5%, пригласи 3 друзей и получай процент. Старт от 20 000 тг', 'pyramid'),
    ('Думаешь это лохотрон? Поднял 300к на лаки джет, ссылка в шапке профиля', 'casino'),
    ('Нужна рабочая схема? Авиатор, сигналы 100%, пиши в лс', 'casino'),
    ('Гарантированный доход 5% в день. Вход 20000 тг. Ваш банк никогда не даст столько!', 'pyramid'),
    ('Розыгрыш iPhone! Участие 500 тг. Внимание: остерегайтесь фейков, пиши только мне в лс', 'lottery'),
    ('Казино лаки джет, поднял 500к. Подпольные казино — зло, а это легальный сайт, ссылка в профиле', 'casino'),
    ('Вы выиграли приз! Чтобы получить, не переживайте, переведите 2000 на каспи', 'lottery'),
    ('Осторожно, мошенники! Наш «Розыгрыш iPhone, участие 500 тг, переведи на каспи» единственный настоящий. Каспи 87011234567', 'lottery'),
])
def test_fake_warnings_and_quotes_do_not_hide_a_scam(detector: Detector, text: str, track: str) -> None:
    analysis = _analyze(detector, text)
    assert analysis.level in ("medium", "high") and analysis.track == track, (analysis.score, analysis.summary)


@pytest.mark.parametrize("text", ["схем" * 5000, "1" * 20000, "приз " * 4000, "не " * 6000, "«" + "через " * 3000],
                         ids=["word-run", "digit-run", "prize-run", "negation-run", "open-quote"])
def test_adversarial_long_posts_are_processed_quickly(detector: Detector, text: str) -> None:
    import time
    started = time.perf_counter()
    _analyze(detector, text)
    assert time.perf_counter() - started < 1.5
