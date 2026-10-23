"""Отпечатки артефактов: PDQ для изображений, MinHash для текстов, SHA-256 для точных копий."""

from __future__ import annotations

import hashlib
import io
import re
import zlib

import numpy as np
import pdqhash
from PIL import Image, ImageOps

PDQ_BITS = 256
PDQ_WORDS = PDQ_BITS // 64
MINHASH_PERM = 64
MINHASH_BANDS = 16
MINHASH_ROWS = MINHASH_PERM // MINHASH_BANDS
SHINGLE = 5
_PRIME = np.uint64(4294967311)  # простое > 2^32
_rng = np.random.default_rng(20261023)
_A = _rng.integers(1, 2**31 - 1, size=MINHASH_PERM, dtype=np.uint64)
_B = _rng.integers(0, 2**31 - 1, size=MINHASH_PERM, dtype=np.uint64)
_BAND_MIX = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0x27D4EB2F165667C5], dtype=np.uint64)
_DIGITS_RE = re.compile(r"\d")
_SPACES_RE = re.compile(r"\s+")
MAX_IMAGE_PIXELS = 40_000_000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def open_image(data: bytes) -> Image.Image:
    """Открыть изображение с защитой от «бомб» и с учётом EXIF-поворота."""
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    img = Image.open(io.BytesIO(data))
    img.load()
    return ImageOps.exif_transpose(img).convert("RGB")


def pdq_hash(img: Image.Image) -> tuple[np.ndarray, int]:
    """PDQ (Meta) 256 бит, упакованные в 4 uint64, и качество 0–100."""
    bits, quality = pdqhash.compute(np.asarray(img))
    packed = np.packbits(bits.astype(np.uint8)).view(">u8").astype(np.uint64)
    return packed, int(quality)


def pdq_hex(words: np.ndarray) -> str:
    return "".join(f"{int(w):016x}" for w in words)


def pdq_from_hex(value: str) -> np.ndarray:
    return np.array([int(value[i:i + 16], 16) for i in range(0, 64, 16)], dtype=np.uint64)


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.bitwise_count(np.bitwise_xor(a, b)).sum())


def text_shingles(folded: str) -> np.ndarray:
    """Шинглы свёрнутого текста; цифры заменены на #, чтобы шаблон с другой суммой оставался дублем."""
    text = _SPACES_RE.sub(" ", _DIGITS_RE.sub("#", folded)).strip()
    if len(text) < SHINGLE:
        return np.array([zlib.crc32(text.encode())], dtype=np.uint64) if text else np.array([], dtype=np.uint64)
    grams = {text[i:i + SHINGLE] for i in range(len(text) - SHINGLE + 1)}
    return np.fromiter((zlib.crc32(g.encode()) for g in grams), dtype=np.uint64, count=len(grams))


def minhash(folded: str) -> np.ndarray | None:
    shingles = text_shingles(folded)
    if shingles.size == 0:
        return None
    values = (shingles[None, :] * _A[:, None] + _B[:, None]) % _PRIME
    return values.min(axis=1).astype(np.uint64)


def band_keys_batch(signatures: np.ndarray) -> np.ndarray:
    """Ключи LSH-полос для матрицы сигнатур (N, MINHASH_PERM) -> (N, MINHASH_BANDS)."""
    rows = signatures.reshape(len(signatures), MINHASH_BANDS, MINHASH_ROWS)
    keys = np.bitwise_xor.reduce(rows * _BAND_MIX[:MINHASH_ROWS], axis=2)
    return keys ^ np.arange(MINHASH_BANDS, dtype=np.uint64)[None, :]


def band_keys(signature: np.ndarray) -> np.ndarray:
    return band_keys_batch(signature.reshape(1, -1))[0]


def minhash_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(a == b))
