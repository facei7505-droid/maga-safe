"""Правила по трекам (ru/kk/translit), легальные контрольные примеры и логика итогового балла."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.detect.lexicon import FEATURES, TRACKS, features_by_track
from pruf.detect.rules import find_features
from pruf.models import HIGH_THRESHOLD, MEDIUM_THRESHOLD, Evidence, level_for
from pruf.normalize.text import normalize_text
from pruf.scoring import (
    ML_ONLY_CAP,
    NO_COMBO_CAP,
    STOP_CAP,
    combine,
    score_track,
    summarize,
)

PHONE = "+7 701 234 56 78"

POSITIVES = [
    ("lottery", "ru", f"🎁 РОЗЫГРЫШ iPhone 15 Pro! Участие всего 2000 тг, переводите на Kaspi {PHONE}. Итоги в пятницу!"),
    ("lottery", "kk", f"Ұтыс ойыны! iPhone 15 ұтып алыңыз. Қатысу 1000 теңге, каспиге аударыңыз {PHONE}. Жеңімпаз жұмада"),
    ("lottery", "translit", f"Rozygrysh iPhone 15! Uchastie 2000 tg, perevod na kaspi {PHONE}. Pishi v lichku posle oplaty"),
    ("casino", "ru", "Рабочее зеркало vulkan-kz.top — без блокировок! Бонус на депозит 200% и 100 фриспинов по промокоду WIN777"),
    ("casino", "kk", "Казино зеркало azino-kz.club жұмыс істейді, блоксыз. Тіркел де бонус ал, сайт директке жазамын"),
    ("casino", "translit", "Kazino zerkalo rabochee pinup-win.site, bonus na depozit 200%, pishi v lichku"),
    ("pyramid", "ru", "Пассивный доход от 5% в день! Пригласи 3 друзей и получай бонус с каждого. Вход от 10000 тг, пиши в лс"),
    ("pyramid", "kk", f"Күніне 5% табыс! Достарыңды шақыр, әр адамнан бонус. Кіру жарнасы 5000 теңге, каспиге аудар {PHONE}"),
    ("pyramid", "translit", f"Passivnyi dohod 5% v den! Priglasi druzei i poluchai bonus. Vhod ot 5000 tg, kaspi {PHONE}"),
]

LEGAL_CONTROLS = [
    ("free_giveaway_ru", "Розыгрыш от нашей кофейни! Подпишись, отметь друга в комментариях. Участие бесплатное, правила розыгрыша в закрепе"),
    ("free_giveaway_kk", "Ұтыс ойыны! Парақшаға жазылыңыз, досыңызды белгілеңіз. Қатысу тегін, ережесі закрепте"),
    ("free_giveaway_translit", "Rozygrysh ot magazina, uchastie besplatnoe, nichego platit ne nuzhno. Pravila rozygrysha v profile"),
    ("anti_fraud_ru", "Осторожно, мошенники! Обещают 3% в день и просят приглашать друзей — это признаки пирамиды. Не ведитесь"),
    ("anti_fraud_kk", "Абай болыңыз, алаяқтардан сақ болыңыз! Күніне 5% табыс уәде етсе, бұл қаржы пирамидасы"),
    ("anti_gambling_regulator", "АРРФР предупреждает: незаконные онлайн-казино блокируются, лудомания разрушает семьи. Помощь зависимым по номеру 111"),
    ("anti_gambling_news", "Новости: в Шымкенте задержали организаторов незаконного казино, сайт заблокирован"),
    ("personal_transfer_ru", "Скинь на каспи за обед 2500 тг, я вчера платил 😄"),
    ("personal_transfer_translit", "Skin na kaspi za taksi 1500 tg pozhaluista"),
    ("bank_deposit", "Депозит в банке под 14% годовых, вклад застрахован КФГД. Подробности в отделении"),
    ("sale", "Скидка 20% на всё меню до конца недели. Оплата картой или Kaspi QR"),
]


def _analyze(detector: Detector, text: str):
    return detector.detect([SourceText("text", text)]).analysis


# ---------- позитивные примеры ----------
@pytest.mark.parametrize(("track", "lang", "text"), POSITIVES, ids=[f"{t}-{lang}" for t, lang, _ in POSITIVES])
def test_scheme_posts_get_high_risk_on_their_track(detector: Detector, track: str, lang: str, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.track == track
    assert analysis.level == "high"
    assert analysis.score >= HIGH_THRESHOLD
    assert any(e.track == track and e.core for e in analysis.evidence)
    assert "Решение принимает аналитик" in analysis.summary


@pytest.mark.parametrize(("track", "lang", "text"), POSITIVES, ids=[f"{t}-{lang}" for t, lang, _ in POSITIVES])
def test_every_quote_is_a_verbatim_fragment_of_the_original(detector: Detector, track: str, lang: str, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    text_evidence = [e for e in analysis.evidence if e.source == "text" and e.span]
    assert text_evidence
    for ev in text_evidence:
        assert ev.quote and ev.quote in text
        start, end = ev.span
        assert text[start:end].lower() in ev.quote.lower()


# ---------- легальные контрольные примеры ----------
@pytest.mark.parametrize(("name", "text"), LEGAL_CONTROLS, ids=[n for n, _ in LEGAL_CONTROLS])
def test_legal_controls_stay_low(detector: Detector, name: str, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (name, analysis.score, [e.feature_id for e in analysis.evidence])
    assert analysis.track is None
    assert analysis.summary.startswith("Существенных признаков схем не найдено")


def test_free_giveaway_summary_lists_legality_signs(detector: Detector) -> None:
    # Act
    analysis = _analyze(detector, LEGAL_CONTROLS[0][1])

    # Assert
    assert "признаки легальности" in analysis.summary
    assert any(e.stop for e in analysis.evidence)


# ---------- обязательное сочетание и стоп-признаки ----------
def test_single_core_feature_without_transfer_is_capped_below_high(detector: Detector) -> None:
    # Arrange: только «приз» (ядро) + усилители, без взноса и без просьбы перевести деньги
    text = "Розыгрыш айфона! Каждый выигрывает! Срочно, пиши в лс, пруфы выплат"

    # Act
    analysis = _analyze(detector, text)
    lottery = next(t for t in analysis.tracks if t.track == "lottery")

    # Assert
    assert lottery.score == NO_COMBO_CAP
    assert lottery.level == "medium"
    assert lottery.capped_reason == "нет обязательного сочетания признаков для высокого риска"


def test_stop_feature_caps_track_at_medium(detector: Detector) -> None:
    # Arrange: платное участие, но упомянут организатор (стоп-признак легальности)
    text = "Розыгрыш iPhone! Участие 2000 тг, переводи на каспи. Организатор магазин Береке"

    # Act
    analysis = _analyze(detector, text)
    lottery = next(t for t in analysis.tracks if t.track == "lottery")

    # Assert
    assert lottery.score <= STOP_CAP
    assert lottery.capped_reason == "есть признаки легальности"


def test_prize_without_fee_is_not_high(detector: Detector) -> None:
    analysis = _analyze(detector, "Розыгрыш iPhone! Выиграй приз")
    assert analysis.level != "high"


# ---------- rules.find_features ----------
def test_find_features_on_empty_text_returns_nothing() -> None:
    assert find_features(normalize_text("   ")) == []


def test_find_features_limits_quotes_per_feature() -> None:
    # Arrange: «казино» встречается пять раз
    norm = normalize_text("казино. казино. казино. казино. казино.")

    # Act
    hits = [e for e in find_features(norm, "ocr") if e.feature_id == "casino.terms"]

    # Assert
    assert len(hits) == 2
    assert all(e.source == "ocr" for e in hits)


def test_find_features_quotes_original_obfuscated_spelling() -> None:
    # Arrange
    norm = normalize_text("Р0ЗЫГРЫШ сегодня")

    # Act
    prize = next(e for e in find_features(norm) if e.feature_id == "lottery.prize")

    # Assert
    assert "Р0ЗЫГРЫШ" in prize.quote


def test_lexicon_is_consistent() -> None:
    # Assert
    assert len({f.id for f in FEATURES}) == len(FEATURES)
    for f in FEATURES:
        assert f.track in TRACKS + ("common",)
        assert f.compiled()
        assert (f.weight < 0) == f.stop
    for track in TRACKS:
        assert any(f.core for f in features_by_track(track))


# ---------- scoring (синтетические признаки, не зависят от словаря) ----------
def ev(fid: str, track: str, weight: float, *, core: bool = False, stop: bool = False, source: str = "text") -> Evidence:
    return Evidence(fid, track, fid, weight, source, core=core, stop=stop)


def test_level_thresholds() -> None:
    assert level_for(MEDIUM_THRESHOLD - 0.1) == "low"
    assert level_for(MEDIUM_THRESHOLD) == "medium"
    assert level_for(HIGH_THRESHOLD - 0.1) == "medium"
    assert level_for(HIGH_THRESHOLD) == "high"


def test_common_features_count_only_with_own_positive_feature() -> None:
    # Arrange
    common = [ev("common.kaspi_transfer", "common", 14), ev("common.urgency", "common", 6)]

    # Act
    without_own = score_track("lottery", common, None, [])
    with_own = score_track("lottery", common + [ev("lottery.prize", "lottery", 14, core=True)], None, [])

    # Assert
    assert without_own.score == 0 and without_own.rule_points == 0
    assert with_own.rule_points == 34


def test_each_feature_counts_once() -> None:
    # Arrange
    twice = [ev("lottery.prize", "lottery", 14, core=True), ev("lottery.prize", "lottery", 14, core=True)]

    # Act
    result = score_track("lottery", twice, None, [])

    # Assert
    assert result.rule_points == 14


def test_two_core_features_allow_high() -> None:
    # Arrange
    evidence = [ev("lottery.prize", "lottery", 30, core=True), ev("lottery.entry_fee", "lottery", 30, core=True)]

    # Act
    result = score_track("lottery", evidence, None, [])

    # Assert
    assert result.level == "high" and result.capped_reason is None


def test_core_plus_transfer_allows_high() -> None:
    # Arrange
    evidence = [ev("lottery.entry_fee", "lottery", 40, core=True), ev("common.kaspi_transfer", "common", 14),
                ev("lottery.big_prize", "lottery", 20)]

    # Act
    result = score_track("lottery", evidence, None, [])

    # Assert
    assert result.level == "high" and result.capped_reason is None


def test_ml_raises_score_when_track_has_features() -> None:
    # Arrange
    evidence = [ev("casino.terms", "casino", 10, core=True), ev("casino.bonus", "casino", 10)]

    # Act
    rules_only = score_track("casino", evidence, None, [])
    blended = score_track("casino", evidence, {"casino": 1.0, "legit": 0.0}, [])
    low_ml = score_track("casino", evidence, {"casino": 0.0, "legit": 1.0}, [])

    # Assert
    assert blended.score > rules_only.score
    assert blended.ml_probability == 1.0
    assert low_ml.score >= rules_only.score  # модель может только поднять балл


def test_single_isolated_feature_stays_low() -> None:
    # Act
    result = score_track("casino", [ev("casino.terms", "casino", 60, core=True)], None, [])

    # Assert
    assert result.level == "low"
    assert result.capped_reason is not None


def test_context_without_own_features_cannot_reach_high() -> None:
    # Arrange
    context = [ev("registry.reused_proof", "pyramid", 40, source="registry"),
               ev("graph.requisite.phone", "pyramid", 40, source="graph")]

    # Act
    result = score_track("pyramid", [], None, context)

    # Assert
    assert result.level == "medium"


def test_ml_alone_stays_below_medium() -> None:
    # Act
    result = score_track("pyramid", [], {"pyramid": 0.99, "legit": 0.01}, [])

    # Assert: модель без признаков не ставит пост в очередь аналитика
    assert result.score == ML_ONLY_CAP
    assert result.level == "low"


def test_strong_own_context_counts_without_text_features() -> None:
    # Arrange: повтор пруфа из рискованных постов того же трека
    context = [ev("registry.reused_proof", "pyramid", 20, source="registry")]

    # Act
    result = score_track("pyramid", [], None, context)

    # Assert
    assert result.score == 20


def test_weak_or_common_context_alone_is_not_risk() -> None:
    # Arrange: «повтор сам по себе не риск»
    weak_own = [ev("registry.text_template", "pyramid", 10, source="registry")]
    strong_common = [ev("registry.edited_digits", "common", 20, source="registry")]

    # Act
    weak = score_track("pyramid", [], None, weak_own)
    common_only = score_track("pyramid", [], None, strong_common)

    # Assert
    assert weak.score == 0
    assert common_only.score == 0


def test_context_adds_to_track_with_text_features_and_is_clamped() -> None:
    # Arrange
    evidence = [ev("pyramid.referral", "pyramid", 60, core=True), ev("pyramid.entry", "pyramid", 60, core=True)]
    context = [ev("registry.reused_proof", "pyramid", 20, source="registry"),
               ev("registry.edited_digits", "common", 20, source="registry")]

    # Act
    result = score_track("pyramid", evidence, None, context)

    # Assert
    assert result.score == 100.0


def test_negative_points_floor_at_zero() -> None:
    result = score_track("casino", [ev("casino.awareness", "casino", -35, stop=True)], None, [])
    assert result.score == 0 and result.level == "low"


def test_combine_picks_top_track_and_filters_evidence() -> None:
    # Arrange
    evidence = [ev("casino.terms", "casino", 30, core=True), ev("casino.mirror", "casino", 30, core=True),
                ev("lottery.prize", "lottery", 5, core=True), ev("pyramid.bank_product", "pyramid", -35, stop=True)]

    # Act
    analysis = combine(evidence, requisites=({"kind": "phone"},), links=({"url": "x"},))

    # Assert
    assert analysis.track == "casino"
    ids = [e.feature_id for e in analysis.evidence]
    assert "lottery.prize" not in ids
    assert "pyramid.bank_product" in ids  # стоп-признаки показываются всегда
    assert ids[0] == "pyramid.bank_product"  # сортировка по |весу|
    data = analysis.to_dict()
    assert data["level_label"] == "высокий"
    assert data["requisites"] == ({"kind": "phone"},) or data["requisites"] == [{"kind": "phone"}]


def test_summarize_low_without_stop_features() -> None:
    assert summarize("low", None, []) == "Существенных признаков схем не найдено."


def test_warning_on_one_track_caps_every_track_without_money_request_or_contact() -> None:
    # Arrange: расследование о казино: новостная рамка без реквизита и ссылки
    evidence = [ev("casino.terms", "casino", 40, core=True), ev("casino.mirror", "casino", 40, core=True),
                ev("casino.bonus", "casino", 30), ev("common.news.awareness", "common", -45, stop=True),
                ev("common.news.awareness", "common", -45, stop=True)]

    # Act
    analysis = combine(evidence)

    # Assert
    casino = next(t for t in analysis.tracks if t.track == "casino")
    assert analysis.level == "low"
    assert casino.capped_reason == "похоже на предупреждение или новость о схеме"


def test_single_news_word_in_an_ad_does_not_drop_it_to_low() -> None:
    # Arrange: «Сотында бәрі дәлелденді» дописано к рекламе с двумя ядровыми признаками
    evidence = [ev("pyramid.entry", "pyramid", 22, core=True), ev("pyramid.high_return", "pyramid", 24, core=True),
                ev("pyramid.referral", "pyramid", 26, core=True), ev("common.news.awareness", "common", -45, stop=True)]

    # Act
    analysis = combine(evidence)

    # Assert
    assert analysis.level != "low"
    assert analysis.track == "pyramid"


def test_warning_with_requisite_keeps_medium_cap_only() -> None:
    # Arrange: «осторожно, мошенники» в рекламе с номером для перевода остаётся в очереди
    evidence = [ev("casino.terms", "casino", 22, core=True), ev("casino.mirror", "casino", 22, core=True),
                ev("casino.bonus", "casino", 16), ev("common.requisite", "common", 6),
                ev("casino.awareness", "casino", -45, stop=True)]

    # Act / Assert
    assert combine(evidence).level == "medium"


def test_casino_specific_awareness_does_not_cap_other_tracks() -> None:
    # Arrange: «подпольные казино — зло» в посте с платным розыгрышем
    evidence = [ev("lottery.prize", "lottery", 14, core=True), ev("lottery.entry_fee", "lottery", 30, core=True),
                ev("common.kaspi_transfer", "common", 14), ev("casino.awareness", "casino", -45, stop=True)]

    # Act / Assert
    assert combine(evidence).track == "lottery" and combine(evidence).level == "high"
