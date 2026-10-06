"""Read-model types for keyword lifecycle evidence (Stage 1.20B)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

EvidenceAvailability = Literal["available", "insufficient", "unavailable"]
EvidenceRole = Literal["primary", "supporting", "diagnostic", "not_ready"]


@dataclass(frozen=True, slots=True)
class EvidenceFamilyMeta:
    availability: EvidenceAvailability
    role: EvidenceRole


@dataclass(frozen=True, slots=True)
class ScanEvidence:
    meta: EvidenceFamilyMeta
    total_scan_count: int
    successful_scan_count: int
    failed_scan_count: int
    latest_scan_at: datetime | None
    latest_scan_status: str | None
    total_raw_candidates: int
    total_unique_candidates: int
    total_persisted_videos: int


@dataclass(frozen=True, slots=True)
class DiscoveryEvidence:
    meta: EvidenceFamilyMeta
    total_discovery_hits: int
    unique_discovered_video_count: int
    new_to_database_video_count: int
    persisted_for_monitoring_count: int
    attributed_observation_count: int
    unique_candidate_rate: float | None
    persistence_rate: float | None
    new_video_rate: float | None


@dataclass(frozen=True, slots=True)
class RedundancyEvidence:
    meta: EvidenceFamilyMeta
    within_keyword_duplicate_count: int
    cross_keyword_duplicate_count: int
    duplicate_hit_count: int
    duplicate_rate: float | None
    unique_yield_rate: float | None


@dataclass(frozen=True, slots=True)
class DiscoveryVphEvidence:
    meta: EvidenceFamilyMeta
    observation_count: int
    median_discovery_vph: float | None
    p90_discovery_vph: float | None


@dataclass(frozen=True, slots=True)
class BreakoutEvidence:
    meta: EvidenceFamilyMeta
    breakout_eligible_count: int
    top_decile_breakout_count: int
    top_decile_breakout_rate: float | None
    ranking_version: str | None
    global_eligible_video_count: int | None


@dataclass(frozen=True, slots=True)
class DelayedOutcomeEvidence:
    meta: EvidenceFamilyMeta
    attributed_observation_count: int
    matured_72h_count: int
    valid_72h_outcome_count: int
    missing_72h_outcome_count: int
    median_72h_growth: float | None
    p90_72h_growth: float | None
    horizon_hours: int | None
    horizon_snapshot_tolerance_hours: float | None


@dataclass(frozen=True, slots=True)
class LifecycleContextEvidence:
    meta: EvidenceFamilyMeta
    status_changed_at: datetime | None
    status_reason: str | None
    last_manual_change_at: datetime | None
    latest_lifecycle_actor_source: str | None


@dataclass(frozen=True, slots=True)
class SchedulingEvidence:
    meta: EvidenceFamilyMeta
    last_checked: datetime | None
    next_scan_at: datetime | None
    scan_interval_seconds: int | None
    is_due: bool
    scheduling_hint: str | None


@dataclass
class KeywordEvidence:
    keyword_id: int
    keyword: str
    lifecycle_status: str
    source_type: str
    parent_keyword_id: int | None
    scan: ScanEvidence
    discovery: DiscoveryEvidence
    redundancy: RedundancyEvidence
    discovery_vph: DiscoveryVphEvidence
    breakout: BreakoutEvidence
    delayed_outcome: DelayedOutcomeEvidence
    lifecycle_context: LifecycleContextEvidence
    scheduling: SchedulingEvidence
    attribution_mode: str
    evaluated_at: datetime
    include_breakout: bool
    include_delayed: bool


@dataclass(frozen=True, slots=True)
class KeywordEvidenceListResult:
    evaluated_at: datetime
    attribution_mode: str
    include_breakout: bool
    include_delayed: bool
    ranking_version: str | None
    global_eligible_video_count: int | None
    items: list[KeywordEvidence] = field(default_factory=list)
