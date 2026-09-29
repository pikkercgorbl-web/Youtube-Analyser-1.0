"""Independent T0 cohort with channel baseline sample (Stage 1.10C)."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_baseline_sampling_design import (
    SAMPLING_SEED,
    SamplingRecord,
    apply_per_channel_cap,
    assign_vph_stratum,
    capped_proportional_keyword_allocation,
    compute_vph_boundaries,
    filter_regular_sampling_pool,
    sample_design_a_vph_heavy,
    to_sampling_records,
)
from app.services.radar_candidate import RadarCandidate
from app.services.radar_channel_baseline import (
    DEFAULT_VALIDATION_INNERTUBE_REQUEST_TIMEOUT,
    DEFAULT_VALIDATION_MAX_PAGES_PER_CHANNEL,
    DEFAULT_VALIDATION_MAX_SECONDS_PER_CHANNEL,
    ChannelBaselineConfig,
    ChannelBaselineRunStats,
    collect_channel_baselines_for_candidates,
)
from app.services.radar_validation_t0_dataset import (
    T0_SCHEMA_VERSION_WITH_BASELINE,
    serialize_t0_candidate,
    serialize_t0_candidate_with_baseline,
)

STAGE110_SCHEMA_VERSION = "1.10C"
STAGE110_TARGET_SAMPLE_SIZE = 500
STAGE110_KEYWORD_CAP_FRACTION = 0.18
STAGE110_MAX_PER_CHANNEL = 2
STAGE110_DESIGN_A_STRATA_MIX = {
    "very_high": 0.35,
    "high": 0.25,
    "medium": 0.25,
    "low": 0.15,
}

STAGE110_KEYWORDS: tuple[str, ...] = (
    "AI tools",
    "productivity",
    "fitness",
    "gaming",
    "history",
    "technology",
    "self improvement",
    "interesting facts",
    "home improvement",
    "travel",
)


@dataclass
class SamplingAudit:
    seed: int
    eligible_count: int
    target_size: int
    vph_boundaries: dict[str, float]
    keyword_quotas_requested: dict[str, int]
    keyword_quotas_filled: dict[str, int]
    vph_stratum_target: dict[str, int]
    vph_stratum_actual: dict[str, int]
    top_up_added: int
    per_channel_dropped: int
    keyword_shortfalls: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "eligible_count": self.eligible_count,
            "target_size": self.target_size,
            "vph_boundaries": self.vph_boundaries,
            "keyword_quotas_requested": self.keyword_quotas_requested,
            "keyword_quotas_filled": self.keyword_quotas_filled,
            "vph_stratum_target": self.vph_stratum_target,
            "vph_stratum_actual": self.vph_stratum_actual,
            "top_up_added": self.top_up_added,
            "per_channel_dropped": self.per_channel_dropped,
            "keyword_shortfalls": self.keyword_shortfalls,
            "design": "A_vph_heavy",
            "strata_mix": STAGE110_DESIGN_A_STRATA_MIX,
            "keyword_cap_fraction": STAGE110_KEYWORD_CAP_FRACTION,
            "max_per_channel": STAGE110_MAX_PER_CHANNEL,
        }


def merge_candidates_by_video_id(candidates: list[RadarCandidate]) -> list[RadarCandidate]:
    """Dedupe by video_id; keep first candidate row, track keywords on side dict."""
    by_id: dict[str, RadarCandidate] = {}
    keywords_by_id: dict[str, list[str]] = {}
    for candidate in candidates:
        vid = candidate.video_id
        if vid not in by_id:
            by_id[vid] = candidate
            keywords_by_id[vid] = [candidate.keyword]
        elif candidate.keyword not in keywords_by_id[vid]:
            keywords_by_id[vid].append(candidate.keyword)
    for vid, candidate in by_id.items():
        setattr(candidate, "t0_keywords", keywords_by_id[vid])
    return list(by_id.values())


def candidate_to_pool_record(candidate: RadarCandidate) -> dict[str, Any]:
    keywords = getattr(candidate, "t0_keywords", None) or [candidate.keyword]
    return {
        "video_id": candidate.video_id,
        "channel_id": candidate.channel_id,
        "keyword": candidate.keyword,
        "t0_keywords": keywords,
        "content_format": candidate.content_format,
        "vph_at_t0": candidate.vph_at_t0,
        "discovery_views": candidate.discovery_views,
        "age_hours_at_t0": candidate.age_hours_at_t0,
        "final_subscribers": candidate.final_subscribers,
        "discovery_subscribers": candidate.discovery_subscribers,
        "discovered_at": candidate.discovered_at.isoformat(),
    }


def build_eligible_pool(candidates: list[RadarCandidate]) -> tuple[list[RadarCandidate], list[dict[str, Any]]]:
    deduped = merge_candidates_by_video_id(candidates)
    records = [candidate_to_pool_record(candidate) for candidate in deduped]
    eligible_ids = {
        str(record["video_id"])
        for record in filter_regular_sampling_pool(records)
    }
    eligible_candidates = [candidate for candidate in deduped if candidate.video_id in eligible_ids]
    pool_records = [candidate_to_pool_record(candidate) for candidate in eligible_candidates]
    return eligible_candidates, pool_records


def _count_strata(selected_ids: list[str], records_by_id: dict[str, SamplingRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for video_id in selected_ids:
        record = records_by_id.get(video_id)
        if not record:
            continue
        counts[record.vph_stratum] = counts.get(record.vph_stratum, 0) + 1
    return counts


def _count_keywords(selected_ids: list[str], records_by_id: dict[str, SamplingRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for video_id in selected_ids:
        record = records_by_id.get(video_id)
        if not record:
            continue
        counts[record.keyword] = counts.get(record.keyword, 0) + 1
    return counts


def sample_stage110_design_a(
    pool_records: list[dict[str, Any]],
    *,
    target_size: int = STAGE110_TARGET_SAMPLE_SIZE,
    seed: int = SAMPLING_SEED,
) -> tuple[list[str], SamplingAudit, dict[str, SamplingRecord]]:
    vph_bounds = compute_vph_boundaries(pool_records)
    sub_bounds = {"p33": None, "p67": None}
    records = to_sampling_records(pool_records, vph_bounds=vph_bounds, sub_bounds=sub_bounds)
    records_by_id = {record.video_id: record for record in records}

    keyword_counts: dict[str, int] = {}
    for record in records:
        keyword_counts[record.keyword] = keyword_counts.get(record.keyword, 0) + 1

    keyword_quotas = capped_proportional_keyword_allocation(
        keyword_counts,
        target_size,
        cap_fraction=STAGE110_KEYWORD_CAP_FRACTION,
    )

    rng = random.Random(seed)
    pre_cap = sample_design_a_vph_heavy(
        records,
        target_size=target_size,
        keyword_allocation=keyword_quotas,
        rng=rng,
        max_per_channel=None,
    )
    capped = apply_per_channel_cap(pre_cap, records_by_id, max_per_channel=STAGE110_MAX_PER_CHANNEL)
    per_channel_dropped = len(pre_cap) - len(capped)
    selected = list(capped)
    selected_set = set(selected)

    stratum_target = {
        name: int(round(target_size * fraction))
        for name, fraction in STAGE110_DESIGN_A_STRATA_MIX.items()
    }

    keyword_filled = _count_keywords(selected, records_by_id)

    keyword_shortfalls = {
        keyword: max(0, keyword_quotas.get(keyword, 0) - keyword_filled.get(keyword, 0))
        for keyword in keyword_quotas
    }

    keyword_hard_cap = max(1, int(round(target_size * STAGE110_KEYWORD_CAP_FRACTION)))
    top_up_added = 0
    if len(selected) < target_size:
        remainder = [
            record
            for record in sorted(records, key=lambda item: item.vph_at_t0, reverse=True)
            if record.video_id not in selected_set
        ]
        channel_counts: dict[str, int] = {}
        for video_id in selected:
            channel_counts[records_by_id[video_id].channel_id] = (
                channel_counts.get(records_by_id[video_id].channel_id, 0) + 1
            )
        top_rng = random.Random(seed + 999)
        top_rng.shuffle(remainder)
        for record in remainder:
            if len(selected) >= target_size:
                break
            if channel_counts.get(record.channel_id, 0) >= STAGE110_MAX_PER_CHANNEL:
                continue
            if keyword_filled.get(record.keyword, 0) >= min(
                keyword_quotas.get(record.keyword, keyword_hard_cap),
                keyword_hard_cap,
            ):
                continue
            selected.append(record.video_id)
            selected_set.add(record.video_id)
            channel_counts[record.channel_id] = channel_counts.get(record.channel_id, 0) + 1
            keyword_filled[record.keyword] = keyword_filled.get(record.keyword, 0) + 1
            top_up_added += 1

    keyword_filled = _count_keywords(selected, records_by_id)
    audit = SamplingAudit(
        seed=seed,
        eligible_count=len(records),
        target_size=target_size,
        vph_boundaries=vph_bounds,
        keyword_quotas_requested=keyword_quotas,
        keyword_quotas_filled=keyword_filled,
        vph_stratum_target=stratum_target,
        vph_stratum_actual=_count_strata(selected, records_by_id),
        top_up_added=top_up_added,
        per_channel_dropped=per_channel_dropped,
        keyword_shortfalls=keyword_shortfalls,
    )
    return selected, audit, records_by_id


def load_old_cohort_video_and_channels(manifest_path: Path) -> tuple[set[str], set[str]]:
    from app.services.radar_baseline_sampling_design import load_t0_cohort_from_manifest

    rows = load_t0_cohort_from_manifest(manifest_path)
    video_ids = {str(row["video_id"]) for row in rows if row.get("video_id")}
    channel_ids = {str(row["channel_id"]) for row in rows if row.get("channel_id")}
    return video_ids, channel_ids


def compute_overlap(
    eligible: list[RadarCandidate],
    *,
    old_manifest_path: Path,
) -> dict[str, Any]:
    old_videos, old_channels = load_old_cohort_video_and_channels(old_manifest_path)
    new_videos = {candidate.video_id for candidate in eligible}
    new_channels = {candidate.channel_id for candidate in eligible if candidate.channel_id}
    overlap_videos = sorted(new_videos & old_videos)
    overlap_channels = sorted(new_channels & old_channels)
    return {
        "old_manifest": str(old_manifest_path),
        "new_unique_videos": len(new_videos),
        "new_unique_channels": len(new_channels),
        "overlap_video_count": len(overlap_videos),
        "overlap_channel_count": len(overlap_channels),
        "new_only_video_count": len(new_videos - old_videos),
        "overlap_video_ids_sample": overlap_videos[:20],
    }


def serialize_stage110_broad_row(candidate: RadarCandidate) -> dict[str, Any]:
    row = serialize_t0_candidate(candidate)
    keywords = getattr(candidate, "t0_keywords", None) or [candidate.keyword]
    row["t0_keywords"] = keywords
    return row


def serialize_stage110_sample_row(
    candidate: RadarCandidate,
    *,
    vph_stratum: str | None,
    sampling_audit: SamplingAudit,
) -> dict[str, Any]:
    row = serialize_t0_candidate_with_baseline(candidate)
    keywords = getattr(candidate, "t0_keywords", None) or [candidate.keyword]
    row.update(
        {
            "t0_keywords": keywords,
            "t0_views": candidate.discovery_views,
            "t0_vph": candidate.vph_at_t0,
            "age_hours_at_t0": candidate.age_hours_at_t0,
            "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
            "duration_seconds": candidate.duration_seconds,
            "t0_final_subscribers": candidate.final_subscribers,
            "t0_qualification_outcome": candidate.qualification_state,
            "t0_filter_reason": candidate.first_failure_reason,
            "vph_stratum": vph_stratum,
            "sampling_seed": sampling_audit.seed,
            "sampling_design": "A_vph_heavy",
            "sampling_target_n": sampling_audit.target_size,
        },
    )
    return row


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def build_stage110_manifest(
    *,
    cohort_timestamp: datetime,
    broad_path: Path,
    sample_path: Path,
    all_candidates: list[RadarCandidate],
    eligible: list[RadarCandidate],
    selected_ids: list[str],
    sampling_audit: SamplingAudit,
    baseline_stats: ChannelBaselineRunStats,
    overlap: dict[str, Any],
    discovery_duration_seconds: float,
    baseline_duration_seconds: float,
    quality: dict[str, Any],
) -> dict[str, Any]:
    stamp = cohort_timestamp.strftime("%Y%m%d_%H%M%S")
    return {
        "schema_version": STAGE110_SCHEMA_VERSION,
        "cohort_run_id": f"stage110_{stamp}",
        "discovery_timestamp": cohort_timestamp.isoformat(),
        "keywords": list(STAGE110_KEYWORDS),
        "datasets": {
            "broad_t0_jsonl": str(broad_path.resolve()),
            "experimental_sample_jsonl": str(sample_path.resolve()),
        },
        "sampling": sampling_audit.to_dict(),
        "overlap_with_stage19_t0": overlap,
        "discovery": {
            "duration_seconds": round(discovery_duration_seconds, 2),
            "raw_candidate_rows": len(all_candidates),
            "eligible_count": len(eligible),
            "selected_count": len(selected_ids),
        },
        "baseline": {
            "duration_seconds": round(baseline_duration_seconds, 2),
            "channel_baseline_requests": baseline_stats.channel_baseline_requests,
            "cache_hits": baseline_stats.cache_hits,
            "retained_history_leakage_violations": baseline_stats.retained_history_leakage_violations,
            "excluded_future_tab_videos": baseline_stats.excluded_future_tab_videos,
            "max_pages_per_channel": DEFAULT_VALIDATION_MAX_PAGES_PER_CHANNEL,
            "max_seconds_per_channel": DEFAULT_VALIDATION_MAX_SECONDS_PER_CHANNEL,
            "innertube_request_timeout": DEFAULT_VALIDATION_INNERTUBE_REQUEST_TIMEOUT,
        },
        "quality": quality,
        "verification": {
            "NO_OUTCOME_USAGE": True,
            "NO_DB_WRITES": True,
            "NO_T72_YET": True,
            "production_db_registration": False,
        },
    }


def build_quality_report(
    *,
    all_candidates: list[RadarCandidate],
    eligible: list[RadarCandidate],
    selected: list[RadarCandidate],
    sampling_audit: SamplingAudit,
    baseline_stats: ChannelBaselineRunStats,
) -> dict[str, Any]:
    broad_deduped = merge_candidates_by_video_id(all_candidates)
    vph_available = sum(1 for candidate in broad_deduped if candidate.vph_at_t0 is not None)
    regular = sum(1 for candidate in broad_deduped if candidate.content_format == "regular")

    baseline_ok = sum(
        1 for candidate in selected if getattr(candidate, "channel_baseline_status", None) == "ok"
    )
    partial = sum(
        1 for candidate in selected if getattr(candidate, "channel_baseline_status", None) == "partial"
    )
    views_median_cov = sum(
        1 for candidate in selected if getattr(candidate, "views_vs_channel_median", None) is not None
    )
    views_p75_cov = sum(
        1 for candidate in selected if getattr(candidate, "views_vs_channel_p75", None) is not None
    )
    subs_cov = sum(
        1
        for candidate in selected
        if (candidate.final_subscribers or candidate.discovery_subscribers)
    )

    channels = {candidate.channel_id for candidate in selected if candidate.channel_id}

    status_counts: dict[str, int] = {}
    for candidate in selected:
        status = getattr(candidate, "channel_baseline_status", None) or "missing"
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "broad_pool": {
            "raw_scan_rows": len(all_candidates),
            "unique_videos_deduped": len(broad_deduped),
            "regular_count": regular,
            "vph_available": vph_available,
            "eligible_for_sampling": len(eligible),
            "unique_channels_eligible": len({candidate.channel_id for candidate in eligible}),
        },
        "sample": {
            "target_n": sampling_audit.target_size,
            "actual_n": len(selected),
            "vph_stratum_counts": sampling_audit.vph_stratum_actual,
            "keyword_counts": sampling_audit.keyword_quotas_filled,
            "unique_channels": len(channels),
            "subscriber_coverage": subs_cov,
            "baseline_status_counts": status_counts,
            "baseline_ok_or_partial": baseline_ok + partial,
            "views_vs_channel_median_coverage": views_median_cov,
            "views_vs_channel_p75_coverage": views_p75_cov,
        },
        "baseline_stats_summary": {
            "channel_baseline_requests": baseline_stats.channel_baseline_requests,
            "cache_hits": baseline_stats.cache_hits,
            "retained_history_leakage_violations": baseline_stats.retained_history_leakage_violations,
            "channels_target_reached": baseline_stats.channels_target_reached,
            "channels_page_cap_reached": baseline_stats.channels_page_cap_reached,
            "channels_timeout": baseline_stats.channels_timeout,
            "channels_no_continuation": baseline_stats.channels_no_continuation,
            "max_pages_observed": baseline_stats.max_pages_observed,
            "max_channel_elapsed_seconds": baseline_stats.max_channel_elapsed_seconds,
            "average_channel_elapsed_seconds": baseline_stats.average_channel_elapsed_seconds,
        },
    }


async def apply_baseline_to_selected(
    selected: list[RadarCandidate],
    client: Any,
) -> ChannelBaselineRunStats:
    return await collect_channel_baselines_for_candidates(
        selected,
        client,
        config=ChannelBaselineConfig(
            max_pages_per_channel=DEFAULT_VALIDATION_MAX_PAGES_PER_CHANNEL,
            max_seconds_per_channel=DEFAULT_VALIDATION_MAX_SECONDS_PER_CHANNEL,
            innertube_request_timeout=DEFAULT_VALIDATION_INNERTUBE_REQUEST_TIMEOUT,
        ),
    )
