"""Calibration observation DTOs (Stage 1.20E). Read-only — no lifecycle writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

CalibrationReadiness = Literal["READY", "PARTIALLY_READY", "NOT_READY"]


@dataclass(frozen=True, slots=True)
class ScanCalibrationRow:
    scan_run_id: int
    keyword_id: int
    discovery_run_id: str
    started_at: datetime
    finished_at: datetime
    status: str
    raw_candidates: int
    unique_candidates: int
    persisted_videos: int
    new_to_database_video_count: int
    zero_raw_result: bool
    zero_persisted_result: bool
    zero_new_video_yield: bool
    scan_failed: bool


@dataclass(frozen=True, slots=True)
class KeywordCalibrationRow:
    keyword_id: int
    keyword: str
    lifecycle_status: str
    source_type: str
    parent_keyword_id: int | None
    created_at: datetime | None
    status_changed_at: datetime | None
    total_scan_count: int
    successful_scan_count: int
    failed_scan_count: int
    first_scan_at: datetime | None
    latest_scan_at: datetime | None
    scan_span_hours: float | None
    total_raw_candidates: int
    total_unique_candidates: int
    total_persisted_videos: int
    unique_discovered_video_count: int
    new_to_database_video_count: int
    successful_zero_yield_scan_count: int
    zero_yield_rate: float | None
    consecutive_zero_yield_scans_at_end: int
    max_consecutive_zero_yield_scans: int
    within_keyword_duplicate_count: int
    cross_keyword_duplicate_count: int
    duplicate_rate: float | None
    unique_yield_rate: float | None
    new_video_rate: float | None
    discovery_vph_observation_count: int
    median_discovery_vph: float | None
    p90_discovery_vph: float | None
    max_discovery_vph: float | None
    breakout_eligible_count: int
    top_decile_breakout_count: int
    top_decile_breakout_rate: float | None
    attributed_observation_count: int
    matured_72h_count: int
    valid_72h_outcome_count: int
    missing_72h_outcome_count: int
    median_absolute_view_growth_72h: float | None
    p90_absolute_view_growth_72h: float | None
    recommendation: str
    recommendation_confidence: str
    recommendation_reason_code: str
    calibration_required: bool
    maturity_group: str


@dataclass(frozen=True, slots=True)
class SpearmanAssociation:
    pair_label: str
    n: int
    rho: float | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RuleReadinessItem:
    rule_id: str
    readiness: CalibrationReadiness
    required_evidence: str
    current_sample_size: int
    missing_evidence: str
    recommendation: str


@dataclass
class KeywordLifecycleCalibrationReport:
    generated_at: datetime
    attribution_mode: str
    include_breakout: bool
    include_delayed: bool
    keyword_count: int
    scan_row_count: int
    maturity_group_counts: dict[str, int]
    recommendation_counts: dict[str, int]
    recommendation_by_lifecycle: dict[str, dict[str, int]]
    zero_yield_by_maturity: dict[str, Any]
    yield_distribution: dict[str, Any]
    vph_analysis: dict[str, Any]
    breakout_analysis: dict[str, Any]
    outcome_72h_coverage: dict[str, Any]
    associations: list[SpearmanAssociation] = field(default_factory=list)
    readiness: list[RuleReadinessItem] = field(default_factory=list)
    case_review: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    production_findings: list[str] = field(default_factory=list)
    keyword_rows: list[KeywordCalibrationRow] = field(default_factory=list)
    scan_rows: list[ScanCalibrationRow] = field(default_factory=list)
