"""Serialize and export in-memory RadarCandidate datasets (Stage 1.5)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_candidate import (
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)

DATASET_SCHEMA_VERSION = "1.5"


@dataclass(frozen=True, slots=True)
class CandidateDatasetMetadata:
    timestamp: str
    keywords: list[str]
    total_candidates: int
    total_passed: int
    total_rejected: int
    total_parse_errors: int
    source: str
    schema_version: str = DATASET_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def serialize_candidate(candidate: RadarCandidate) -> dict[str, Any]:
    """Convert one RadarCandidate to a JSON-serializable record."""
    subscribers = candidate.subscribers
    return {
        "keyword": candidate.keyword,
        "video_id": candidate.video_id,
        "channel_id": candidate.channel_id,
        "video_title": candidate.video_title,
        "channel_title": candidate.channel_title,
        "discovery_views": candidate.discovery_views,
        "discovery_subscribers": candidate.discovery_subscribers,
        "discovery_published_text": candidate.discovery_published_text,
        "final_subscribers": candidate.final_subscribers,
        "subscriber_fetch_status": candidate.subscriber_fetch_status,
        "published_text": candidate.published_text,
        "views": candidate.views,
        "subscribers": subscribers if subscribers is not None else None,
        "video_age_days": candidate.video_age_days,
        "vph": candidate.vph,
        "viral_coefficient": candidate.viral_coefficient,
        "qualification_state": candidate.qualification_state,
        "first_failure_reason": candidate.first_failure_reason,
        "discovery_source": candidate.discovery_source,
        "discovered_at": candidate.discovered_at.isoformat(),
        "is_short": candidate.is_short,
        "is_live": candidate.is_live,
        "content_renderer": candidate.content_renderer,
        "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
        "age_hours_at_t0": candidate.age_hours_at_t0,
        "vph_at_t0": candidate.vph_at_t0,
        "views_per_subscriber_at_t0": candidate.views_per_subscriber_at_t0,
        "duration_seconds": candidate.duration_seconds,
        "content_format": candidate.content_format,
        "enrichment_status": candidate.enrichment_status,
    }


def count_candidate_states(candidates: list[RadarCandidate]) -> dict[str, int]:
    passed = rejected = parse_errors = pending = 0
    for candidate in candidates:
        if candidate.qualification_state == QUALIFICATION_PASSED:
            passed += 1
        elif candidate.qualification_state == QUALIFICATION_REJECTED:
            rejected += 1
        elif candidate.qualification_state == QUALIFICATION_PARSE_ERROR:
            parse_errors += 1
        else:
            pending += 1
    return {
        "passed": passed,
        "rejected": rejected,
        "parse_errors": parse_errors,
        "pending": pending,
    }


def validate_dataset_invariants(candidates: list[RadarCandidate]) -> None:
    """Ensure candidate state counts are internally consistent."""
    counts = count_candidate_states(candidates)
    if counts["pending"]:
        raise ValueError(
            f"Dataset contains {counts['pending']} pending candidates without outcomes",
        )
    total = len(candidates)
    accounted = counts["passed"] + counts["rejected"] + counts["parse_errors"]
    if total != accounted:
        raise ValueError(
            f"Dataset invariant failed: {total} candidates != "
            f"{accounted} accounted (passed/rejected/parse_errors)",
        )


def build_dataset_metadata(
    *,
    keywords: list[str],
    candidates: list[RadarCandidate],
    source: str,
    timestamp: datetime | None = None,
) -> CandidateDatasetMetadata:
    counts = count_candidate_states(candidates)
    return CandidateDatasetMetadata(
        timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
        keywords=keywords,
        total_candidates=len(candidates),
        total_passed=counts["passed"],
        total_rejected=counts["rejected"],
        total_parse_errors=counts["parse_errors"],
        source=source,
    )


def export_candidates_jsonl(
    candidates: list[RadarCandidate],
    output_path: Path,
) -> None:
    """Write one JSON object per line without mutating candidates."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(serialize_candidate(candidate), ensure_ascii=False))
            handle.write("\n")


def export_candidate_dataset(
    candidates: list[RadarCandidate],
    *,
    keywords: list[str],
    output_dir: Path,
    source: str,
    timestamp: datetime | None = None,
) -> tuple[Path, Path]:
    """Export JSONL dataset and companion metadata JSON."""
    validate_dataset_invariants(candidates)
    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"radar_candidates_{stamp}.jsonl"
    meta_path = output_dir / f"radar_candidates_{stamp}_meta.json"

    export_candidates_jsonl(candidates, jsonl_path)
    metadata = build_dataset_metadata(
        keywords=keywords,
        candidates=candidates,
        source=source,
        timestamp=ts,
    )
    meta_path.write_text(
        json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return jsonl_path, meta_path
