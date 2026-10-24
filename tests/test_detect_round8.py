"""Раунд 8: пропуски жюри (сутки, круги дарения, инсайд из клуба, «ұшақ»), казахские предупреждения и складчины."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


@pytest.mark.parametrize(("text", "track"), [
    ("кидаешь 5к на каспи, через сутки возвращаю 7,5к. пиши +7 701 555 22 11", "pyramid"),
    ("закрыла третий круг 🌸 поставила 25, получила 200, лепестков осталось 4, кто с нами — пишите в лс", "pyramid"),
    ("инфа от человека из клуба, договорной экспресс на вечер, доступ 3к, пиши в лс", "casino"),
    ("Ұшақ ойынында 1.5 коэфтен ұстап тұрсаң болды, кеше 2 мыңнан 64 мың шығардым. Сілтеме профильде", "casino"),
    ("апа сіз ұттыңыз ғой теледидар, тек салығын төлеу керек 15 мың, каспиге жіберсеңіз", "lottery"),
    ("Telegram-задания: лайк басасың, пікір жазасың, 1000 тг за задание, но сначала депозит 10 000 тг", "pyramid"),
])
def test_round8_scam_patterns_reach_medium(detector: Detector, text: str, track: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (text, analysis.score, [e.feature_id for e in analysis.evidence])
    assert analysis.track == track


@pytest.mark.parametrize("text", [
    "Как отличить настоящий розыгрыш: нет платы за участие, победителю пишут с основного аккаунта, не просят код из СМС или CVV.",
    "Сыныптастар, мұғалімге сыйлық алайық, әр адамнан 5 000 тг, Айгүлге Каспи арқылы аударыңыздар. Чекті топқа саламыз.",
    "Жұмысқа шақырамыз: наубайшы керек, айлық 280 000 тг. Ешқандай алдын ала төлем жоқ.",
    "Ескерту: «Мына ойында ақша шығарамын, сілтеме директе» деген блогерлердің бәрі казино жарнамалайды. Сақ болыңыздар!",
    "Қыздар бұл алаяқтық па? Өзара көмек тобына шақырып жатыр 15 мың салсаң 120 мың аласың дейді",
    "Мектебімізде зияткерлік ойын өтеді, қатысу жарнасы 1000 тг, жеңімпаздарға кубок",
])
def test_round8_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (text, analysis.score, [e.feature_id for e in analysis.evidence])
