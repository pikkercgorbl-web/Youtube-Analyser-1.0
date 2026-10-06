"""DTOs for keyword expansion (Stage 1.16C)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class KeywordExpansionCandidate:
    keyword: str
    normalized_keyword: str
    source_type: str
    parent_keyword_id: int
    parent_keyword: str
    source_reference: str | None = None
    discovered_at: datetime | None = None
    confidence_hint: str | None = None
    metadata: dict[str, Any] | None = None


class KeywordExpansionContext(Protocol):
    parent_keyword_id: int
    parent_keyword: str


@dataclass(frozen=True, slots=True)
class SimpleExpansionContext:
    parent_keyword_id: int
    parent_keyword: str


class KeywordExpansionSource(Protocol):
    source_type: str

    async def expand(
        self,
        seed_keyword: str,
        context: SimpleExpansionContext,
    ) -> list[KeywordExpansionCandidate]:
        ...


@dataclass
class KeywordExpansionSummary:
    discovery_run_id: str
    seed_keyword_count: int = 0
    source_count: int = 0
    raw_candidate_count: int = 0
    normalized_unique_count: int = 0
    existing_keyword_count: int = 0
    rejected_count: int = 0
    deferred_count: int = 0
    created_keyword_count: int = 0
    per_source_counts: dict[str, int] = field(default_factory=dict)
    per_seed_counts: dict[int, int] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    runtime_seconds: float = 0.0
    cycle_status: str = "ok"
