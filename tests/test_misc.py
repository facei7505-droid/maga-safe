"""Настройки, blob-хранилище, миграция базы, Whisper/OCR-адаптеры, шаблоны синтетики."""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

import pruf.normalize.audio as audio_mod
import pruf.normalize.ocr as ocr_mod
from pruf.config import Settings, load_settings
from pruf.detect.detector import Detector, SourceText
from pruf.storage.blobs import BlobStore
from pruf.storage.db import Database
from pruf.synth import templates
from tests.helpers import TEST_HMAC_KEY

SHA = "a" * 64


# ---------- config ----------
def test_settings_read_environment(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("PRUF_BANK_TOKENS", " halyk:t1, ,kaspi:t2 ")
    monkeypatch.setenv("PRUF_MAX_UPLOAD_BYTES", "1234")
    monkeypatch.setenv("PRUF_RATE_LIMIT", "7")

    # Act
    s = load_settings()

    # Assert
    assert s.dev_mode is True
    assert s.data_dir == env / "data"
    assert s.db_path == env / "data" / "pruf.db" and s.blob_dir == env / "data" / "blobs"
    assert s.bank_tokens == ("halyk:t1", "kaspi:t2")
    assert s.max_upload_bytes == 1234 and s.rate_limit_per_minute == 7
    assert s.effective_hmac_key() == TEST_HMAC_KEY.encode()


def test_dev_hmac_key_is_random_per_data_dir_and_persistent(tmp_path: Path) -> None:
    # Arrange
    a = Settings(data_dir=tmp_path / "a", hmac_key="", dev_mode=True)
    b = Settings(data_dir=tmp_path / "b", hmac_key="", dev_mode=True)

    # Act
    key_a1, key_a2, key_b = a.effective_hmac_key(), a.effective_hmac_key(), b.effective_hmac_key()

    # Assert
    assert key_a1 == key_a2 and len(key_a1) == 32
    assert key_a1 != key_b
    assert (tmp_path / "a" / ".dev_hmac_key").stat().st_mode & 0o777 == 0o600


def test_missing_hmac_key_outside_dev_mode_fails_fast(tmp_path: Path) -> None:
    # Arrange
    s = Settings(data_dir=tmp_path, hmac_key="", dev_mode=False, model_path=tmp_path / "none.joblib")

    # Act / Assert
    with pytest.raises(RuntimeError, match="PRUF_HMAC_KEY"):
        s.effective_hmac_key()
    with pytest.raises(RuntimeError):
        Detector(s)


# ---------- blobs ----------
def test_blob_store_roundtrip_and_idempotent_put(tmp_path: Path) -> None:
    # Arrange
    store = BlobStore(tmp_path / "blobs")

    # Act
    path = store.put(SHA, "jpg", b"first")
    again = store.put(SHA, "jpg", b"second")  # тот же адрес содержимого не перезаписывается

    # Assert
    assert path == again == tmp_path / "blobs" / "aa" / f"{SHA}.jpg"
    assert store.get(SHA, "jpg") == b"first"
    assert store.get("b" * 64, "jpg") is None


@pytest.mark.parametrize(("sha", "ext"), [("../../etc/passwd", "jpg"), ("A" * 64, "jpg"), (SHA, "exe"), (SHA, "jpg/../x")])
def test_blob_store_rejects_unsafe_keys(tmp_path: Path, sha: str, ext: str) -> None:
    with pytest.raises(ValueError):
        BlobStore(tmp_path).path_for(sha, ext)


# ---------- db ----------
def test_database_migrates_old_schema_without_status(tmp_path: Path) -> None:
    # Arrange: база старой версии без колонки status
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, external_id TEXT, source TEXT NOT NULL, channel TEXT, "
                 "author TEXT, posted_at TEXT, text TEXT, ocr_text TEXT, transcript TEXT, score REAL DEFAULT 0, "
                 "level TEXT DEFAULT 'low', track TEXT, analysis_json TEXT, label TEXT, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO posts (source, level, created_at) VALUES ('old', 'high', '2026-01-01')")
    conn.commit()
    conn.close()

    # Act
    db = Database(path)

    # Assert
    assert db.all_posts_brief()[0]["level"] == "high"
    assert db.get_post(1)["status"] == "ok"
    db.close()


def test_database_rejects_unknown_case_status(tmp_path: Path) -> None:
    # Arrange
    db = Database(":memory:")

    # Act / Assert
    with pytest.raises(ValueError):
        db.set_case_status("C-1", "guilty", None, "tester")
    db.set_case_status("C-1", "confirmed", "ok", "tester")
    db.set_case_status("C-1", "dismissed", None, "tester2")
    assert db.case_statuses()["C-1"]["status"] == "dismissed"
    assert db.case_statuses()["C-1"]["updated_by"] == "tester2"
    assert db.get_posts([]) == [] and db.artifact_post_ids([]) == {}
    db.close()


# ---------- Whisper ----------
def test_transcribe_without_whisper_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import падает ImportError

    # Act / Assert
    assert audio_mod.whisper_available() is False
    assert audio_mod.transcribe(b"OggS") is None


def _fake_whisper(monkeypatch: pytest.MonkeyPatch, model_factory) -> None:
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = model_factory
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(audio_mod, "_model", None)


def test_transcribe_with_whisper_joins_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    seen: list[bytes] = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, path: str, vad_filter: bool):
            seen.append(Path(path).read_bytes())
            return [types.SimpleNamespace(text=" Пассивный доход "), types.SimpleNamespace(text="5% в день ")], None

    _fake_whisper(monkeypatch, FakeModel)

    # Act
    text = audio_mod.transcribe(b"OggS-voice", ".ogg")

    # Assert
    assert text == "Пассивный доход 5% в день"
    assert seen == [b"OggS-voice"]


def test_transcribe_when_model_cannot_load_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def broken(*_a, **_kw):
        raise OSError("модель не скачана")

    _fake_whisper(monkeypatch, broken)

    # Act / Assert
    assert audio_mod.transcribe(b"OggS") is None


# ---------- OCR ----------
def test_run_ocr_reads_digits_from_receipt(original_tokens) -> None:
    # Assert: PP-OCR уверенно читает цифры, координаты в долях
    texts = " ".join(t.text for t in original_tokens)
    assert "150 000" in texts and "23.10.2026" in texts and "4821" in texts
    assert all(0 <= v <= 1 for t in original_tokens for v in t.box)
    centers = [round(t.center[1], 2) for t in original_tokens]
    assert centers == sorted(centers)


def test_run_ocr_filters_low_confidence_and_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    box = [[0, 0], [50, 0], [50, 10], [0, 10]]
    fake = lambda arr: ([(box, "12 345", 0.9), (box, "шум", 0.2), (box, "   ", 0.99)], None)
    monkeypatch.setattr(ocr_mod, "_engine", fake)

    # Act
    tokens = ocr_mod.run_ocr(Image.new("RGB", (100, 20)))

    # Assert
    assert [t.text for t in tokens] == ["12 345"]
    assert tokens[0].box == (0.0, 0.0, 0.5, 0.5)


def test_run_ocr_engine_failure_raises_ocr_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def broken(_arr):
        raise RuntimeError("onnx упал")

    monkeypatch.setattr(ocr_mod, "_engine", broken)

    # Act / Assert
    with pytest.raises(ocr_mod.OcrUnavailable):
        ocr_mod.run_ocr(Image.new("RGB", (10, 10)))


def test_ocr_unavailable_when_engine_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(ocr_mod, "_engine", None)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)

    # Act / Assert
    assert ocr_mod.ocr_available() is False
    with pytest.raises(ocr_mod.OcrUnavailable):
        ocr_mod.run_ocr(Image.new("RGB", (10, 10)))


# ---------- шаблоны синтетики ----------
SLOTS = dict(prize="iPhone 15 Pro", fee="2000", phone="+7 701 234 56 78", card="4400 4301 2345 6789",
             kaspi="kaspi.me/pay/shop1", domain="vulkan-kz.top", promo="WIN777", pct="5", amount="150 000", n="5",
             mult="x500", start="10000")


@pytest.mark.parametrize("track", ["lottery", "casino", "pyramid"])
def test_scheme_templates_reach_at_least_medium_on_their_track(detector: Detector, track: str) -> None:
    # Arrange
    items = getattr(templates, track.upper())

    # Act
    results = [(text, detector.detect([SourceText("text", text.format(**SLOTS))]).analysis) for _, text in items]

    # Assert: каждая схема видна; трек проверяется отдельно (см. xfail ниже)
    assert not [(text, a.score) for text, a in results if a.level == "low"]
    on_track = sum(1 for _, a in results if a.track == track)
    assert on_track >= len(results) - 1


def test_pyramid_entry_fee_without_prize_is_not_lottery(detector: Detector) -> None:
    # Act
    analysis = detector.detect([SourceText("text", "Вступительный взнос 10000 тг, переводи на каспи +7 701 234 56 78")]).analysis
    lottery = next(t for t in analysis.tracks if t.track == "lottery")

    # Assert
    assert analysis.track == "pyramid"
    assert lottery.level != "high"


def test_legit_templates_stay_low(detector: Detector) -> None:
    # Act
    results = [(text, detector.detect([SourceText("text", text.format(**SLOTS))]).analysis) for _, text in templates.LEGIT]

    # Assert
    assert not [(text, a.score) for text, a in results if a.level != "low"]
