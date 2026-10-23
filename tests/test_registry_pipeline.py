"""ProofRegistry на временной базе и сквозной приём постов через Pruf."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import pruf.registry.registry as registry_mod
from pruf.normalize.ocr import OcrToken, OcrUnavailable
from pruf.normalize.text import normalize_text
from pruf.pipeline import Pruf, Submission, Upload
from pruf.registry.forensics import TokenAnomaly
from pruf.registry.index import _MERGE_EVERY
from pruf.registry.registry import ProofRegistry, strong_tokens
from pruf.storage.blobs import BlobStore
from pruf.storage.db import Database
from tests.helpers import CASINO_RU, KASPI_PHONE, LOTTERY_RU, PYRAMID_RU, make_settings

PYRAMID_PROOF_TEXT = "Вот пруф выплаты 👆 Уже вывел 150 000 тг. Пассивный доход 5% в день, вступительный взнос 5000 тг, пиши в лс"
PYRAMID_REPOST_TEXT = "Пассивный доход от 5% в день! Пригласи друзей. Вход от 10000 тг, пиши в лс"
FAKE_TOKENS = [
    OcrToken("+150 000 T", (0.1, 0.3, 0.8, 0.36), 0.99),
    OcrToken("23.10.2026", (0.5, 0.5, 0.8, 0.53), 0.99),
    OcrToken("QR 4821 7730 19", (0.5, 0.7, 0.9, 0.73), 0.99),
]


# ---------- ProofRegistry ----------
@pytest.fixture
def store(tmp_path: Path):
    db = Database(tmp_path / "reg.db")
    blobs = BlobStore(tmp_path / "blobs")
    yield db, blobs
    db.close()


def _post(db: Database, text: str | None = None, channel: str | None = None) -> int:
    return db.create_post(source="test", channel=channel, author=None, posted_at=None, text=text)


def test_register_image_stores_blob_and_finds_exact_copy_in_other_post(store, original_jpeg: bytes) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)

    # Act
    first = reg.register_image(p1, original_jpeg, ocr_tokens=FAKE_TOKENS)
    second = reg.register_image(p2, original_jpeg, ocr_tokens=FAKE_TOKENS)

    # Assert
    assert first.matches == []
    assert [(m.artifact_id, m.post_id, m.distance) for m in second.matches] == [(first.artifact_id, p1, 0)]
    assert second.matches[0].changes == []
    assert blobs.get(first.sha256, "jpg") == original_jpeg
    art = db.get_artifact(second.artifact_id)
    assert art["kind"] == "image" and art["ext"] == "jpg" and len(art["pdq"]) == 64
    assert art["ocr"][0]["text"] == "+150 000 T"
    assert "+150 000 T" in first.ocr_text


def test_register_image_ignores_copies_within_same_post(store, original_jpeg: bytes) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1 = _post(db)
    reg.register_image(p1, original_jpeg, ocr_tokens=[])

    # Act
    again = reg.register_image(p1, original_jpeg, ocr_tokens=[])

    # Assert
    assert again.matches == []


def test_register_image_records_digit_changes_between_copies(store, original_jpeg: bytes) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)
    edited = [OcrToken("+950 000 T", t.box, t.confidence) if t.text.startswith("+") else t for t in FAKE_TOKENS]
    first = reg.register_image(p1, original_jpeg, ocr_tokens=FAKE_TOKENS)

    # Act
    second = reg.register_image(p2, original_jpeg, ocr_tokens=edited)

    # Assert
    change = second.matches[0].changes[0]
    assert (change.kind, change.before, change.after) == ("amount", "+150 000 T", "+950 000 T")
    stored = db.matches_for(second.artifact_id)[0]
    assert stored["other_id"] == first.artifact_id
    assert stored["diff"]["changes"][0]["kind"] == "amount"


def test_edited_repost_is_matched_via_strong_ocr_tokens(store, original_jpeg, edited_jpeg, original_tokens,
                                                         edited_tokens) -> None:
    # Arrange: перепост с обрезкой и масштабом далеко по PDQ (> строгого порога), но с теми же номером и датой
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)
    first = reg.register_image(p1, original_jpeg, ocr_tokens=original_tokens)

    # Act
    second = reg.register_image(p2, edited_jpeg, ocr_tokens=edited_tokens)

    # Assert
    assert [m.artifact_id for m in second.matches] == [first.artifact_id]
    assert second.matches[0].distance > registry_mod.PDQ_STRICT
    assert any(c.kind == "amount" for c in second.matches[0].changes)


def test_other_receipt_of_same_template_is_not_matched(store, original_jpeg, other_receipt_jpeg, original_tokens) -> None:
    # Arrange: тот же макет чека, но другие номер, дата и время
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)
    reg.register_image(p1, original_jpeg, ocr_tokens=original_tokens)
    other_tokens = [OcrToken("QR 1111 2222 33", (0.5, 0.7, 0.9, 0.73), 0.99), OcrToken("02.09.2026", (0.5, 0.5, 0.8, 0.53), 0.99)]

    # Act
    result = reg.register_image(p2, other_receipt_jpeg, ocr_tokens=other_tokens)

    # Assert
    assert result.matches == []


def test_registry_reloads_indexes_from_database(store, original_jpeg: bytes) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1 = _post(db)
    img = reg.register_image(p1, original_jpeg, ocr_tokens=FAKE_TOKENS)
    txt = reg.register_text(p1, normalize_text(PYRAMID_PROOF_TEXT).folded)

    # Act
    reloaded = ProofRegistry(db, blobs, ocr_enabled=False)
    p2 = _post(db)
    again = reloaded.register_image(p2, original_jpeg, ocr_tokens=FAKE_TOKENS)

    # Assert
    assert len(reloaded.images) == 1 + 1 and len(reloaded.texts) == 1
    assert [m.artifact_id for m in again.matches] == [img.artifact_id]
    assert txt is not None
    assert reloaded._strong_of[img.artifact_id] == strong_tokens(FAKE_TOKENS)


def test_strong_tokens_are_digit_runs_independent_of_ocr_split() -> None:
    # Arrange: одна строка «23.10.2026 14:35» одним токеном и двумя
    whole = [OcrToken("Дата", (0.1, 0.5, 0.3, 0.52), 1.0), OcrToken("23.10.2026 14:35", (0.5, 0.5, 0.9, 0.52), 1.0),
             OcrToken("Комиссия 0 T", (0.1, 0.6, 0.4, 0.62), 1.0)]
    split = [OcrToken("Дата", (0.1, 0.5, 0.3, 0.52), 1.0), OcrToken("23.10.2026", (0.5, 0.5, 0.7, 0.52), 1.0),
             OcrToken("14:35", (0.75, 0.5, 0.9, 0.52), 1.0)]

    # Act / Assert: короткие серии («0») не входят, разрезанная строка даёт ту же серию
    assert strong_tokens(whole) == strong_tokens(split) == frozenset({"231020261435"})


def test_register_text_skips_short_texts_and_finds_templates(store) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)
    a = normalize_text(PYRAMID_PROOF_TEXT).folded
    b = normalize_text(PYRAMID_PROOF_TEXT.replace("150 000", "990 000")).folded

    # Act
    short = reg.register_text(p1, "коротко")
    first = reg.register_text(p1, a)
    same_post = reg.register_text(p1, a)
    second = reg.register_text(p2, b)

    # Assert
    assert short is None
    assert first.matches == [] and same_post.matches == []
    assert [(aid, pid, sim) for aid, pid, sim in second.matches if pid == p1][0][2] == 1.0


def test_register_audio_matches_exact_forwards(store) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    p1, p2 = _post(db), _post(db)
    voice = b"OggS" + b"\x00" * 64

    # Act
    _, first_same = reg.register_audio(p1, voice, "ogg")
    aid, same = reg.register_audio(p2, voice, "ogg")

    # Assert
    assert first_same == [] and same == [p1]
    assert db.get_artifact(aid)["kind"] == "audio"
    assert blobs.get(db.get_artifact(aid)["sha256"], "ogg") == voice


@pytest.mark.parametrize(("fmt", "ext"), [("PNG", "png"), ("WEBP", "webp"), ("JPEG", "jpg")])
def test_register_image_detects_format_by_signature(store, fmt: str, ext: str) -> None:
    # Arrange
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=False)
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 120, 200)).save(buf, fmt)

    # Act
    result = reg.register_image(_post(db), buf.getvalue(), ocr_tokens=[])

    # Assert
    assert db.get_artifact(result.artifact_id)["ext"] == ext


def test_peek_format_unknown_bytes() -> None:
    assert registry_mod._peek_format(b"GIF89a....") is None


def test_register_image_marks_ocr_failure(store, original_jpeg: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def broken(_img):
        raise OcrUnavailable("нет модели")

    monkeypatch.setattr(registry_mod, "run_ocr", broken)
    db, blobs = store
    reg = ProofRegistry(db, blobs, ocr_enabled=True)

    # Act
    result = reg.register_image(_post(db), original_jpeg)

    # Assert
    assert result.ocr_ok is False and result.tokens == []


def test_text_index_incremental_merge_keeps_old_items_findable() -> None:
    # Arrange: два слияния подряд (вставка в уже отсортированные массивы)
    from pruf.registry.index import TextIndex

    rng = np.random.default_rng(5)
    sigs = rng.integers(0, 2**32, size=(2 * _MERGE_EVERY, 64), dtype=np.uint64)
    idx = TextIndex()

    # Act
    idx.add_many(np.arange(_MERGE_EVERY, dtype=np.int64), sigs[:_MERGE_EVERY])
    idx.add_many(np.arange(_MERGE_EVERY, 2 * _MERGE_EVERY, dtype=np.int64), sigs[_MERGE_EVERY:])

    # Assert
    assert idx._merged == 2 * _MERGE_EVERY
    for b in range(16):
        assert np.all(np.diff(idx._sorted_keys[b].astype(np.float64)) >= 0)
    for probe in (3, _MERGE_EVERY - 1, _MERGE_EVERY + 7, 2 * _MERGE_EVERY - 1):
        assert idx.query(sigs[probe])[0] == (probe, 1.0)


# ---------- Pruf: сквозной приём ----------
@pytest.fixture
def pruf(tmp_path: Path):
    p = Pruf(make_settings(tmp_path))
    yield p
    p.db.close()


def _ingest(p: Pruf, text: str | None, *, images: tuple[bytes, ...] = (), channel: str | None = None,
            posted_at: str | None = None, label: str | None = None, audio: bytes | None = None) -> dict:
    uploads = tuple(Upload(img, "image", "jpg") for img in images)
    if audio is not None:
        uploads += (Upload(audio, "audio", "ogg"),)
    return p.ingest(Submission(text=text, uploads=uploads, channel=channel, posted_at=posted_at, label=label))


def _ids(result: dict) -> set[str]:
    return {e["feature_id"] for e in result["analysis"]["evidence"]}


def test_edited_payout_screenshot_is_linked_to_original(pruf: Pruf, original_jpeg: bytes, edited_jpeg: bytes) -> None:
    # Arrange: оригинальный «скрин выплаты» в посте пирамиды
    first = _ingest(pruf, PYRAMID_PROOF_TEXT, images=(original_jpeg,), channel="chan1", posted_at="2026-10-01T10:00:00")

    # Act: отредактированная копия (сумма перерисована, обрезка, подпись канала) в другом посте
    second = _ingest(pruf, PYRAMID_REPOST_TEXT, images=(edited_jpeg,), channel="chan2", posted_at="2026-10-02T10:00:00")

    # Assert
    assert first["analysis"]["level"] in ("medium", "high")
    proof = second["proofs"][0]
    assert proof["match_count"] == 1
    match = proof["matches"][0]
    assert match["post_id"] == first["post_id"]
    assert any(c["kind"] == "amount" and "950" in c["after"] for c in match["changes"])
    ids = _ids(second)
    assert {"registry.edited_digits", "registry.reused_proof"} <= ids
    edited = next(e for e in second["analysis"]["evidence"] if e["feature_id"] == "registry.edited_digits")
    assert "→" in edited["quote"]
    assert second["analysis"]["level"] == "high"
    assert not second["analysis"]["degraded"]


def test_same_kaspi_phone_links_posts_into_one_case(pruf: Pruf) -> None:
    # Arrange / Act
    from pruf.graph.builder import CaseGraph

    lottery = _ingest(pruf, LOTTERY_RU.format(phone=KASPI_PHONE), channel="lottery_chan")
    lottery2 = _ingest(pruf, "Лотерея для своих: билет 1000 тенге, главный приз Toyota Camry. Оплата на каспи "
                       + KASPI_PHONE, channel="lottery_chan2")
    casino = _ingest(pruf, CASINO_RU.format(phone=KASPI_PHONE), channel="casino_chan")
    pyramid = _ingest(pruf, PYRAMID_RU.format(phone=KASPI_PHONE), channel="pyramid_chan")
    graph = CaseGraph(pruf.db)
    graph.ensure(pruf.version)

    # Assert
    assert lottery["analysis"]["track"] == "lottery"
    assert casino["analysis"]["track"] == "casino" and pyramid["analysis"]["track"] == "pyramid"
    req_ev = [e for e in lottery2["analysis"]["evidence"] if e["feature_id"] == "graph.requisite.phone"]
    assert req_ev and req_ev[0]["quote"] == "+77019998877" and req_ev[0]["source"] == "graph"
    post_ids = {lottery["post_id"], lottery2["post_id"], casino["post_id"], pyramid["post_id"]}
    cases = graph.cases()
    assert len(cases) == 1
    assert set(cases[0].post_ids) == post_ids
    assert set(cases[0].tracks) == {"lottery", "casino", "pyramid"}
    assert cases[0].requisites == ("+77019998877",)


def test_cross_track_requisite_reuse_is_visible_in_evidence(pruf: Pruf) -> None:
    # Arrange
    _ingest(pruf, LOTTERY_RU.format(phone=KASPI_PHONE))

    # Act
    casino = _ingest(pruf, CASINO_RU.format(phone=KASPI_PHONE))

    # Assert
    assert casino["analysis"]["track"] == "casino"
    assert "graph.requisite.phone" in _ids(casino)


def test_reused_image_in_benign_posts_is_not_risk(pruf: Pruf, other_receipt_jpeg: bytes) -> None:
    # Arrange
    _ingest(pruf, "Наш магазин принимает оплату через Kaspi QR, пример чека ниже", images=(other_receipt_jpeg,))

    # Act
    second = _ingest(pruf, "Пример квитанции для бухгалтерии", images=(other_receipt_jpeg,))

    # Assert
    assert "registry.reused_benign" in _ids(second)
    assert second["analysis"]["level"] == "low"


def test_text_template_from_risky_post_adds_context(pruf: Pruf) -> None:
    # Arrange
    _ingest(pruf, PYRAMID_RU.format(phone="+7 701 111 22 33"))

    # Act: та же рассылка с другими цифрами и другим номером
    second = _ingest(pruf, PYRAMID_RU.format(phone="+7 702 444 55 66").replace("5%", "7%").replace("5000", "9000"))

    # Assert
    assert second["text_matches"]
    assert "registry.text_template" in _ids(second)


def test_forwarded_voice_from_risky_post_adds_reused_proof(pruf: Pruf) -> None:
    # Arrange
    voice = b"OggS" + bytes(range(200))
    _ingest(pruf, PYRAMID_RU.format(phone="+7 701 111 22 33"), audio=voice)

    # Act
    second = _ingest(pruf, "Пассивный доход 3% в день, вход от 2000 тг, пиши в лс", audio=voice)

    # Assert
    assert "registry.reused_proof" in _ids(second)
    assert {"component": "whisper", "reason": second["analysis"]["degraded"][0]["reason"]} == second["analysis"]["degraded"][0]


def test_transcript_is_analyzed_as_voice_source(pruf: Pruf) -> None:
    # Act
    result = pruf.ingest(Submission(text=None, transcript=PYRAMID_RU.format(phone="+7 701 111 22 33"),
                                    uploads=(Upload(b"OggS" + b"\x01" * 50, "audio", "ogg"),)))

    # Assert
    assert result["analysis"]["track"] == "pyramid"
    assert any(e["source"] == "voice" for e in result["analysis"]["evidence"])
    assert not result["analysis"]["degraded"]  # расшифровка передана, Whisper не нужен


def test_ela_anomaly_in_digits_adds_evidence(pruf: Pruf, original_jpeg: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(registry_mod, "token_anomalies",
                        lambda img, tokens: [TokenAnomaly("+950 000 T", (0.1, 0.3, 0.8, 0.36), 3.2)])

    # Act
    result = _ingest(pruf, PYRAMID_REPOST_TEXT, images=(original_jpeg,))

    # Assert
    assert "registry.ela" in _ids(result)
    assert result["proofs"][0]["anomalies"][0]["ratio"] == 3.2


def test_ocr_unavailable_is_reported_as_degraded(pruf: Pruf, original_jpeg: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def broken(_img):
        raise OcrUnavailable("нет модели")

    monkeypatch.setattr(registry_mod, "run_ocr", broken)

    # Act
    result = _ingest(pruf, "Скрин выплаты", images=(original_jpeg,))

    # Assert
    assert [d["component"] for d in result["analysis"]["degraded"]] == ["ocr"]


def test_broken_image_is_rejected_before_post_is_created(pruf: Pruf) -> None:
    # Act / Assert
    with pytest.raises((OSError, ValueError)):
        _ingest(pruf, "текст", images=(b"\xff\xd8\xff not really a jpeg",))
    assert pruf.db.count_posts() == 0


def test_processing_error_marks_post_failed_and_hides_it_from_graph(pruf: Pruf, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def boom(*_a, **_kw):
        raise RuntimeError("сбой детектора")

    monkeypatch.setattr(pruf.detector, "detect", boom)

    # Act
    with pytest.raises(RuntimeError):
        _ingest(pruf, LOTTERY_RU.format(phone=KASPI_PHONE))

    # Assert
    post = pruf.db.get_post(1)
    assert post["status"] == "failed"
    assert post["analysis"] == {"error": "RuntimeError"}
    assert pruf.db.all_posts_brief() == []


def test_full_card_number_is_not_stored(pruf: Pruf) -> None:
    # Act
    result = _ingest(pruf, "Розыгрыш iPhone! Участие 2000 тг на карту 4400 4301 2345 6789, пиши в лс")
    post = pruf.db.get_post(result["post_id"])

    # Assert
    assert "4400 4301 2345 6789" not in post["text"]
    assert "440043******6789" in post["text"]
    reqs = pruf.db.requisites_for_post(result["post_id"])
    assert [r["display"] for r in reqs if r["kind"] == "card"] == ["440043******6789"]
    assert "4400430123456789" not in str(result)


def test_only_case_linking_domains_are_stored(pruf: Pruf) -> None:
    # Act
    result = _ingest(pruf, "Зеркало казино vulkan-kz.top, оплата kaspi.kz/pay/x, канал t.me/kz, коротко https://bit.ly/x1")

    # Assert
    assert [link["domain"] for link in pruf.db.links_for_post(result["post_id"])] == ["vulkan-kz.top"]


def test_analyze_only_does_not_store_anything(pruf: Pruf) -> None:
    # Act
    analysis = pruf.analyze_only(LOTTERY_RU.format(phone=KASPI_PHONE))

    # Assert
    assert analysis["level"] == "high" and analysis["level_label"] == "высокий"
    assert pruf.db.count_posts() == 0


def test_ingest_increments_version(pruf: Pruf) -> None:
    # Act
    _ingest(pruf, "Привет")
    _ingest(pruf, "Пока")

    # Assert
    assert pruf.version == 2
