"""Оркестрация приёма: нормализация → реестр ПРУФ → детектор → контекст графа → сохранение."""

from __future__ import annotations

import logging
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from pruf.config import Settings
from pruf.detect.detector import Detector, SourceText
from pruf.models import Evidence
from pruf.normalize.audio import transcribe
from pruf.normalize.links import ALLOWLIST_DOMAINS, Link
from pruf.normalize.requisites import redact_cards
from pruf.normalize.text import normalize_text
from pruf.registry.hashing import open_image
from pruf.registry.registry import (
    ImageResult,
    ProofRegistry,
    TextResult,
    changes_to_json,
)
from pruf.storage.blobs import BlobStore
from pruf.storage.db import Database

log = logging.getLogger(__name__)
RISKY_LEVELS = ("medium", "high")
# Бренды и площадки: их домены и логотипы повторяются легально и не связывают кейсы.
REUSED_PROOF_WEIGHT = 20
REUSED_PROOF_STEP = 5  # за каждый следующий рискованный пост с тем же пруфом, до +20
EDITED_DIGITS_WEIGHT = 20
ELA_WEIGHT = 8
TEXT_TEMPLATE_WEIGHT = 10
RISKY_REQUISITE_WEIGHT = 20


@dataclass(frozen=True)
class Upload:
    data: bytes
    kind: str  # image | audio
    ext: str = "bin"


@dataclass(frozen=True)
class Submission:
    text: str | None = None
    uploads: tuple[Upload, ...] = ()
    transcript: str | None = None
    source: str = "api"
    channel: str | None = None
    author: str | None = None
    posted_at: str | None = None
    external_id: str | None = None
    label: str | None = None  # метка синтетики для eval, аналитику не показывается


@dataclass
class _Collected:
    images: list[ImageResult] = field(default_factory=list)
    texts: list[TextResult] = field(default_factory=list)
    audio_posts: list[int] = field(default_factory=list)


def _major_track(levels: dict[int, tuple[str, str | None, float]], post_ids: list[int]) -> str:
    tracks = Counter(levels[p][1] for p in post_ids if p in levels and levels[p][1])
    return tracks.most_common(1)[0][0] if tracks else "common"


def _links_cases(link: Link) -> bool:
    """Связывает ли домен посты в кейс: не бренды, не мессенджеры, не нераскрытые сокращатели."""
    if link.domain in ALLOWLIST_DOMAINS or link.is_messenger:
        return False
    return not (link.is_shortener and not link.resolved)


class Pruf:
    """Фасад платформы: один объект на процесс."""

    def __init__(self, settings: Settings, detector: Detector | None = None, ocr_enabled: bool = True):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.blobs = BlobStore(settings.blob_dir)
        self.registry = ProofRegistry(self.db, self.blobs, ocr_enabled=ocr_enabled and settings.ocr_enabled)
        self.detector = detector or Detector(settings)
        self.version = 0  # растёт при каждом приёме, по нему сбрасывается кэш графа
        # Один писатель: реестр (поиск → запись → добавление в индекс) и счётчик версии должны
        # обновляться атомарно, иначе две одновременные копии одного пруфа не найдут друг друга.
        self._ingest_lock = threading.Lock()

    def _ocr_degraded(self, got: _Collected) -> list[dict[str, str]]:
        if got.images and not self.settings.ocr_enabled:
            return [{"component": "ocr", "reason": "Распознавание скриншотов выключено на этом сервере: суммы на скрине не прочитаны, "
                                                   "совпадения по картинке ищутся"}]
        if any(not r.ocr_ok for r in got.images):
            return [{"component": "ocr", "reason": "OCR недоступен: текст и суммы на скриншоте не прочитаны"}]
        return []

    # ---------- контекст из реестра и графа ----------
    def _proof_context(self, got: _Collected) -> list[Evidence]:
        out: list[Evidence] = []
        image_posts = sorted({m.post_id for r in got.images for m in r.matches if m.post_id > 0})
        text_posts = sorted({p for r in got.texts for _, p, _ in r.matches if p > 0})
        all_posts = sorted(set(image_posts) | set(text_posts) | set(got.audio_posts))
        levels = self.db.post_levels(all_posts)
        risky_img = [p for p in image_posts + got.audio_posts if levels.get(p, ("low",))[0] in RISKY_LEVELS]
        if risky_img:
            channels = sorted({c for c in (self.db.get_post(p).get("channel") for p in risky_img[:20]) if c})
            out.append(Evidence("registry.reused_proof", _major_track(levels, risky_img),
                                f"Этот пруф уже встречался в {len(set(risky_img))} постах с признаками схем",
                                REUSED_PROOF_WEIGHT + REUSED_PROOF_STEP * min(len(set(risky_img)) - 1, 4),
                                "registry", quote=", ".join(channels[:5])))
        elif image_posts:
            out.append(Evidence("registry.reused_benign", "common",
                                f"Изображение повторяется в {len(image_posts)} постах без признаков схем: повтор сам по себе не риск",
                                0, "registry"))
        risky_txt = [p for p in text_posts if levels.get(p, ("low",))[0] in RISKY_LEVELS]
        if risky_txt:
            out.append(Evidence("registry.text_template", _major_track(levels, risky_txt),
                                f"Текст почти совпадает с {len(risky_txt)} постами с признаками схем (шаблон рассылки)",
                                TEXT_TEMPLATE_WEIGHT, "registry"))
        edits = [c for r in got.images for m in r.matches for c in m.changes if c.kind in ("amount", "date")]
        if edits:
            sample = "; ".join(dict.fromkeys(f"{c.before} → {c.after}" for c in edits[:6]))
            out.append(Evidence("registry.edited_digits", "common",
                                "На копиях одного и того же пруфа отличаются суммы или даты", EDITED_DIGITS_WEIGHT,
                                "registry", quote=sample))
        digit_anoms = [a for r in got.images for a in r.anomalies if any(ch.isdigit() for ch in a.text)]
        if digit_anoms:
            out.append(Evidence("registry.ela", "common", "Признаки локальной правки изображения в зоне цифр (ELA)",
                                ELA_WEIGHT, "registry", quote=", ".join(a.text for a in digit_anoms[:3])))
        return out

    def _requisite_context(self, post_id: int, requisites: tuple[dict, ...], links: tuple[dict, ...]) -> list[Evidence]:
        out: list[Evidence] = []
        for req in requisites:
            others = [p for p in self.db.posts_with_requisite(req["key"]) if p != post_id]
            if not others:
                continue
            levels = self.db.post_levels(others)
            risky = [p for p in others if levels[p][0] in RISKY_LEVELS]
            cleared_at = self.db.requisite_cleared_at(req["key"]) if risky else None
            if cleared_at:
                # Аналитик отклонил кейс с этим реквизитом: старые посты его больше не засвечивают,
                # иначе честный магазин навсегда остаётся «встречался в схемах». Новые рискованные посты после решения — да.
                fresh = self.db.posts_created_after(risky, cleared_at)
                risky = [p for p in risky if p in fresh]
            if risky:
                tracks = sorted({levels[p][1] for p in risky if levels[p][1]})
                out.append(Evidence(f"graph.requisite.{req['kind']}", _major_track(levels, risky),
                                    f"Реквизит встречался в {len(risky)} постах с признаками схем (треки: {', '.join(tracks)})",
                                    RISKY_REQUISITE_WEIGHT, "graph", quote=req["display"]))
        return out

    # ---------- приём ----------
    def ingest(self, sub: Submission, allow_llm: bool = True) -> dict[str, Any]:
        # Сначала проверяем файлы, чтобы битая картинка не оставила пустой пост.
        images = [(up, open_image(up.data)) for up in sub.uploads if up.kind == "image"]
        # Медленное (OCR, Whisper, LLM) идёт вне общей блокировки: под ней только запись в реестр
        # и чтение контекста, поэтому параллельные загрузки не выстраиваются в очередь за OCR.
        ocr = [self.registry.read_ocr(img) for _, img in images]
        transcript, voice_failed = self._transcribe(sub)
        with self._ingest_lock:
            post_id = self.db.create_post(source=sub.source, channel=sub.channel, author=sub.author,
                                          posted_at=sub.posted_at, text=redact_cards(sub.text),
                                          external_id=sub.external_id, label=sub.label)
        try:
            return self._process(post_id, sub, images, ocr, transcript, voice_failed, allow_llm)
        except Exception as exc:
            self.db.mark_post_failed(post_id, type(exc).__name__)
            raise

    def _transcribe(self, sub: Submission) -> tuple[str | None, bool]:
        if sub.transcript:
            return sub.transcript, False
        audio = next((up for up in sub.uploads if up.kind == "audio"), None)
        if audio is None:
            return None, False
        transcript = transcribe(audio.data, "." + audio.ext)
        return transcript, transcript is None

    def _process(self, post_id: int, sub: Submission, images: list, ocr: list, transcript: str | None,
                 voice_failed: bool, allow_llm: bool = True) -> dict[str, Any]:
        got = _Collected()
        degraded: list[dict[str, str]] = []
        if voice_failed:
            degraded.append({"component": "whisper", "reason": "голосовое не расшифровано: Whisper недоступен"})
        with self._ingest_lock:
            for (up, img), (tokens, ocr_ok) in zip(images, ocr):
                result = self.registry.register_image(post_id, up.data, ocr_tokens=tokens, img=img)
                result.ocr_ok = ocr_ok
                got.images.append(result)
            for up in sub.uploads:
                if up.kind == "audio":
                    got.audio_posts.extend(self.registry.register_audio(post_id, up.data, up.ext)[1])
            if sub.text:
                text_res = self.registry.register_text(post_id, normalize_text(redact_cards(sub.text) or "").folded)
                if text_res:
                    got.texts.append(text_res)
            ocr_text = "\n".join(r.ocr_text for r in got.images if r.ocr_text) or None
            sources = [SourceText("text", sub.text or ""), SourceText("ocr", ocr_text or ""), SourceText("voice", transcript or "")]
            first = self.detector.detect(sources, allow_llm=False)
            for r in first.requisites:
                self.db.link_requisite(post_id, r.kind, r.key, r.display)
            for link in first.links:
                if _links_cases(link):
                    self.db.add_link(post_id, link.url, link.domain, link.resolved)
            context = self._proof_context(got) + self._requisite_context(post_id, first.analysis.requisites, first.analysis.links)
        degraded.extend(self._ocr_degraded(got))
        analysis = self.detector.detect(sources, context, allow_llm=allow_llm).analysis  # может звать LLM: вне блокировки
        if analysis.llm_status == "failed":
            degraded.append({"component": "llm", "reason": "LLM-арбитр не ответил, балл посчитан без него"})
        analysis = replace(analysis, degraded=tuple(degraded))
        with self._ingest_lock:
            self.db.update_post_analysis(post_id, score=analysis.score, level=analysis.level, track=analysis.track,
                                         analysis=analysis.to_dict(), ocr_text=redact_cards(ocr_text),
                                         transcript=redact_cards(transcript))
            self.version += 1
        return {
            "post_id": post_id,
            "analysis": analysis.to_dict(),
            "proofs": [
                {"artifact_id": r.artifact_id, "sha256": r.sha256, "ocr_text": redact_cards(r.ocr_text),
                 "matches": [{"artifact_id": m.artifact_id, "post_id": m.post_id, "distance": m.distance,
                              "changes": changes_to_json(m.changes)} for m in r.matches[:50]],
                 "match_count": len(r.matches),
                 "anomalies": [{"text": a.text, "box": a.box, "ratio": a.ratio} for a in r.anomalies]}
                for r in got.images
            ],
            "text_matches": [{"artifact_id": a, "post_id": p, "similarity": round(s, 3)} for r in got.texts for a, p, s in r.matches[:50]],
        }

    def analyze_only(self, text: str) -> dict[str, Any]:
        """Быстрая проверка текста без сохранения."""
        return self.check(text)["analysis"]

    def check(self, text: str | None, images: tuple[bytes, ...] = (), transcript: str | None = None,
              public: bool = False, allow_llm: bool = True) -> dict[str, Any]:
        """Проверка без сохранения (бот, дашборд): реестр и граф только читаются, поэтому
        уже засвеченный номер или скрин, встречавшийся в рискованных постах, виден и здесь.
        public=True (анонимный пользователь бота): без каналов, сумм с чужих скринов и счётчиков."""
        decoded = [(data, open_image(data)) for data in images]
        got = _Collected(images=[self.registry.lookup_image(data, img) for data, img in decoded])
        degraded = []
        degraded.extend(self._ocr_degraded(got))
        ocr_text = "\n".join(r.ocr_text for r in got.images if r.ocr_text) or ""
        sources = [SourceText("text", text or ""), SourceText("ocr", ocr_text), SourceText("voice", transcript or "")]
        first = self.detector.detect(sources, allow_llm=False)
        context = self._proof_context(got)
        # Анонимный бот не отвечает «есть ли этот номер в базе» на голый реквизит: иначе мошенник
        # проверяет, засвечена ли его карта. Контекст реестра по реквизитам только если сам текст
        # уже даёт средний риск. LLM для анонимов выключен: иначе любой может тратить бюджет API.
        if not public or first.analysis.level in RISKY_LEVELS:
            context += self._requisite_context(-1, first.analysis.requisites, first.analysis.links)
        analysis = self.detector.detect(sources, context, allow_llm=allow_llm and not public).analysis
        if analysis.llm_status == "failed":
            degraded.append({"component": "llm", "reason": "LLM-арбитр не ответил, балл посчитан без него"})
        analysis = replace(analysis, degraded=tuple(degraded))
        if public:
            return _public_view(analysis.to_dict(), got)
        return {
            "analysis": analysis.to_dict(),
            "proofs": [{"sha256": r.sha256, "match_count": len(r.matches),
                        "matches": [{"artifact_id": m.artifact_id, "post_id": m.post_id, "distance": m.distance,
                                     "changes": changes_to_json(m.changes)} for m in r.matches[:50]]}
                       for r in got.images],
        }


PUBLIC_CONTEXT_LABELS = {
    "registry.reused_proof": "Этот скрин уже встречался в постах с признаками схем",
    "registry.text_template": "Текст похож на рассылку из постов с признаками схем",
    "registry.edited_digits": "На копиях этого скрина отличаются суммы или даты",
    "registry.ela": "Есть признаки правки изображения в зоне цифр",
}


def _public_view(analysis: dict[str, Any], got: _Collected) -> dict[str, Any]:
    """Анонимному пользователю бота: только сами признаки. Каналы, суммы с чужих скринов,
    счётчики и треки из реестра не раскрываются, чтобы бот не стал справочником по базе."""
    evidence = []
    for e in analysis["evidence"]:
        if e["source"] in ("registry", "graph"):
            label = PUBLIC_CONTEXT_LABELS.get(e["feature_id"])
            if label is None and e["feature_id"].startswith("graph.requisite."):
                label = "Этот реквизит уже встречался в постах с признаками схем"
            e = {**e, "label": label or "Связь с постами с признаками схем", "quote": None, "span": None}
        evidence.append(e)
    proofs = [{"seen_before": bool(r.matches),
               "edited_copies": any(c.kind in ("amount", "date") for m in r.matches for c in m.changes)}
              for r in got.images]
    return {"analysis": {**analysis, "evidence": evidence}, "proofs": proofs}
