"""Candidate distribution diagnostics for one keyword scan (Stage 1.3)."""

from __future__ import annotations

from typing import Any

from app.services.radar_candidate import (
    QUALIFICATION_PARSE_ERROR,
    QUALIFICATION_PASSED,
    QUALIFICATION_REJECTED,
    RadarCandidate,
)

SIGNAL_FIELDS = ("views", "vph", "video_age_days", "viral_coefficient")
DEFAULT_SAMPLE_LIMIT = 3


def _signal_value(candidate: RadarCandidate, field: str) -> int | float | None:
    if field == "views":
        return candidate.views
    return getattr(candidate, field)


def _signal_stats(values: list[int | float]) -> dict[str, int | float]:
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
    }


def _group_distribution(candidates: list[RadarCandidate]) -> dict[str, Any]:
    result: dict[str, Any] = {"count": len(candidates)}
    for field in SIGNAL_FIELDS:
        values = [
            value
            for candidate in candidates
            if (value := _signal_value(candidate, field)) is not None
        ]
        if values:
            result[field] = _signal_stats(values)
    return result


def _build_signal_availability(candidates: list[RadarCandidate]) -> dict[str, int]:
    availability = {
        "views": 0,
        "subscribers": 0,
        "viral_coefficient": 0,
        "vph": 0,
        "video_age_days": 0,
    }
    for candidate in candidates:
        if candidate.views is not None:
            availability["views"] += 1
        if candidate.subscribers is not None:
            availability["subscribers"] += 1
        if candidate.viral_coefficient is not None:
            availability["viral_coefficient"] += 1
        if candidate.vph is not None:
            availability["vph"] += 1
        if candidate.video_age_days is not None:
            availability["video_age_days"] += 1
    return availability


def _candidate_sample(candidate: RadarCandidate) -> dict[str, Any]:
    return {
        "title": candidate.video_title,
        "views": candidate.views,
        "subscribers": candidate.subscribers,
        "vph": candidate.vph,
        "video_age_days": candidate.video_age_days,
        "viral_coefficient": candidate.viral_coefficient,
    }


def build_candidate_distribution(
    keyword: str,
    candidates: list[RadarCandidate],
    *,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Aggregate candidate signals by outcome group (read-only, no qualification logic)."""
    passed = [c for c in candidates if c.qualification_state == QUALIFICATION_PASSED]
    rejected = [c for c in candidates if c.qualification_state == QUALIFICATION_REJECTED]
    parse_errors = [c for c in candidates if c.qualification_state == QUALIFICATION_PARSE_ERROR]

    filter_skip_reasons: dict[str, int] = {}
    for candidate in rejected + parse_errors:
        reason = candidate.first_failure_reason
        if not reason:
            continue
        filter_skip_reasons[reason] = filter_skip_reasons.get(reason, 0) + 1

    groups: dict[str, dict[str, Any]] = {
        "all": _group_distribution(candidates),
        "passed": _group_distribution(passed),
    }

    rejection_reasons = sorted(
        {
            candidate.first_failure_reason
            for candidate in rejected
            if candidate.first_failure_reason
        },
    )
    for reason in rejection_reasons:
        reason_candidates = [
            candidate
            for candidate in rejected
            if candidate.first_failure_reason == reason
        ]
        groups[reason] = _group_distribution(reason_candidates)

    if parse_errors:
        groups["parse_error"] = _group_distribution(parse_errors)

    samples: dict[str, list[dict[str, Any]]] = {}
    for reason in rejection_reasons:
        reason_candidates = [
            candidate
            for candidate in rejected
            if candidate.first_failure_reason == reason
        ]
        samples[reason] = [
            _candidate_sample(candidate)
            for candidate in reason_candidates[:sample_limit]
        ]

    distribution: dict[str, Any] = {
        "keyword": keyword,
        "total_candidates": len(candidates),
        "passed": len(passed),
        "rejected": len(rejected),
        "parse_errors": len(parse_errors),
        "filter_skip_reasons": dict(sorted(filter_skip_reasons.items())),
        "signal_availability": _build_signal_availability(candidates),
        "groups": groups,
    }
    if samples:
        distribution["samples"] = samples
    return distribution
