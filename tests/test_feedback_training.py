"""Дообучение на решениях аналитика: разметка из статусов кейсов и ворота «чемпион и претендент»."""

from __future__ import annotations

from pathlib import Path

import pytest

from pruf.detect.classifier import TrackClassifier
from pruf.detect.feedback_training import Labeled, analyst_rows, compare, in_holdout, train_challenger
from pruf.graph.builder import CaseGraph
from pruf.pipeline import Pruf, Submission
from pruf.synth.generator import Generator
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings

HONEST = "Розыгрыш среди подписчиков магазина! Участие бесплатное, подписка и репост. Вопросы +7 702 640 18 33"


@pytest.fixture(scope="module")
def synthetic() -> list[tuple[str, str]]:
    posts = Generator(seed=7).dataset(campaigns_per_track=3, posts_per_campaign=10, legit=120, image_rate=0.0)
    return [(p.text, p.label) for p in posts if p.split == "train"]


def test_analyst_rows_label_confirmed_by_track_and_dismissed_as_legit(tmp_path: Path) -> None:
    # Arrange
    core = Pruf(make_settings(tmp_path), ocr_enabled=False)
    scam = core.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), source="t", channel="@a"), allow_llm=False)
    honest = core.ingest(Submission(text=HONEST, source="t", channel="@b"), allow_llm=False)
    graph = CaseGraph(core.db)
    graph.ensure(core.version)
    core.db.set_case_status(graph.case_for_post(scam["post_id"]), "confirmed", None, "a")
    honest_case = graph.case_for_post(honest["post_id"])
    if honest_case:
        core.db.set_case_status(honest_case, "dismissed", None, "a")

    # Act
    rows = {r.post_id: r.label for r in analyst_rows(core.db, graph)}

    # Assert
    assert rows[scam["post_id"]] == "lottery"
    if honest_case:
        assert rows[honest["post_id"]] == "legit"
    core.db.close()


def test_holdout_split_is_stable() -> None:
    picks = [in_holdout(i) for i in range(400)]
    assert picks == [in_holdout(i) for i in range(400)]
    assert 60 < sum(picks) < 140  # около четверти


def test_poisoned_feedback_is_rejected(tmp_path: Path, synthetic) -> None:
    # Arrange: чемпион обучен честно. Аналитик ошибся на новых кампаниях (их нет в обучении) и пометил схемы
    # легальными; претендент учится на этих решениях. Проверка — на других постах тех же новых кампаний.
    champion = TrackClassifier.train(*zip(*synthetic))
    fresh = [(p.text, p.label) for p in Generator(seed=99).dataset(campaigns_per_track=3, posts_per_campaign=10,
                                                                     legit=0, image_rate=0.0) if p.label != "legit"]
    poisoned = [Labeled(i, t, "legit") for i, (t, _) in enumerate(fresh[::2])]
    holdout = [Labeled(1000 + i, t, label) for i, (t, label) in enumerate(fresh[1::2])]
    challenger = train_challenger(iter(synthetic), poisoned, dev_paths=[])

    # Act
    verdict = compare(make_settings(tmp_path), champion, challenger, holdout, dev_rows=synthetic[:200])

    # Assert: правила ловят знакомые схемы и без модели, но сама модель испорчена — замены нет
    assert not verdict.accept, verdict.reason
    assert verdict.challenger_ml_errors > verdict.champion_ml_errors


def test_honest_feedback_passes_the_gate(tmp_path: Path, synthetic) -> None:
    champion = TrackClassifier.train(*zip(*synthetic))
    feedback = [Labeled(i, t, label) for i, (t, label) in enumerate(synthetic[:80])]
    challenger = train_challenger(iter(synthetic), feedback, dev_paths=[])
    verdict = compare(make_settings(tmp_path), champion, challenger, feedback[60:], dev_rows=synthetic[:200])
    assert verdict.accept, verdict.reason


def test_first_model_is_accepted_without_comparison(tmp_path: Path, synthetic) -> None:
    challenger = TrackClassifier.train(*zip(*synthetic))
    assert compare(make_settings(tmp_path), None, challenger, [], []).accept
