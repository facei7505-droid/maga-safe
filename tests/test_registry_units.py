"""Реестр ПРУФ по частям: отпечатки, индексы почти-дубликатов, OCR-дифф копий, ELA."""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from pruf.normalize.ocr import OcrToken, tokens_to_text
from pruf.normalize.text import normalize_text
from pruf.registry import index as index_mod
from pruf.registry.forensics import ela_heatmap_png, ela_map, token_anomalies
from pruf.registry.hashing import (
    MINHASH_PERM,
    PDQ_WORDS,
    band_keys,
    hamming,
    minhash,
    minhash_similarity,
    open_image,
    pdq_from_hex,
    pdq_hash,
    pdq_hex,
    sha256_bytes,
    text_shingles,
)
from pruf.registry.imagediff import diff_tokens, summarize_changes
from pruf.registry.index import ImageIndex, TextIndex

TEMPLATE_A = "Вот пруф выплаты! Уже вывел 150 000 тг за неделю. Вступительный взнос 5000 тг, пиши в лс"
TEMPLATE_B = "Вот пруф выплаты! Уже вывел 870 500 тг за неделю. Вступительный взнос 9000 тг, пиши в лс"
UNRELATED = "Скидка 20% на всё меню нашей кофейни до конца недели, оплата картой или Kaspi QR"


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------- hashing ----------
def test_pdq_hex_roundtrip(original_jpeg: bytes) -> None:
    # Arrange
    words, quality = pdq_hash(open_image(original_jpeg))

    # Act
    restored = pdq_from_hex(pdq_hex(words))

    # Assert
    assert words.shape == (PDQ_WORDS,) and words.dtype == np.uint64
    assert len(pdq_hex(words)) == 64
    assert np.array_equal(restored, words)
    assert 0 <= quality <= 100


def test_pdq_is_close_for_reposts_and_far_for_other_images(original_jpeg: bytes, edited_jpeg: bytes) -> None:
    # Arrange
    a, _ = pdq_hash(open_image(original_jpeg))
    b, _ = pdq_hash(open_image(edited_jpeg))
    noise = Image.fromarray(np.random.default_rng(1).integers(0, 255, (300, 300, 3), dtype=np.uint8))
    c, _ = pdq_hash(noise)

    # Assert
    assert hamming(a, a) == 0
    assert hamming(a, b) < 96
    assert hamming(a, c) > 96


def test_hamming_counts_differing_bits() -> None:
    a = np.array([0, 0, 0, 0], dtype=np.uint64)
    b = np.array([0b1011, 0, 1 << 63, 0], dtype=np.uint64)
    assert hamming(a, b) == 4


def test_minhash_near_duplicate_texts_with_different_numbers_are_identical() -> None:
    # Act
    a = minhash(normalize_text(TEMPLATE_A).folded)
    b = minhash(normalize_text(TEMPLATE_B).folded)
    c = minhash(normalize_text(UNRELATED).folded)

    # Assert
    assert a is not None and a.shape == (MINHASH_PERM,)
    assert minhash_similarity(a, b) == 1.0  # цифры заменены на #
    assert minhash_similarity(a, c) < 0.2


def test_minhash_similarity_degrades_gracefully_with_edits() -> None:
    # Arrange
    edited = TEMPLATE_A.replace("пиши в лс", "пиши в директ, места ограничены")

    # Act
    sim = minhash_similarity(minhash(normalize_text(TEMPLATE_A).folded), minhash(normalize_text(edited).folded))

    # Assert
    assert 0.4 < sim < 1.0


def test_text_shingles_short_and_empty_text() -> None:
    assert text_shingles("").size == 0
    assert text_shingles("абв").size == 1
    assert minhash("   ") is None


def test_band_keys_shape_and_determinism() -> None:
    sig = minhash("какой-то достаточно длинный текст для шинглов")
    assert band_keys(sig).shape == (16,)
    assert np.array_equal(band_keys(sig), band_keys(sig.copy()))


def test_sha256_bytes_matches_hashlib() -> None:
    import hashlib

    assert sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_open_image_applies_exif_rotation_and_converts_to_rgb() -> None:
    # Arrange: RGBA 40×20 с EXIF Orientation=6 (поворот на 90°)
    img = Image.new("RGBA", (40, 20), (255, 0, 0, 128))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", exif=exif.tobytes())

    # Act
    opened = open_image(buf.getvalue())

    # Assert
    assert opened.mode == "RGB"
    assert opened.size == (20, 40)


def test_open_image_downscales_large_images() -> None:
    # Act
    opened = open_image(_png(Image.new("RGB", (5000, 100), "white")))

    # Assert
    assert max(opened.size) <= 2400


def _png_header_only(width: int, height: int) -> bytes:
    """PNG с заголовком огромного размера и без данных: проверка защиты от «бомб» без выделения памяти."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


def test_open_image_rejects_decompression_bombs() -> None:
    # Act / Assert: ожидаем контролируемую ошибку значения, а не попытку декодировать 400 Мп
    with pytest.raises((ValueError, Image.DecompressionBombError)):
        open_image(_png_header_only(20000, 20000))


def test_open_image_rejects_non_images() -> None:
    with pytest.raises(OSError):
        open_image(b"\x89PNG\r\n\x1a\n not really a png")


# ---------- ImageIndex ----------
def test_image_index_returns_matches_sorted_by_distance() -> None:
    # Arrange
    idx = ImageIndex()
    base = np.array([0, 0, 0, 0], dtype=np.uint64)
    idx.add(1, base)
    idx.add(2, np.array([0b111, 0, 0, 0], dtype=np.uint64))  # 3 бита
    idx.add(3, np.array([2**64 - 1, 0, 0, 0], dtype=np.uint64))  # 64 бита

    # Act
    hits = idx.query(base, max_distance=40)

    # Assert
    assert hits == [(1, 0), (2, 3)]
    assert len(idx) == 3


def test_image_index_empty_query_returns_nothing() -> None:
    assert ImageIndex().query(np.zeros(PDQ_WORDS, dtype=np.uint64)) == []


def test_image_index_grows_and_respects_limit() -> None:
    # Arrange: больше начальной ёмкости
    idx = ImageIndex()
    n = 2500
    hashes = np.zeros((n, PDQ_WORDS), dtype=np.uint64)
    hashes[:, 0] = np.arange(n, dtype=np.uint64) % 8  # до 3 бит отличий
    idx.add_many(np.arange(n, dtype=np.int64), hashes)

    # Act
    hits = idx.query(np.zeros(PDQ_WORDS, dtype=np.uint64), max_distance=3, limit=10)

    # Assert
    assert len(idx) == n
    assert len(hits) == 10
    assert [d for _, d in hits] == sorted(d for _, d in hits)
    assert hits[0][1] == 0


# ---------- TextIndex ----------
def _random_sigs(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 2**32, size=(n, MINHASH_PERM), dtype=np.uint64)


def test_text_index_finds_items_in_pending_buffer() -> None:
    # Arrange
    idx = TextIndex()
    sigs = _random_sigs(5)
    for i, sig in enumerate(sigs):
        idx.add(100 + i, sig)

    # Act
    hits = idx.query(sigs[3])

    # Assert
    assert hits[0] == (103, 1.0)
    assert idx._merged == 0  # всё ещё в буфере


def test_text_index_merges_after_threshold_and_finds_merged_and_pending() -> None:
    # Arrange
    idx = TextIndex()
    n = index_mod._MERGE_EVERY + 10
    sigs = _random_sigs(n + 3, seed=42)
    idx.add_many(np.arange(n, dtype=np.int64), sigs[:n])
    for j in range(3):
        idx.add(n + j, sigs[n + j])  # в буфер после слияния
    near_dup = sigs[7].copy()
    near_dup[:8] = 1  # испорчены 2 полосы из 16, остальные совпадают

    # Act
    merged_hit = idx.query(sigs[7])
    pending_hit = idx.query(sigs[n + 1])
    near_hit = idx.query(near_dup)

    # Assert
    assert idx._merged == n and len(idx) == n + 3
    assert merged_hit[0] == (7, 1.0)
    assert pending_hit[0] == (n + 1, 1.0)
    assert near_hit[0][0] == 7 and near_hit[0][1] == pytest.approx(56 / 64)


def test_text_index_filters_by_min_similarity_and_misses_unrelated() -> None:
    # Arrange
    idx = TextIndex()
    a = minhash(normalize_text(TEMPLATE_A).folded)
    idx.add(1, a)

    # Act
    unrelated = idx.query(minhash(normalize_text(UNRELATED).folded))
    strict = idx.query(a, min_similarity=1.0)

    # Assert
    assert unrelated == []
    assert strict == [(1, 1.0)]


# ---------- imagediff ----------
def tok(text: str, cx: float, cy: float, w: float = 0.2, h: float = 0.03) -> OcrToken:
    return OcrToken(text, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.99)


def _receipt_tokens(amount: str, date: str = "23.10.2026", shift: tuple[float, float] = (0.0, 0.0),
                    time_label: str = "BpeMa") -> list[OcrToken]:
    dx, dy = shift
    return [
        tok("Перевод выполнен", 0.4 + dx, 0.05 + dy),
        tok(amount, 0.4 + dx, 0.33 + dy),
        tok(date, 0.7 + dx, 0.50 + dy),
        tok(time_label, 0.2 + dx, 0.57 + dy),
        tok("14:35", 0.7 + dx, 0.57 + dy),
        tok("QR 4821 7730 19", 0.7 + dx, 0.70 + dy),
    ]


def test_diff_detects_amount_change_after_crop_offset() -> None:
    # Arrange: копия сдвинута обрезкой на 3% по x и 2.5% по y (больше порога сопоставления без поправки)
    before = _receipt_tokens("+150 000 T")
    after = _receipt_tokens("+950 000 T", shift=(-0.03, -0.025))

    # Act
    changes = diff_tokens(before, after)

    # Assert
    assert [(c.kind, c.before, c.after) for c in changes] == [("amount", "+150 000 T", "+950 000 T")]
    assert "+150 000 T → +950 000 T" in summarize_changes(changes)


def test_diff_classifies_date_change() -> None:
    changes = diff_tokens(_receipt_tokens("+1 T"), _receipt_tokens("+1 T", date="24.10.2026"))
    assert [(c.kind, c.after) for c in changes] == [("date", "24.10.2026")]


def test_diff_classifies_ocr_noise_as_text() -> None:
    # Arrange: OCR по-разному прочитал кириллицу («Время»)
    changes = diff_tokens(_receipt_tokens("+1 T"), _receipt_tokens("+1 T", time_label="BpeMy"))

    # Assert
    assert [(c.kind, c.before, c.after) for c in changes] == [("text", "BpeMa", "BpeMy")]


def test_diff_amount_with_different_currency_text_is_text_not_amount() -> None:
    changes = diff_tokens([tok("150 000 T", 0.5, 0.5)], [tok("150 000 KZT", 0.5, 0.5)])
    assert changes[0].kind == "text"


def test_diff_reports_added_and_removed_tokens() -> None:
    # Arrange
    before = [tok("Сумма", 0.2, 0.2), tok("Комиссия", 0.2, 0.8)]
    after = [tok("Сумма", 0.2, 0.2), tok("@channel2", 0.1, 0.97)]

    # Act
    kinds = sorted(c.kind for c in diff_tokens(before, after))

    # Assert
    assert kinds == ["added", "removed"]


def test_summarize_changes_without_edits() -> None:
    assert summarize_changes([]) == "Копии совпадают по распознанному тексту"


def test_diff_on_real_ocr_of_edited_copy_finds_amount(original_tokens, edited_tokens) -> None:
    # Act
    changes = diff_tokens(original_tokens, edited_tokens)

    # Assert
    amounts = [c for c in changes if c.kind == "amount"]
    assert any("150" in c.before and "950" in c.after for c in amounts)
    assert not any(c.kind == "amount" and "4821" in c.before for c in changes)  # номер квитанции не тронут


def test_tokens_to_text_groups_lines_and_orders_by_x() -> None:
    # Arrange
    tokens = [tok("B", 0.8, 0.5), tok("A", 0.2, 0.505), tok("C", 0.5, 0.9)]

    # Act / Assert
    assert tokens_to_text(tokens) == "A B\nC"


def test_ocr_token_center() -> None:
    assert OcrToken("x", (0.0, 0.2, 0.4, 0.6), 1.0).center == pytest.approx((0.2, 0.4))


# ---------- forensics ----------
def test_ela_map_and_heatmap(original_jpeg: bytes) -> None:
    # Arrange
    img = open_image(original_jpeg)

    # Act
    ela = ela_map(img)
    png = ela_heatmap_png(img)

    # Assert
    assert ela.shape == (img.height, img.width)
    assert png.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(png)).size == img.size


def test_token_anomalies_needs_at_least_three_digit_tokens(original_jpeg: bytes) -> None:
    img = open_image(original_jpeg)
    assert token_anomalies(img, [tok("150", 0.5, 0.3), tok("Сумма", 0.5, 0.2)]) == []


def test_token_anomalies_flags_freshly_pasted_digits() -> None:
    # Arrange: фон пережат JPEG q=40, в одну зону вставлены несжатые цифры с резким шумом
    from PIL import ImageDraw

    base = Image.new("RGB", (400, 400), (240, 240, 240))
    draw = ImageDraw.Draw(base)
    for y in (50, 150, 250):
        draw.text((50, y), "12 345", fill=(20, 20, 20))
    buf = io.BytesIO()
    base.save(buf, "JPEG", quality=40)
    img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    noise = Image.fromarray(np.random.default_rng(3).integers(0, 255, (40, 120, 3), dtype=np.uint8))
    img.paste(noise, (40, 340))
    tokens = [OcrToken("12 345", (0.1, y / 400, 0.4, (y + 30) / 400), 0.9) for y in (50, 150, 250)]
    tokens.append(OcrToken("99 999", (0.1, 340 / 400, 0.4, 380 / 400), 0.9))

    # Act
    anomalies = token_anomalies(img, tokens)

    # Assert
    assert isinstance(anomalies, list)
    assert [a.text for a in anomalies] == ["99 999"]
    assert anomalies[0].ratio >= 1.8


def test_token_anomalies_on_real_edited_copy_returns_list(edited_jpeg: bytes, edited_tokens) -> None:
    result = token_anomalies(open_image(edited_jpeg), edited_tokens)
    assert isinstance(result, list)
    assert all(any(ch.isdigit() for ch in a.text) for a in result)
