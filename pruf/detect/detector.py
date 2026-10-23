"""Детектор сигналов: правила + ML + LLM для спорной зоны поверх нормализованных источников."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.lexicon import TRACKS
from pruf.detect.llm import LlmArbiter
from pruf.detect.rules import find_features
from pruf.models import HIGH_THRESHOLD, MEDIUM_THRESHOLD, Analysis, Evidence
from pruf.normalize.links import Link, extract_links, resolve_shortener
from pruf.normalize.requisites import Requisite, extract_requisites
from pruf.normalize.text import normalize_text
from pruf.scoring import combine

log = logging.getLogger(__name__)
_CASINO_DOMAIN_RE = re.compile(r"(casino|kazino|slot|1xbet|1win|pin-?up|mostbet|melbet|vulkan|azino|bet\b|\.bet$)", re.I)


@dataclass(frozen=True)
class SourceText:
    source: str  # text | ocr | voice
    text: str


@dataclass(frozen=True)
class Detection:
    analysis: Analysis
    requisites: tuple[Requisite, ...]
    links: tuple[Link, ...]
    folded: str


def _link_evidence(links: list[Link]) -> list[Evidence]:
    out: list[Evidence] = []
    for link in links:
        domain = link.domain
        if link.is_shortener:
            out.append(Evidence("common.shortener", "common", "Сокращённая ссылка скрывает конечный адрес", 6, "link", link.url))
        target = link.resolved or link.url
        if _CASINO_DOMAIN_RE.search(domain) or _CASINO_DOMAIN_RE.search(target):
            out.append(Evidence("casino.domain", "casino", "Ссылка на домен казино/букмекера", 20, "link", target, core=True))
    return out


def _requisite_evidence(reqs: list[Requisite]) -> list[Evidence]:
    out: list[Evidence] = []
    if any(r.kind == "kaspi_link" for r in reqs):
        out.append(Evidence("common.kaspi_pay_link", "common", "Платёжная ссылка Kaspi в сообщении", 8, "text",
                            next(r.display for r in reqs if r.kind == "kaspi_link")))
    if any(r.kind in ("card", "phone", "iban") for r in reqs):
        r = next(r for r in reqs if r.kind in ("card", "phone", "iban"))
        out.append(Evidence("common.requisite", "common", "Реквизиты для перевода в тексте", 6, "text", r.display))
    return out


class Detector:
    def __init__(self, settings: Settings, classifier: TrackClassifier | None = None, llm: LlmArbiter | None = None):
        self._settings = settings
        self._hmac_key = settings.effective_hmac_key()
        self._classifier = classifier if classifier is not None else TrackClassifier.load(settings.model_path)
        if llm is None and settings.anthropic_api_key:
            llm = LlmArbiter(settings.anthropic_api_key, settings.llm_model)
        self._llm = llm

    @property
    def has_classifier(self) -> bool:
        return self._classifier is not None

    def detect(self, sources: list[SourceText], context: list[Evidence] | None = None) -> Detection:
        evidence: list[Evidence] = []
        requisites: list[Requisite] = []
        links: list[Link] = []
        folded_parts: list[str] = []
        req_keys: set[str] = set()
        for src in sources:
            if not src.text or not src.text.strip():
                continue
            norm = normalize_text(src.text)
            folded_parts.append(norm.folded)
            evidence.extend(find_features(norm, src.source))
            for req in extract_requisites(norm.original, self._hmac_key):
                if req.key not in req_keys:
                    req_keys.add(req.key)
                    requisites.append(req)
            found_links = extract_links(norm.original)
            if self._settings.resolve_links:
                found_links = [resolve_shortener(link) for link in found_links]
            links.extend(found_links)
        evidence.extend(_link_evidence(links))
        evidence.extend(_requisite_evidence(requisites))
        folded = "\n".join(folded_parts)
        ml = self._classifier.predict_folded(folded) if self._classifier and folded.strip() else None

        req_dicts = tuple({"kind": r.kind, "key": r.key, "display": r.display} for r in requisites)
        link_dicts = tuple({k: v for k, v in asdict(l).items() if k != "raw_span"} for l in links)
        analysis = combine(evidence, ml, context, req_dicts, link_dicts)

        if self._llm and MEDIUM_THRESHOLD <= analysis.score < HIGH_THRESHOLD:
            full_text = "\n".join(s.text for s in sources if s.text)
            verdict = self._llm.review(full_text)
            if verdict is not None:
                extra = list(verdict.evidence)
                if verdict.legit_context and not verdict.evidence:
                    extra.extend(Evidence(f"llm.legit.{t}", t, "LLM: контекст похож на легальный", -15, "llm", stop=True)
                                 for t in TRACKS)
                analysis = combine(evidence + extra, ml, context, req_dicts, link_dicts, llm_used=True)
        return Detection(analysis=analysis, requisites=tuple(requisites), links=tuple(links), folded=folded)
