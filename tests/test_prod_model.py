"""Модель для прода: публикуется только со всеми наборами, ставится только с верным хэшем и версией scikit-learn."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pruf.detect import prod_model
from pruf.detect.classifier import TrackClassifier
from pruf.detect.training import DEV_SETS

TEXTS = ["розыгрыш айфона участие 2000 тг", "доход 5% в день приведи друга", "казино бонус промокод слоты",
         "встреча выпускников в субботу"] * 3
LABELS = ["lottery", "pyramid", "casino", "legit"] * 3


@pytest.fixture
def clf() -> TrackClassifier:
    return TrackClassifier.train(TEXTS, LABELS)


def _eval_dir(tmp_path: Path, skip: str | None = None) -> Path:
    d = tmp_path / "eval"
    d.mkdir()
    for name in DEV_SETS:
        if name != skip:
            (d / f"{name}.jsonl").write_text(json.dumps({"text": "пост", "label": "legit"}) + "\n", encoding="utf-8")
    return d


def test_publish_refuses_without_real_posts(tmp_path: Path, clf: TrackClassifier) -> None:
    eval_dir = _eval_dir(tmp_path, skip="real_v1")
    with pytest.raises(ValueError, match="real_v1"):
        prod_model.publish(clf, 10, eval_dir, tmp_path / "prod")
    assert not (tmp_path / "prod" / prod_model.MODEL_FILE).exists()


def test_publish_then_install(tmp_path: Path, clf: TrackClassifier) -> None:
    # Arrange
    out = tmp_path / "prod"
    manifest = prod_model.publish(clf, 10, _eval_dir(tmp_path), out)
    target = tmp_path / "app" / "clf.joblib"

    # Act
    result = prod_model.install(target, out)

    # Assert
    real_sets = [n for n in DEV_SETS if n.startswith("real_")]
    assert manifest["real_posts"] == len(real_sets) and manifest["sets"]["real_v1"] == 1
    assert result.installed, result.reason
    assert TrackClassifier.load(target) is not None


def test_install_rejects_tampered_model(tmp_path: Path, clf: TrackClassifier) -> None:
    out = tmp_path / "prod"
    prod_model.publish(clf, 10, _eval_dir(tmp_path), out)
    with (out / prod_model.MODEL_FILE).open("ab") as f:
        f.write(b"x")
    result = prod_model.install(tmp_path / "clf.joblib", out)
    assert not result.installed and "SHA-256" in result.reason
    assert not (tmp_path / "clf.joblib").exists()


def test_install_rejects_other_sklearn_version(tmp_path: Path, clf: TrackClassifier) -> None:
    out = tmp_path / "prod"
    prod_model.publish(clf, 10, _eval_dir(tmp_path), out)
    manifest = json.loads((out / prod_model.MANIFEST_FILE).read_text())
    (out / prod_model.MANIFEST_FILE).write_text(json.dumps({**manifest, "sklearn": "0.24.2"}))
    result = prod_model.install(tmp_path / "clf.joblib", out)
    assert not result.installed and "0.24.2" in result.reason


def test_install_without_published_model(tmp_path: Path) -> None:
    result = prod_model.install(tmp_path / "clf.joblib", tmp_path / "nothing")
    assert not result.installed and result.reason == "опубликованной модели нет"
