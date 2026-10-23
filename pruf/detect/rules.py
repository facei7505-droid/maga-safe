"""Поиск признаков из словаря в нормализованном тексте, с цитатами из оригинала."""

from __future__ import annotations

import re
from functools import lru_cache

from pruf.detect.lexicon import FEATURES, Feature
from pruf.models import Evidence
from pruf.normalize.text import NormText

QUOTE_CONTEXT = 25
MAX_QUOTES_PER_FEATURE = 2
# Цитата внутри поста: «вы выиграли iPhone, оплатите доставку». В предупреждении это пересказ схемы, а не сама схема
_QUOTED_RE = re.compile(r"«[^»\n]{1,300}»|“[^”\n]{1,300}”|„[^“\n]{1,300}“|\"[^\"\n]{1,300}\"")


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[Feature, tuple], ...]:
    return tuple((f, f.compiled()) for f in FEATURES)


def find_features(text: NormText, source: str = "text") -> list[Evidence]:
    """Все срабатывания признаков; один признак может дать до двух цитат."""
    found: list[Evidence] = []
    if not text.folded.strip():
        return found
    for feature, patterns in _compiled():
        hits = 0
        seen_spans: set[tuple[int, int]] = set()
        for pattern in patterns:
            for match in pattern.finditer(text.folded):
                if hits >= MAX_QUOTES_PER_FEATURE:
                    break
                span = text.original_span(match.start(), match.end())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                found.append(Evidence(
                    feature_id=feature.id, track=feature.track, label=feature.label, weight=feature.weight,
                    source=source, quote=text.quote(match.start(), match.end(), QUOTE_CONTEXT), span=span,
                    stop=feature.stop, core=feature.core,
                ))
                hits += 1
    return _drop_quoted_in_warnings(found, text.original)


def _drop_quoted_in_warnings(found: list[Evidence], original: str) -> list[Evidence]:
    """В посте-предупреждении признаки, целиком попавшие в кавычки, не считаются: это цитата мошенников."""
    if not any(e.stop and e.feature_id.endswith(".awareness") for e in found):
        return found
    quoted = [m.span() for m in _QUOTED_RE.finditer(original)]
    if not quoted:
        return found
    return [e for e in found
            if e.stop or not e.span or not any(qs <= e.span[0] and e.span[1] <= qe for qs, qe in quoted)]
