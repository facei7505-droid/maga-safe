"""Реестр ПРУФ: регистрирует артефакты поста и находит их прежние появления."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from pruf.normalize.ocr import OcrToken, OcrUnavailable, run_ocr, tokens_to_text
from pruf.registry.forensics import TokenAnomaly, token_anomalies
from pruf.registry.hashing import (
    minhash,
    open_image,
    pdq_from_hex,
    pdq_hash,
    pdq_hex,
    sha256_bytes,
)
from pruf.registry.imagediff import TokenChange, diff_tokens
from pruf.registry.index import ImageIndex, TextIndex
from pruf.storage.blobs import BlobStore
from pruf.storage.db import Database


def strong_tokens(tokens: list[OcrToken]) -> frozenset[str]:
    """Токены с 4+ цифрами (номер квитанции, дата, время, телефон): совпадают у копий одного пруфа
    и не совпадают у разных чеков одного шаблона. Сумма из 3-значных групп сюда не входит,
    поэтому подделанная сумма не мешает найти копию."""
    out = set()
    for t in tokens:
        compact = re.sub(r"\s", "", t.text)
        if sum(ch.isdigit() for ch in compact) >= 4:
            out.add(compact)
    return frozenset(out)

log = logging.getLogger(__name__)
MIN_TEXT_FOR_INDEX = 40
PDQ_STRICT = 40  # почти точная копия
PDQ_LOOSE = 96  # кандидат, если совпадают «сильные» токены OCR (обрезка, подписи канала)
MIN_SHARED_STRONG = 2
MIN_STRONG_OVERLAP = 0.5
# Разные чеки одного шаблона (банк, магазин) визуально почти одинаковы и проходят PDQ_STRICT.
# Если у обоих есть сильные токены и они почти не совпадают, это другой документ, а не копия.
TEMPLATE_MAX_OVERLAP = 0.25
MAX_DIFFS_PER_IMAGE = 20
_FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


@dataclass
class ImageMatch:
    artifact_id: int
    post_id: int
    distance: int
    changes: list[TokenChange] = field(default_factory=list)


@dataclass
class ImageResult:
    artifact_id: int
    sha256: str
    ocr_text: str
    tokens: list[OcrToken]
    matches: list[ImageMatch]
    anomalies: list[TokenAnomaly]
    ocr_ok: bool = True


@dataclass
class TextResult:
    artifact_id: int
    matches: list[tuple[int, int, float]]  # (artifact_id, post_id, similarity)


def tokens_from_json(items: list[dict]) -> list[OcrToken]:
    return [OcrToken(i["text"], tuple(i["box"]), float(i.get("confidence", 1.0))) for i in items]


def tokens_to_json(tokens: list[OcrToken]) -> list[dict]:
    return [{"text": t.text, "box": [round(v, 4) for v in t.box], "confidence": round(t.confidence, 3)} for t in tokens]


def changes_to_json(changes: list[TokenChange]) -> list[dict]:
    return [{"kind": c.kind, "before": c.before, "after": c.after, "box_before": c.box_before, "box_after": c.box_after}
            for c in changes]


class ProofRegistry:
    def __init__(self, db: Database, blobs: BlobStore, ocr_enabled: bool = True):
        self._db = db
        self._blobs = blobs
        self._ocr_enabled = ocr_enabled
        self.images = ImageIndex()
        self.texts = TextIndex()
        self._strong: dict[str, set[int]] = defaultdict(set)  # токен -> артефакты
        self._strong_of: dict[int, frozenset[str]] = {}
        self._load()

    def _load(self) -> None:
        img_ids, img_hashes, txt_ids, txt_sigs = [], [], [], []
        for row in self._db.iter_index_rows():
            if row["pdq"]:
                img_ids.append(row["id"])
                img_hashes.append(pdq_from_hex(row["pdq"]))
            if row.get("ocr_json"):
                self._remember_strong(row["id"], strong_tokens(tokens_from_json(json.loads(row["ocr_json"]))))
            if row["minhash"]:
                txt_ids.append(row["id"])
                txt_sigs.append(np.frombuffer(row["minhash"], dtype=np.uint64))
        if img_ids:
            self.images.add_many(np.array(img_ids, dtype=np.int64), np.stack(img_hashes))
        if txt_ids:
            self.texts.add_many(np.array(txt_ids, dtype=np.int64), np.stack(txt_sigs))
        log.info("реестр загружен: %d изображений, %d текстов", len(img_ids), len(txt_ids))

    def _remember_strong(self, artifact_id: int, strong: frozenset[str]) -> None:
        if strong:
            self._strong_of[artifact_id] = strong
            for tok in strong:
                self._strong[tok].add(artifact_id)

    def _image_candidates(self, words: np.ndarray, strong: frozenset[str]) -> list[tuple[int, int]]:
        """Кандидаты: близкий PDQ, либо умеренно близкий PDQ плюс общие сильные токены OCR."""
        loose = dict(self.images.query(words, max_distance=PDQ_LOOSE))
        shared_counts: dict[int, int] = defaultdict(int)
        for tok in strong:
            for aid in self._strong.get(tok, ()):
                shared_counts[aid] += 1
        accepted: list[tuple[int, int]] = []
        for aid, dist in loose.items():
            shared = shared_counts.get(aid, 0)
            other = self._strong_of.get(aid, frozenset())
            overlap = shared / (len(strong | other) or 1)
            if dist <= PDQ_STRICT:
                same_template_only = len(strong) >= MIN_SHARED_STRONG and len(other) >= MIN_SHARED_STRONG \
                    and overlap < TEMPLATE_MAX_OVERLAP
                if not same_template_only:
                    accepted.append((aid, dist))
            elif shared >= MIN_SHARED_STRONG and overlap >= MIN_STRONG_OVERLAP:
                accepted.append((aid, dist))
        return sorted(accepted, key=lambda x: x[1])

    def register_image(self, post_id: int, data: bytes, ocr_tokens: list[OcrToken] | None = None,
                       img: Image.Image | None = None) -> ImageResult:
        img = img if img is not None else open_image(data)
        sha = sha256_bytes(data)
        fmt = _FORMAT_EXT.get((_peek_format(data) or "").upper(), "png")
        self._blobs.put(sha, fmt, data)
        words, quality = pdq_hash(img)
        ocr_ok = True
        tokens = ocr_tokens or []
        if ocr_tokens is None and self._ocr_enabled:
            try:
                tokens = run_ocr(img)
            except OcrUnavailable:
                ocr_ok = False
        anomalies = token_anomalies(img, tokens) if tokens else []
        strong = strong_tokens(tokens)
        found = self._image_candidates(words, strong)
        artifact_id = self._db.create_artifact(
            post_id=post_id, kind="image", sha256=sha, ext=fmt, pdq=pdq_hex(words), pdq_quality=quality,
            ocr=tokens_to_json(tokens), width=img.width, height=img.height,
        )
        post_of = self._db.artifact_post_ids(a for a, _ in found)
        matches: list[ImageMatch] = []
        for rank, (other_id, dist) in enumerate(found):
            if post_of.get(other_id) == post_id:
                continue
            changes: list[TokenChange] = []
            if rank < MAX_DIFFS_PER_IMAGE and tokens:
                other = self._db.get_artifact(other_id)
                if other and other["ocr"]:
                    changes = diff_tokens(tokens_from_json(other["ocr"]), tokens)
            self._db.add_match(artifact_id, other_id, "image", dist, {"changes": changes_to_json(changes)} if changes else None)
            matches.append(ImageMatch(other_id, post_of.get(other_id, -1), dist, changes))
        self.images.add(artifact_id, words)
        self._remember_strong(artifact_id, strong)
        return ImageResult(artifact_id, sha, tokens_to_text(tokens), tokens, matches, anomalies, ocr_ok)

    def register_text(self, post_id: int, folded: str) -> TextResult | None:
        if len(folded.strip()) < MIN_TEXT_FOR_INDEX:
            return None
        sig = minhash(folded)
        if sig is None:
            return None
        found = self.texts.query(sig)
        artifact_id = self._db.create_artifact(post_id=post_id, kind="text", sha256=sha256_bytes(folded.encode()),
                                               ext=None, minhash=sig.tobytes())
        post_of = self._db.artifact_post_ids(a for a, _ in found)
        matches = []
        for other_id, sim in found:
            if post_of.get(other_id) == post_id:
                continue
            self._db.add_match(artifact_id, other_id, "text", round(1 - sim, 3))
            matches.append((other_id, post_of.get(other_id, -1), sim))
        self.texts.add(artifact_id, sig)
        return TextResult(artifact_id, matches)

    def register_audio(self, post_id: int, data: bytes, ext: str) -> tuple[int, list[int]]:
        sha = sha256_bytes(data)
        self._blobs.put(sha, ext, data)
        artifact_id = self._db.create_artifact(post_id=post_id, kind="audio", sha256=sha, ext=ext)
        same = [r for r in self._db.artifacts_by_sha(sha) if r["id"] != artifact_id]
        for r in same:
            self._db.add_match(artifact_id, r["id"], "audio", 0)
        return artifact_id, [r["post_id"] for r in same]


def _peek_format(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None
