"""Проверка разметки человеком: слепая страница для эксперта и каппа Коэна против ИИ-разметки."""

from __future__ import annotations

import random

import pytest
from sklearn.metrics import cohen_kappa_score

from pruf.audit import Item, agreement, answer_key, cohen_kappa, labeling_page, stratified_sample

ITEMS = [Item(f"p{i}", f"текст поста номер {i}", label, "ru", "real_v9")
         for i, label in enumerate(["lottery", "casino", "pyramid", "legit"] * 30)]


def test_kappa_matches_sklearn() -> None:
    rng = random.Random(1)
    a = [rng.choice("abcd") for _ in range(200)]
    b = [x if rng.random() < 0.7 else rng.choice("abcd") for x in a]
    assert cohen_kappa(a, b) == pytest.approx(cohen_kappa_score(a, b))
    assert cohen_kappa(a, a) == 1.0


def test_sample_is_balanced_and_reproducible() -> None:
    sample = stratified_sample(ITEMS, 40, seed=3)
    assert len(sample) == 40
    assert {i.label for i in sample} == {"lottery", "casino", "pyramid", "legit"}
    assert all(sum(i.label == label for i in sample) == 10 for label in ("lottery", "casino", "pyramid", "legit"))
    assert sample == stratified_sample(ITEMS, 40, seed=3)


def test_page_is_blind() -> None:
    # Метка ИИ, набор и исходный id эксперту не видны: варианты ответа одинаковы у всех постов
    sample = stratified_sample(ITEMS, 8)
    page = labeling_page(sample, salt="s")
    assert "real_v9" not in page and 'data-id="p' not in page
    assert page.count('value="lottery"') == len(sample)
    assert "<script>" in page and "текст поста номер" in page


def test_page_escapes_post_text() -> None:
    page = labeling_page([Item("x", "<script>alert(1)</script>", "legit", "ru", "s")], salt="s")
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


def test_agreement_skips_unsure_and_lists_disagreements() -> None:
    # Arrange
    sample = stratified_sample(ITEMS, 8)
    key = answer_key(sample, salt="s")
    ids = list(key)
    answers = {bid: {"label": key[bid]["label"]} for bid in ids}
    answers[ids[0]] = {"label": "unsure"}
    wrong = next(b for b in ids[1:] if key[b]["label"] != "legit")
    answers[wrong] = {"label": "legit", "note": "похоже на обычную рекламу"}

    # Act
    result = agreement(answers, key)

    # Assert
    assert result.n == 7 and result.unsure == 1
    assert result.disagreements == [{"id": key[wrong]["id"], "source": "real_v9", "ai": key[wrong]["label"],
                                     "human": "legit", "note": "похоже на обычную рекламу"}]
    assert 0 < result.kappa_scam < 1 and result.agree_scam == pytest.approx(6 / 7, abs=1e-3)
