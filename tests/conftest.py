"""Общие фикстуры: изолированные настройки, детектор, синтетические скрины и OCR (один раз за сессию)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from pruf.config import Settings
from pruf.detect.detector import Detector
from pruf.normalize.ocr import OcrToken, run_ocr
from pruf.registry.hashing import open_image
from pruf.synth.screens import (
    Receipt,
    edit_amount,
    render_receipt,
    repost_variant,
    to_jpeg,
)
from tests.helpers import TEST_HMAC_KEY, make_settings

_ENV_TO_CLEAR = (
    "PRUF_ANALYST_TOKEN", "PRUF_BANK_TOKENS", "PRUF_BANK_ALLOW_ANALYST", "ANTHROPIC_API_KEY", "PRUF_RESOLVE_LINKS",
    "PRUF_MAX_UPLOAD_BYTES", "PRUF_RATE_LIMIT", "TELEGRAM_BOT_TOKEN", "PRUF_LLM_MODEL",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Чистое окружение: dev-режим, данные во временном каталоге, модели нет, LLM выключен."""
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PRUF_DEV_MODE", "1")
    monkeypatch.setenv("PRUF_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PRUF_HMAC_KEY", TEST_HMAC_KEY)
    monkeypatch.setenv("PRUF_MODEL_PATH", str(tmp_path / "no-model" / "clf.joblib"))
    return tmp_path


@pytest.fixture
def settings(env: Path) -> Settings:
    return Settings()



@pytest.fixture(scope="session")
def detector(tmp_path_factory: pytest.TempPathFactory) -> Detector:
    """Детектор только на правилах (без ML и LLM): общий на сессию, состояния не хранит."""
    return Detector(make_settings(tmp_path_factory.mktemp("det")))


@pytest.fixture(scope="session")
def receipt() -> Receipt:
    return Receipt(amount="150 000", sender="Айгерим С.", date="23.10.2026", time="14:35", receipt_no="QR 4821 7730 19")


@pytest.fixture(scope="session")
def original_jpeg(receipt: Receipt) -> bytes:
    return to_jpeg(render_receipt(receipt))


@pytest.fixture(scope="session")
def edited_jpeg(original_jpeg: bytes) -> bytes:
    """Копия с перерисованной суммой, обрезкой, масштабом и подписью другого канала."""
    return repost_variant(edit_amount(original_jpeg, "950 000"), random.Random(7), watermark="@channel2")


@pytest.fixture(scope="session")
def other_receipt_jpeg() -> bytes:
    """Другой чек того же шаблона: другие номер квитанции, дата и время."""
    other = Receipt(amount="80 000", sender="Ерлан Б.", date="02.09.2026", time="09:12", receipt_no="QR 1111 2222 33")
    return to_jpeg(render_receipt(other))


@pytest.fixture(scope="session")
def original_tokens(original_jpeg: bytes) -> list[OcrToken]:
    return run_ocr(open_image(original_jpeg))


@pytest.fixture(scope="session")
def edited_tokens(edited_jpeg: bytes) -> list[OcrToken]:
    return run_ocr(open_image(edited_jpeg))
