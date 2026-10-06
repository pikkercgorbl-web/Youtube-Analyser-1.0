"""Admission decision DTOs (Stage 1.20C). Facts and policy outcomes only — no quality score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AdmissionDecisionKind = Literal["accept", "reject", "defer", "existing"]


@dataclass(frozen=True, slots=True)
class AdmissionContext:
    """Inspectability bag for admission audits (not a score)."""

    filter_reason: str | None = None
    existing_lifecycle_status: str | None = None
    pool_non_archived_count: int | None = None
    pool_probation_count: int | None = None
    parent_accepted_this_run: int | None = None
    global_accepted_this_run: int | None = None
    expansion_depth: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KeywordAdmissionDecision:
    normalized_keyword: str
    decision: AdmissionDecisionKind
    reason_code: str
    human_reason: str
    source_type: str
    parent_keyword_id: int
    existing_keyword_id: int | None = None
    admission_context: AdmissionContext = field(default_factory=AdmissionContext)
