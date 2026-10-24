"""Детектор сигналов: правила + ML + LLM для спорной зоны поверх нормализованных источников."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.llm import LlmArbiter
from pruf.detect.rules import find_features
from pruf.models import HIGH_THRESHOLD, Analysis, Evidence
from pruf.normalize.links import (
    ALLOWLIST_DOMAINS,
    MAX_RESOLVE_PER_POST,
    Link,
    extract_links,
    resolve_shortener,
)
from pruf.normalize.requisites import Requisite, extract_requisites, redact_cards
from pruf.normalize.text import normalize_text
from pruf.scoring import LLM_LEGIT, combine

# Спорная зона для LLM: от «один признак упёрся в потолок» (20–34) до нижней части высокого риска (65–74),
# где чаще всего ложные срабатывания на легальных сборах и платных мероприятиях
LLM_ZONE = (20.0, HIGH_THRESHOLD + 10.0)
log = logging.getLogger(__name__)
# Только по имени хоста, не по пути: «gov.kz/news/kazino-zapret» не казино. «bet» только целой меткой
# (bet.kz, jet-casino.bet, bet-777.top), иначе ловятся alphabet.com и tibet.kz.
_CASINO_DOMAIN_RE = re.compile(r"casino|kazino|slot|1xbet|1win|pin-?up|mostbet|melbet|vulkan|azino|(?:^|[.\-])bet(?=$|[.\-\d])", re.IGNORECASE)


# Бренды, которыми прикрываются фальшивые розыгрыши, и их настоящие домены
_BRAND_DOMAINS = {
    "kaspi": ("kaspi.kz",), "halyk": ("halykbank.kz", "homebank.kz"), "magnum": ("magnum.kz",), "egov": ("egov.kz",),
    "kazpost": ("post.kz", "kazpost.kz"), "jusan": ("jusan.kz",), "freedom": ("ffin.kz", "freedombank.kz"),
    "kcell": ("kcell.kz",), "beeline": ("beeline.kz",), "tele2": ("tele2.kz",), "sattilik": ("sattilik.kz",),
    "airastana": ("airastana.com",),
}


def _brand_lookalike(host: str) -> str | None:
    for brand, official in _BRAND_DOMAINS.items():
        if brand in host and not any(host == d or host.endswith("." + d) for d in official):
            return brand
    return None


def _host(url: str) -> str:
    return (urlsplit(url if "://" in url else "http://" + url).hostname or "").lower()


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
        hosts = {domain.lower(), _host(target)} - ALLOWLIST_DOMAINS - {""}
        if any(_CASINO_DOMAIN_RE.search(h) for h in hosts):
            out.append(Evidence("casino.domain", "casino", "Ссылка на домен казино/букмекера", 20, "link", target, core=True))
        brand = next((b for h in hosts if (b := _brand_lookalike(h))), None)
        if brand:
            out.append(Evidence("common.brand_lookalike", "common", f"Домен похож на {brand}, но не официальный", 14, "link", target))
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

    def llm_state(self) -> dict[str, Any]:
        if self._llm is None:
            return {"configured": False}
        return {"configured": True, **self._llm.stats()}

    def detect(self, sources: list[SourceText], context: list[Evidence] | None = None, allow_llm: bool = True) -> Detection:
        evidence: list[Evidence] = []
        requisites: list[Requisite] = []
        links: list[Link] = []
        folded_parts: list[str] = []
        req_keys: set[str] = set()
        for src in sources:
            if not src.text or not src.text.strip():
                continue
            # Признаки и цитаты считаем по тексту с замаскированными картами: полный номер
            # не должен попасть ни в базу, ни в экспорт, ни в LLM. Реквизиты берём из оригинала.
            norm = normalize_text(redact_cards(src.text) or "")
            folded_parts.append(norm.folded)
            src_reqs = extract_requisites(src.text, self._hmac_key)
            found_links = extract_links(norm.original)
            evidence.extend(find_features(norm, src.source, keep_quoted=bool(src_reqs or found_links)))
            for req in src_reqs:
                if req.key not in req_keys:
                    req_keys.add(req.key)
                    requisites.append(req)
            if self._settings.resolve_links:
                found_links = [resolve_shortener(link) if i < MAX_RESOLVE_PER_POST else link
                               for i, link in enumerate(found_links)]
            links.extend(found_links)
        evidence.extend(_link_evidence(links))
        evidence.extend(_requisite_evidence(requisites))
        folded = "\n".join(folded_parts)
        ml = self._classifier.predict_folded(folded) if self._classifier and folded.strip() else None

        req_dicts = tuple({"kind": r.kind, "key": r.key, "display": r.display} for r in requisites)
        link_dicts = tuple({k: v for k, v in asdict(l).items() if k != "raw_span"} for l in links)
        llm_status = "off" if self._llm is None else "not_needed"
        analysis = combine(evidence, ml, context, req_dicts, link_dicts, llm_status=llm_status)

        if allow_llm and self._llm and LLM_ZONE[0] <= analysis.score < LLM_ZONE[1]:
            full_text = "\n".join(redact_cards(s.text) or "" for s in sources if s.text)
            verdict = self._llm.review(full_text)
            extra: list[Evidence] = []
            if verdict is None:
                llm_status = "failed"
            else:
                llm_status = "ok"
                extra = list(verdict.evidence)
                if verdict.legit_context and not verdict.evidence:
                    # Вето ограничено в scoring.py: при реквизите или ссылке мнение LLM балл не снижает
                    extra.append(Evidence(LLM_LEGIT, "common", "LLM: контекст похож на легальный", 0, "llm"))
            analysis = combine(evidence + extra, ml, context, req_dicts, link_dicts, llm_status=llm_status)
        return Detection(analysis=analysis, requisites=tuple(requisites), links=tuple(links), folded=folded)
