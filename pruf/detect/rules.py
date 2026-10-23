"""Поиск признаков из словаря в нормализованном тексте, с цитатами из оригинала."""

from __future__ import annotations

from functools import lru_cache

from pruf.detect.lexicon import FEATURES, Feature
from pruf.models import Evidence
from pruf.normalize.text import NormText

QUOTE_CONTEXT = 25
MAX_QUOTES_PER_FEATURE = 2


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
    return found
