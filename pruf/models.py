"""Общие структуры результата анализа."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LEVEL_LOW = "low"
LEVEL_MEDIUM = "medium"
LEVEL_HIGH = "high"
LEVEL_LABELS = {LEVEL_LOW: "низкий", LEVEL_MEDIUM: "средний", LEVEL_HIGH: "высокий"}
MEDIUM_THRESHOLD = 35
HIGH_THRESHOLD = 65


def level_for(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return LEVEL_HIGH
    if score >= MEDIUM_THRESHOLD:
        return LEVEL_MEDIUM
    return LEVEL_LOW


@dataclass(frozen=True)
class Evidence:
    feature_id: str
    track: str
    label: str
    weight: float
    source: str  # text | ocr | qr | voice | link | registry | graph | ml | llm
    quote: str = ""
    span: tuple[int, int] | None = None
    stop: bool = False
    core: bool = False


@dataclass(frozen=True)
class TrackScore:
    track: str
    score: float
    level: str
    rule_points: float
    ml_probability: float | None
    capped_reason: str | None = None


@dataclass(frozen=True)
class Analysis:
    score: float
    level: str
    track: str | None
    tracks: tuple[TrackScore, ...]
    evidence: tuple[Evidence, ...]
    summary: str
    requisites: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    links: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    llm_status: str = "off"  # off | not_needed | ok | legit | failed
    degraded: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level_label"] = LEVEL_LABELS[self.level]
        return data
