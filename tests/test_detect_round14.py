"""Раунд 14: рассказы пострадавших («не платила, заблокировала номер»), оплата по Kaspi QR, вакансии.
Ложные тревоги слепого v15; новые формулировки ниже написаны заново, а не скопированы из набора."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


def _ids(analysis: Analysis) -> list[str]:
    return [e.feature_id for e in analysis.evidence]


@pytest.mark.parametrize("text", [
    # пересказ рассылки с цитатой «оплатите» и отказ от первого лица
    "Пришло смс: «вы выиграли 2 млн, оплатите налог 20 000 тг». Я ничего не платила и заблокировала номер, берегитесь!",
    "Мне звонили «из банка», сказали что я выиграла машину и надо перевести страховку на карту. Бросила трубку.",
    "Vchera napisali chto ya vyigral iphone, prosili oplatit dostavku 5000. Ya zablokiroval ih, beregites",
    "Маған хабарлама келді: сіз ұтыс ұттыңыз, жеткізу ақысын төлеңіз 6000 теңге. Мен ештеңе төлеген жоқпын, блокқа салдым",
    "Коллега звал в «клуб инвесторов», 4% в день и бонус за каждого приглашённого. Я отказался, это обычная пирамида.",
])
def test_victim_stories_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, _ids(analysis))
    assert "common.victim.awareness" in _ids(analysis)


@pytest.mark.parametrize("text", [
    # «отзыв» в рекламе: автор якобы не платил, но тут же даёт номер или ссылку — маскировка
    "Я тоже сначала думала что развод и ничего не платила, а потом вывела 50 000 за неделю! Пиши мне +7 701 555 12 34",
    "Заблокировала номер старой компании и перешла к нам: доход 5% в день, вход 10 000 тг на Kaspi +7 707 111 22 33",
    "Мен ештеңе төлеген жоқпын, алаяқ емес! 300 000 ұтып алдым. Сен де қатыс, жарна 2000 тг, каспи 87011234567",
    # «это не пирамида» в рекламе по-прежнему не предупреждение
    "Это не пирамида, а клуб взаимопомощи: вход 20 000 тг, через 10 дней х2, приведи двоих друзей. Каспи +7 747 000 11 22",
])
def test_fake_victim_stories_with_contacts_stay_risky(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, _ids(analysis))


@pytest.mark.parametrize("text", [
    "Курс английского для детей, 12 занятий — 24 000 тг. Участие в пробном уроке бесплатно, оплата по Kaspi QR в школе.",
    "Йога-марафон 14 дней, участие 7 500 ₸. Оплата Kaspi QR, чек на почту. Похудение не гарантируем, всё зависит от вас.",
    "Шахмат үйірмесі, ай сайын 12 000 тг, оплата по Kaspi QR на ресепшене.",
    "Наурыз тойына тегін ұтыс! Жүлде — дастарқан жиынтығы. Жеңімпаздардан жеткізу ақысы алынбайды, тек жазылу мен репост.",
])
def test_paid_services_and_free_giveaways_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, _ids(analysis))


def test_kaspi_qr_does_not_hide_a_paid_raffle(detector: Detector) -> None:
    # Arrange: платный розыгрыш остаётся розыгрышем, даже если оплата через QR
    text = "РОЗЫГРЫШ iPhone 15! Участие 2 000 тг, оплата по Kaspi QR. Итоги в пятницу, осталось 7 мест"

    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, _ids(analysis))
    assert analysis.track == "lottery"


def test_kaspi_qr_is_not_a_transfer_request(detector: Detector) -> None:
    ids = _ids(_analyze(detector, "Оплата по Kaspi QR на кассе, доставка по городу бесплатно"))
    assert "common.kaspi_transfer" not in ids
    assert "common.kaspi_transfer" in _ids(_analyze(detector, "Оплата на каспи 87011234567, после перевода скиньте чек"))


def test_job_offer_with_monthly_salary_is_marked_legal(detector: Detector) -> None:
    analysis = _analyze(detector, "Нужен продавец-консультант, график 2/2, оклад 250 000 тг в месяц, официальное трудоустройство")
    assert "pyramid.job_offer" in _ids(analysis)
    assert analysis.level == "low", (analysis.score, _ids(analysis))
