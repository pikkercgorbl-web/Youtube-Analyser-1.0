"""Advisory lifecycle recommendation DTOs (Stage 1.20D). No scores; no writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

LifecycleRecommendationKind = Literal[
    "insufficient_evidence",
    "keep",
    "preliminary_review",
    "promote_active",
    "move_weak",
    "archive_candidate",
    "restore_active",
]

RecommendationConfidence = Literal["none", "preliminary"]


@dataclass(frozen=True, slots=True)
class KeywordLifecycleRecommendation:
    keyword_id: int
    keyword: str
    lifecycle_status: str
    recommendation: LifecycleRecommendationKind
    confidence: RecommendationConfidence
    reason_code: str
    human_reason: str
    calibration_required: bool
    suggested_transition: str | None
    evidence_facts: tuple[str, ...] = ()
    evaluated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class KeywordLifecycleRecommendationListResult:
    evaluated_at: datetime
    attribution_mode: str
    items: tuple[KeywordLifecycleRecommendation, ...] = field(default_factory=tuple)
