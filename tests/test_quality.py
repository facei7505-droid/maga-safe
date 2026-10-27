"""Карточка «Как мы мерили»: цифры совпадают с README, модель для прода узнаётся по хэшу."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.config import ROOT
from pruf.detect.prod_model import MODEL_FILE, PROD_DIR
from pruf.quality import QUALITY, model_info
from tests.helpers import make_settings


def _ru(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def test_dashboard_numbers_match_the_readme_table() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    main, no_real, rules = QUALITY["rows"]
    assert f"**{_ru(main['precision'], 2)}** | **{_ru(main['recall'], 2)}** | **{_ru(main['fpr'], 3)}**" in readme
    for row in (no_real, rules):
        assert f"| {_ru(row['precision'], 2)} | {_ru(row['recall'], 2)} | {_ru(row['fpr'], 3)} |" in readme
    assert f"**{QUALITY['set']}** ({QUALITY['posts']} постов, {QUALITY['channels']} новых канала)" in readme


def test_prod_model_is_recognised_by_its_hash(tmp_path: Path) -> None:
    # Arrange
    copy = tmp_path / "clf.joblib"
    shutil.copy(PROD_DIR / MODEL_FILE, copy)
    other = tmp_path / "other.joblib"
    other.write_bytes(b"not the prod model")

    # Act + Assert
    info = model_info(copy)
    assert info["prod"] is True and info["real_posts"] == 1639
    assert model_info(other)["prod"] is False
    assert model_info(tmp_path / "missing.joblib") == {"prod": False, "real_posts": 0, "trained_at": None}


def test_stats_carry_the_quality_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with TestClient(create_app(make_settings(tmp_path))) as client:
        quality = client.get("/api/v1/stats").json()["data"]["quality"]
    assert quality["set"] == "real_v4" and quality["rows"][0]["main"] is True
    assert quality["model"]["prod"] is False  # в тестах модели для прода нет
