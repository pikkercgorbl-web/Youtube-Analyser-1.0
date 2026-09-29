"""T0 cohort export and enrichment diagnostics for validation scans (Stage 1.8 Step 3)."""

from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_candidate import (
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)
from app.services.radar_candidate_dataset import count_candidate_states, validate_dataset_invariants

T0_SCHEMA_VERSION = "1.8"
T0_SCHEMA_VERSION_WITH_BASELINE = "1.10A"

T0_DISCOVERY_FIELDS = (
    "video_id",
    "channel_id",
    "keyword",
    "video_title",
    "channel_title",
    "discovered_at",
    "discovery_views",
    "discovery_subscribers",
    "discovery_published_text",
    "discovery_source",
    "is_short",
    "is_live",
    "content_renderer",
)

T0_ENRICHMENT_FIELDS = (
    "final_subscribers",
    "subscriber_fetch_status",
    "published_at",
    "age_hours_at_t0",
    "vph_at_t0",
    "views_per_subscriber_at_t0",
    "duration_seconds",
    "content_format",
    "enrichment_status",
)

T0_QUALIFICATION_FIELDS = (
    "qualification_state",
    "first_failure_reason",
)

T0_JSONL_FIELDS = T0_DISCOVERY_FIELDS + T0_ENRICHMENT_FIELDS + T0_QUALIFICATION_FIELDS

T0_CHANNEL_BASELINE_FIELDS = (
    "channel_baseline_status",
    "channel_baseline_requested_count",
    "channel_baseline_found_count",
    "channel_baseline_eligible_count",
    "channel_baseline_leakage_violations",
    "channel_history_count",
    "channel_median_views",
    "channel_p75_views",
    "channel_p90_views",
    "channel_max_views",
    "views_vs_channel_median",
    "views_vs_channel_p75",
    "channel_median_early_vph",
    "channel_p75_early_vph",
    "channel_p90_early_vph",
    "vph_vs_channel_median",
    "vph_vs_channel_p75",
    "velocity_baseline_status",
    "channel_subscribers_at_t0",
    "subscriber_status",
    "channel_baseline_source",
    "channel_baseline_collected_at",
    "channel_baseline_history_cutoff",
    "channel_view_baseline_available",
    "channel_velocity_baseline_available",
)


def serialize_t0_candidate(candidate: RadarCandidate) -> dict[str, Any]:
    """Serialize one candidate for cohort_T0 JSONL (discovery + enrichment + qualification only)."""
    return {
        "video_id": candidate.video_id,
        "channel_id": candidate.channel_id,
        "keyword": candidate.keyword,
        "video_title": candidate.video_title,
        "channel_title": candidate.channel_title,
        "discovered_at": candidate.discovered_at.isoformat(),
        "discovery_views": candidate.discovery_views,
        "discovery_subscribers": candidate.discovery_subscribers,
        "discovery_published_text": candidate.discovery_published_text,
        "discovery_source": candidate.discovery_source,
        "is_short": candidate.is_short,
        "is_live": candidate.is_live,
        "content_renderer": candidate.content_renderer,
        "final_subscribers": candidate.final_subscribers,
        "subscriber_fetch_status": candidate.subscriber_fetch_status,
        "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
        "age_hours_at_t0": candidate.age_hours_at_t0,
        "vph_at_t0": candidate.vph_at_t0,
        "views_per_subscriber_at_t0": candidate.views_per_subscriber_at_t0,
        "duration_seconds": candidate.duration_seconds,
        "content_format": candidate.content_format,
        "enrichment_status": candidate.enrichment_status,
        "qualification_state": candidate.qualification_state,
        "first_failure_reason": candidate.first_failure_reason,
    }


def serialize_t0_candidate_with_baseline(candidate: RadarCandidate) -> dict[str, Any]:
    """T0 JSONL row including channel baseline fields when capture ran."""
    row = serialize_t0_candidate(candidate)
    if candidate.channel_baseline_status is None:
        return row
    for field_name in T0_CHANNEL_BASELINE_FIELDS:
        row[field_name] = getattr(candidate, field_name, None)
    return row


def _sanitize_keyword_for_filename(keyword: str) -> str:
    sanitized = re.sub(r"[^\w\-]+", "_", keyword.strip().lower())
    return sanitized.strip("_") or "keyword"


def build_enrichment_summary(
    candidates: list[RadarCandidate],
    *,
    missing_video_count: int = 0,
) -> dict[str, Any]:
    """Aggregate post-discovery enrichment coverage for validation diagnostics."""
    enrichment_ok = enrichment_partial = enrichment_failed = 0
    published_at_available = 0
    duration_available = 0
    age_hours_available = 0
    vph_available = 0
    final_subscribers_available = 0
    views_per_subscriber_available = 0
    regular_count = short_count = live_count = unknown_count = 0

    for candidate in candidates:
        status = candidate.enrichment_status
        if status == "ok":
            enrichment_ok += 1
        elif status == "partial":
            enrichment_partial += 1
        elif status == "failed":
            enrichment_failed += 1

        if candidate.published_at is not None:
            published_at_available += 1
        if candidate.duration_seconds is not None:
            duration_available += 1
        if candidate.age_hours_at_t0 is not None:
            age_hours_available += 1
        if candidate.vph_at_t0 is not None:
            vph_available += 1
        if candidate.final_subscribers is not None:
            final_subscribers_available += 1
        if candidate.views_per_subscriber_at_t0 is not None:
            views_per_subscriber_available += 1

        content_format = candidate.content_format
        if content_format == "regular":
            regular_count += 1
        elif content_format == "short":
            short_count += 1
        elif content_format == "live":
            live_count += 1
        else:
            unknown_count += 1

    return {
        "candidates_total": len(candidates),
        "enrichment_ok": enrichment_ok,
        "enrichment_partial": enrichment_partial,
        "enrichment_failed": enrichment_failed,
        "missing_video": missing_video_count,
        "published_at_available": published_at_available,
        "duration_available": duration_available,
        "age_hours_available": age_hours_available,
        "vph_available": vph_available,
        "final_subscribers_available": final_subscribers_available,
        "views_per_subscriber_available": views_per_subscriber_available,
        "regular_count": regular_count,
        "short_count": short_count,
        "live_count": live_count,
        "unknown_count": unknown_count,
    }


def count_format_violations(candidates: list[RadarCandidate]) -> int:
    return sum(1 for candidate in candidates if candidate.is_short or candidate.is_live)


def is_experiment_regular_candidate(candidate: RadarCandidate) -> bool:
    """Experiment cohort accepts only post-enrichment regular videos."""
    return candidate.content_format == "regular"


def split_raw_and_regular(
    candidates: list[RadarCandidate],
) -> tuple[list[RadarCandidate], list[RadarCandidate]]:
    """Return (all raw candidates, regular-only experiment subset)."""
    regular = [candidate for candidate in candidates if is_experiment_regular_candidate(candidate)]
    return candidates, regular


def count_excluded_after_enrichment(candidates: list[RadarCandidate]) -> int:
    return sum(1 for candidate in candidates if not is_experiment_regular_candidate(candidate))


def _numeric_distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "median": round(statistics.median(values), 4),
        "max": round(max(values), 4),
    }


def build_regular_distribution_stats(
    regular_candidates: list[RadarCandidate],
) -> dict[str, Any]:
    """Distribution stats for stratified sampling inspection (regular subset only)."""
    views: list[float] = []
    vph: list[float] = []
    vps: list[float] = []
    age: list[float] = []
    subs: list[float] = []

    for candidate in regular_candidates:
        views.append(float(candidate.discovery_views))
        if candidate.vph_at_t0 is not None:
            vph.append(float(candidate.vph_at_t0))
        if candidate.views_per_subscriber_at_t0 is not None:
            vps.append(float(candidate.views_per_subscriber_at_t0))
        if candidate.age_hours_at_t0 is not None:
            age.append(float(candidate.age_hours_at_t0))
        if candidate.final_subscribers is not None:
            subs.append(float(candidate.final_subscribers))

    return {
        "discovery_views": _numeric_distribution(views),
        "vph_at_t0": _numeric_distribution(vph),
        "views_per_subscriber_at_t0": _numeric_distribution(vps),
        "age_hours_at_t0": _numeric_distribution(age),
        "final_subscribers": _numeric_distribution(subs),
    }


def build_keyword_meta_payload(
    *,
    keyword: str,
    dataset_path: Path,
    candidates: list[RadarCandidate],
    enrichment_summary: dict[str, Any],
    dataset_summary: dict[str, Any],
    duration_seconds: float,
    source: str,
    timestamp: datetime,
    missing_video_count: int = 0,
) -> dict[str, Any]:
    """Build per-keyword meta.json payload with raw/regular split."""
    _, regular_candidates = split_raw_and_regular(candidates)
    excluded = count_excluded_after_enrichment(candidates)
    regular_enrichment = build_enrichment_summary(
        regular_candidates,
        missing_video_count=0,
    )
    regular_counts = count_candidate_states(regular_candidates)

    return {
        "keyword": keyword,
        "timestamp": timestamp.isoformat(),
        "schema_version": T0_SCHEMA_VERSION,
        "source": source,
        "dataset_path": str(dataset_path),
        "duration_seconds": round(duration_seconds, 2),
        "raw_candidates": len(candidates),
        "regular_candidates": len(regular_candidates),
        "excluded_after_enrichment": excluded,
        "candidate_count": dataset_summary["candidate_count"],
        "passed": dataset_summary["passed"],
        "rejected": dataset_summary["rejected"],
        "parse_errors": dataset_summary["parse_errors"],
        "format_violations": dataset_summary["format_violations"],
        "regular_format_violations": count_format_violations(regular_candidates),
        "invariant_ok": dataset_summary["invariant_ok"],
        "enrichment_summary": enrichment_summary,
        "regular_enrichment_summary": regular_enrichment,
        "regular_qualification": {
            "passed": regular_counts["passed"],
            "rejected": regular_counts["rejected"],
            "parse_errors": regular_counts["parse_errors"],
        },
        "distribution_regular": build_regular_distribution_stats(regular_candidates),
        "missing_video_count": missing_video_count,
    }


def export_cohort_t0_meta(
    meta_payload: dict[str, Any],
    *,
    keyword: str,
    output_dir: Path,
    timestamp: datetime,
) -> Path:
    stamp = timestamp.strftime("%Y%m%d_%H%M%S")
    safe_keyword = _sanitize_keyword_for_filename(keyword)
    meta_path = output_dir / f"cohort_T0_{stamp}_{safe_keyword}_meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta_path


def build_t0_dataset_summary(
    *,
    path: Path,
    keyword: str,
    candidates: list[RadarCandidate],
) -> dict[str, Any]:
    """Build dataset summary with qualification counts and invariant check."""
    counts = count_candidate_states(candidates)
    candidate_count = len(candidates)
    passed = counts["passed"]
    rejected = counts["rejected"]
    parse_errors = counts["parse_errors"]
    format_violations = count_format_violations(candidates)
    invariant_ok = candidate_count == passed + rejected + parse_errors

    return {
        "path": str(path),
        "keyword": keyword,
        "schema_version": T0_SCHEMA_VERSION,
        "candidate_count": candidate_count,
        "passed": passed,
        "rejected": rejected,
        "parse_errors": parse_errors,
        "format_violations": format_violations,
        "invariant_ok": invariant_ok,
    }


def export_cohort_t0_jsonl(
    candidates: list[RadarCandidate],
    *,
    keyword: str,
    output_dir: Path,
    timestamp: datetime | None = None,
) -> Path:
    """Write cohort_T0 JSONL without mutating candidates or touching the database."""
    validate_dataset_invariants(candidates)
    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    safe_keyword = _sanitize_keyword_for_filename(keyword)
    output_path = output_dir / f"cohort_T0_{stamp}_{safe_keyword}.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(serialize_t0_candidate(candidate), ensure_ascii=False))
            handle.write("\n")

    return output_path


def persist_validation_t0_dataset(
    candidates: list[RadarCandidate],
    *,
    keyword: str,
    output_dir: Path,
    missing_video_count: int = 0,
    timestamp: datetime | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """
    Export full T0 cohort and return path plus enrichment/dataset summaries.

    Raises ValueError if qualification invariant fails.
    """
    path = export_cohort_t0_jsonl(
        candidates,
        keyword=keyword,
        output_dir=output_dir,
        timestamp=timestamp,
    )
    enrichment_summary = build_enrichment_summary(
        candidates,
        missing_video_count=missing_video_count,
    )
    dataset_summary = build_t0_dataset_summary(
        path=path,
        keyword=keyword,
        candidates=candidates,
    )
    if not dataset_summary["invariant_ok"]:
        raise ValueError(
            "T0 dataset invariant failed: "
            f"candidate_count={dataset_summary['candidate_count']} != "
            f"passed+rejected+parse_errors="
            f"{dataset_summary['passed'] + dataset_summary['rejected'] + dataset_summary['parse_errors']}",
        )
    return path, enrichment_summary, dataset_summary


def persist_keyword_t0_outputs(
    candidates: list[RadarCandidate],
    *,
    keyword: str,
    output_dir: Path,
    source: str,
    duration_seconds: float,
    missing_video_count: int = 0,
    timestamp: datetime | None = None,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Export raw T0 JSONL, per-keyword meta, and return summaries."""
    ts = timestamp or datetime.now(timezone.utc)
    jsonl_path, enrichment_summary, dataset_summary = persist_validation_t0_dataset(
        candidates,
        keyword=keyword,
        output_dir=output_dir,
        missing_video_count=missing_video_count,
        timestamp=ts,
    )
    meta_payload = build_keyword_meta_payload(
        keyword=keyword,
        dataset_path=jsonl_path,
        candidates=candidates,
        enrichment_summary=enrichment_summary,
        dataset_summary=dataset_summary,
        duration_seconds=duration_seconds,
        source=source,
        timestamp=ts,
        missing_video_count=missing_video_count,
    )
    meta_path = export_cohort_t0_meta(
        meta_payload,
        keyword=keyword,
        output_dir=output_dir,
        timestamp=ts,
    )
    return jsonl_path, meta_path, meta_payload, enrichment_summary, dataset_summary
