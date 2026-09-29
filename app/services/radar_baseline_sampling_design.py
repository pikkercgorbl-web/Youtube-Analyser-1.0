"""Offline baseline enrichment sampling design (Stage 1.10B)."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_candidate_analysis import _percentile
from app.services.radar_t0_data_quality import load_t0_jsonl

DESIGN_SCHEMA_VERSION = "1.10B"
SAMPLING_SEED = 42
SECONDS_PER_UNIQUE_CHANNEL_BASELINE = 3.0  # Stage 1.10A pilot effective pace
PILOT_UNIQUE_CHANNEL_RATIO = 170 / 189

T0_SAMPLER_FIELDS = frozenset(
    {
        "video_id",
        "channel_id",
        "keyword",
        "vph_at_t0",
        "discovery_views",
        "age_hours_at_t0",
        "final_subscribers",
        "discovery_subscribers",
        "discovered_at",
        "content_format",
    },
)


@dataclass(frozen=True, slots=True)
class SamplingRecord:
    video_id: str
    channel_id: str
    keyword: str
    vph_at_t0: float
    discovery_views: int
    age_hours_at_t0: float | None
    final_subscribers: int | None
    vph_stratum: str
    channel_size_stratum: str


@dataclass(frozen=True, slots=True)
class StratumBoundaries:
    vph: dict[str, Any]
    channel_subscribers: dict[str, Any]


@dataclass
class SampleResult:
    design_name: str
    target_size: int
    selected_video_ids: list[str]
    selected_count: int
    unique_channels: int
    keyword_counts: dict[str, int]
    vph_stratum_counts: dict[str, int]
    channel_size_counts: dict[str, int]
    expected_baseline_requests: int
    expected_runtime_seconds: float


def load_t0_cohort_from_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("per_keyword", []):
        path_str = entry.get("dataset_path")
        if not path_str:
            continue
        path = Path(path_str)
        if not path.is_file():
            continue
        for record in load_t0_jsonl(path):
            video_id = str(record.get("video_id") or "")
            if not video_id:
                continue
            if video_id not in rows:
                rows[video_id] = dict(record)
                rows[video_id]["t0_keywords"] = [record.get("keyword")]
            else:
                kw = record.get("keyword")
                if kw and kw not in rows[video_id]["t0_keywords"]:
                    rows[video_id]["t0_keywords"].append(kw)
    return list(rows.values())


def load_outcome_labels(joined_path: Path) -> dict[str, dict[str, Any]]:
    """Retrospective labels only — not used by frozen T0 sampler."""
    labels: dict[str, dict[str, Any]] = {}
    for record in load_t0_jsonl(joined_path):
        video_id = str(record.get("video_id") or "")
        if not video_id:
            continue
        labels[video_id] = {
            "absolute_view_growth": record.get("absolute_view_growth"),
            "t0_content_format": record.get("t0_content_format"),
        }
    return labels


def filter_regular_sampling_pool(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        if record.get("content_format") != "regular":
            continue
        if record.get("vph_at_t0") is None:
            continue
        channel_id = str(record.get("channel_id") or "").strip()
        if not channel_id:
            continue
        out.append(record)
    return out


def assign_vph_stratum(vph: float, boundaries: dict[str, float]) -> str:
    if vph >= boundaries["p90"]:
        return "very_high"
    if vph >= boundaries["p75"]:
        return "high"
    if vph >= boundaries["p25"]:
        return "medium"
    return "low"


def compute_vph_boundaries(records: list[dict[str, Any]]) -> dict[str, float]:
    values = sorted(float(record["vph_at_t0"]) for record in records)
    return {
        "p25": _percentile(values, 25),
        "p50": _percentile(values, 50),
        "p75": _percentile(values, 75),
        "p90": _percentile(values, 90),
        "min": values[0] if values else 0.0,
        "max": values[-1] if values else 0.0,
    }


def assign_channel_size_stratum(
    final_subscribers: int | None,
    discovery_subscribers: int | None,
    boundaries: dict[str, float | None],
) -> str:
    subs = final_subscribers if final_subscribers is not None else discovery_subscribers
    if subs is None or subs <= 0:
        return "unknown"
    if boundaries["p67"] is not None and subs >= boundaries["p67"]:
        return "large"
    if boundaries["p33"] is not None and subs >= boundaries["p33"]:
        return "medium"
    return "small"


def compute_subscriber_boundaries(records: list[dict[str, Any]]) -> dict[str, float | None]:
    values = sorted(
        float(record.get("final_subscribers") or record.get("discovery_subscribers") or 0)
        for record in records
        if (record.get("final_subscribers") or record.get("discovery_subscribers"))
    )
    values = [value for value in values if value > 0]
    if len(values) < 10:
        return {"p33": None, "p67": None, "note": "insufficient_subscriber_coverage"}
    return {
        "p33": _percentile(values, 33.33),
        "p67": _percentile(values, 66.67),
        "known_n": len(values),
    }


def to_sampling_records(
    pool: list[dict[str, Any]],
    *,
    vph_bounds: dict[str, float],
    sub_bounds: dict[str, float | None],
) -> list[SamplingRecord]:
    out: list[SamplingRecord] = []
    for record in pool:
        vph = float(record["vph_at_t0"])
        out.append(
            SamplingRecord(
                video_id=str(record["video_id"]),
                channel_id=str(record["channel_id"]),
                keyword=str(record.get("keyword") or (record.get("t0_keywords") or ["unknown"])[0]),
                vph_at_t0=vph,
                discovery_views=int(record.get("discovery_views") or 0),
                age_hours_at_t0=record.get("age_hours_at_t0"),
                final_subscribers=record.get("final_subscribers"),
                vph_stratum=assign_vph_stratum(vph, vph_bounds),
                channel_size_stratum=assign_channel_size_stratum(
                    record.get("final_subscribers"),
                    record.get("discovery_subscribers"),
                    sub_bounds,
                ),
            ),
        )
    return out


def summarize_distributions(records: list[SamplingRecord]) -> dict[str, Any]:
    vph_values = sorted(record.vph_at_t0 for record in records)
    views = sorted(float(record.discovery_views) for record in records)
    ages = sorted(
        float(record.age_hours_at_t0)
        for record in records
        if record.age_hours_at_t0 is not None
    )
    keywords: dict[str, int] = {}
    vph_strata: dict[str, int] = {}
    size_strata: dict[str, int] = {}
    channels: set[str] = set()
    for record in records:
        keywords[record.keyword] = keywords.get(record.keyword, 0) + 1
        vph_strata[record.vph_stratum] = vph_strata.get(record.vph_stratum, 0) + 1
        size_strata[record.channel_size_stratum] = size_strata.get(record.channel_size_stratum, 0) + 1
        channels.add(record.channel_id)

    return {
        "pool_size": len(records),
        "unique_channels": len(channels),
        "unique_channel_rate": round(len(channels) / len(records), 4) if records else None,
        "vph": {
            "p10": round(_percentile(vph_values, 10), 4),
            "p25": round(_percentile(vph_values, 25), 4),
            "p50": round(_percentile(vph_values, 50), 4),
            "p75": round(_percentile(vph_values, 75), 4),
            "p90": round(_percentile(vph_values, 90), 4),
        },
        "views": {
            "p50": round(_percentile(views, 50), 4),
            "p90": round(_percentile(views, 90), 4),
        },
        "age_hours": {
            "p50": round(_percentile(ages, 50), 4) if ages else None,
            "p90": round(_percentile(ages, 90), 4) if ages else None,
        },
        "keyword_counts": dict(sorted(keywords.items())),
        "vph_stratum_counts": dict(sorted(vph_strata.items())),
        "channel_size_stratum_counts": dict(sorted(size_strata.items())),
        "subscriber_known_rate": round(
            sum(1 for record in records if record.channel_size_stratum != "unknown") / len(records),
            4,
        )
        if records
        else None,
    }


def proportional_keyword_allocation(
    keyword_counts: dict[str, int],
    total_sample: int,
) -> dict[str, int]:
    total = sum(keyword_counts.values())
    if total == 0:
        return {}
    raw = {kw: total_sample * count / total for kw, count in keyword_counts.items()}
    floors = {kw: int(math.floor(value)) for kw, value in raw.items()}
    remainder = total_sample - sum(floors.values())
    fractional = sorted(
        ((kw, raw[kw] - floors[kw]) for kw in raw),
        key=lambda item: item[1],
        reverse=True,
    )
    for index in range(remainder):
        floors[fractional[index % len(fractional)][0]] += 1
    return floors


def capped_proportional_keyword_allocation(
    keyword_counts: dict[str, int],
    total_sample: int,
    *,
    cap_fraction: float = 0.18,
) -> dict[str, int]:
    cap = max(1, int(math.ceil(total_sample * cap_fraction)))
    total_sample = min(total_sample, sum(keyword_counts.values()))
    target = proportional_keyword_allocation(keyword_counts, total_sample)
    max_by_keyword = {kw: min(cap, count) for kw, count in keyword_counts.items()}
    for keyword in list(target.keys()):
        target[keyword] = min(target[keyword], max_by_keyword[keyword])
    shortfall = total_sample - sum(target.values())
    if shortfall <= 0:
        return target
    candidates = sorted(
        keyword_counts.keys(),
        key=lambda kw: keyword_counts[kw],
        reverse=True,
    )
    index = 0
    while shortfall > 0 and candidates:
        kw = candidates[index % len(candidates)]
        if target.get(kw, 0) < max_by_keyword[kw]:
            target[kw] = target.get(kw, 0) + 1
            shortfall -= 1
        index += 1
        if index > len(candidates) * (total_sample + 5):
            break
    return target


def apply_per_channel_cap(
    selected_ids: list[str],
    records_by_id: dict[str, SamplingRecord],
    *,
    max_per_channel: int | None,
) -> list[str]:
    if max_per_channel is None:
        return selected_ids
    channel_counts: dict[str, int] = {}
    out: list[str] = []
    for video_id in selected_ids:
        record = records_by_id[video_id]
        count = channel_counts.get(record.channel_id, 0)
        if count >= max_per_channel:
            continue
        channel_counts[record.channel_id] = count + 1
        out.append(video_id)
    return out


def _rank_by_vph(records: list[SamplingRecord]) -> list[SamplingRecord]:
    return sorted(records, key=lambda record: record.vph_at_t0, reverse=True)


def _sample_by_keyword_strata(
    records: list[SamplingRecord],
    *,
    target_size: int,
    keyword_allocation: dict[str, int],
    rng: random.Random,
    max_per_channel: int | None,
    strata_mix: dict[str, float],
) -> list[str]:
    by_keyword: dict[str, list[SamplingRecord]] = {}
    for record in records:
        by_keyword.setdefault(record.keyword, []).append(record)
    selected: list[str] = []
    records_by_id = {record.video_id: record for record in records}

    for keyword, quota in keyword_allocation.items():
        pool = _rank_by_vph(by_keyword.get(keyword, []))
        if not pool:
            continue
        picked: list[str] = []
        for stratum, fraction in strata_mix.items():
            need = max(0, int(round(quota * fraction)))
            stratum_pool = [record for record in pool if record.vph_stratum == stratum]
            rng.shuffle(stratum_pool)
            for record in stratum_pool:
                if sum(1 for video_id in picked if records_by_id[video_id].vph_stratum == stratum) >= need:
                    break
                if record.video_id in picked:
                    continue
                picked.append(record.video_id)
        for record in pool:
            if len(picked) >= quota:
                break
            if record.video_id not in picked:
                picked.append(record.video_id)
        selected.extend(picked[:quota])

    selected = list(dict.fromkeys(selected))[:target_size]
    return apply_per_channel_cap(selected, records_by_id, max_per_channel=max_per_channel)


def sample_design_a_vph_heavy(
    records: list[SamplingRecord],
    *,
    target_size: int,
    keyword_allocation: dict[str, int],
    rng: random.Random,
    max_per_channel: int | None,
) -> list[str]:
    return _sample_by_keyword_strata(
        records,
        target_size=target_size,
        keyword_allocation=keyword_allocation,
        rng=rng,
        max_per_channel=max_per_channel,
        strata_mix={"very_high": 0.35, "high": 0.25, "medium": 0.25, "low": 0.15},
    )


def sample_design_b_balanced(
    records: list[SamplingRecord],
    *,
    target_size: int,
    keyword_allocation: dict[str, int],
    rng: random.Random,
    max_per_channel: int | None,
) -> list[str]:
    return _sample_by_keyword_strata(
        records,
        target_size=target_size,
        keyword_allocation=keyword_allocation,
        rng=rng,
        max_per_channel=max_per_channel,
        strata_mix={"very_high": 0.25, "high": 0.25, "medium": 0.25, "low": 0.25},
    )


def sample_design_c_retrieval_first(
    records: list[SamplingRecord],
    *,
    target_size: int,
    keyword_allocation: dict[str, int],
    rng: random.Random,
    max_per_channel: int | None,
    top_vph_fraction: float = 0.10,
) -> list[str]:
    by_keyword: dict[str, list[SamplingRecord]] = {}
    for record in records:
        by_keyword.setdefault(record.keyword, []).append(record)
    selected: list[str] = []
    records_by_id = {record.video_id: record for record in records}
    for keyword, quota in keyword_allocation.items():
        pool = _rank_by_vph(by_keyword.get(keyword, []))
        if not pool:
            continue
        top_k = max(1, int(math.ceil(len(pool) * top_vph_fraction)))
        top_take = max(1, int(round(quota * 0.65)))
        control_take = quota - top_take
        top_ids = [record.video_id for record in pool[:top_k]]
        picked = top_ids[:top_take]
        remainder = [record for record in pool if record.video_id not in picked]
        rng.shuffle(remainder)
        for record in remainder:
            if len(picked) >= quota:
                break
            picked.append(record.video_id)
        selected.extend(picked[: top_take + control_take])
    selected = list(dict.fromkeys(selected))[:target_size]
    return apply_per_channel_cap(selected, records_by_id, max_per_channel=max_per_channel)


def build_sample_result(
    *,
    design_name: str,
    target_size: int,
    selected_ids: list[str],
    records_by_id: dict[str, SamplingRecord],
    unique_channel_ratio: float,
) -> SampleResult:
    selected_records = [records_by_id[video_id] for video_id in selected_ids if video_id in records_by_id]
    keyword_counts: dict[str, int] = {}
    vph_counts: dict[str, int] = {}
    size_counts: dict[str, int] = {}
    channels: set[str] = set()
    for record in selected_records:
        keyword_counts[record.keyword] = keyword_counts.get(record.keyword, 0) + 1
        vph_counts[record.vph_stratum] = vph_counts.get(record.vph_stratum, 0) + 1
        size_counts[record.channel_size_stratum] = size_counts.get(record.channel_size_stratum, 0) + 1
        channels.add(record.channel_id)
    unique_channels = len(channels)
    expected_requests = unique_channels
    return SampleResult(
        design_name=design_name,
        target_size=target_size,
        selected_video_ids=selected_ids,
        selected_count=len(selected_ids),
        unique_channels=unique_channels,
        keyword_counts=dict(sorted(keyword_counts.items())),
        vph_stratum_counts=dict(sorted(vph_counts.items())),
        channel_size_counts=dict(sorted(size_counts.items())),
        expected_baseline_requests=expected_requests,
        expected_runtime_seconds=round(expected_requests * SECONDS_PER_UNIQUE_CHANNEL_BASELINE, 1),
    )


def retrospective_winner_metrics(
    selected_ids: set[str],
    *,
    pool_ids: set[str],
    outcome_by_video: dict[str, float],
    winner_threshold: float,
) -> dict[str, Any]:
    winners_in_pool = {
        video_id
        for video_id in pool_ids
        if (outcome_by_video.get(video_id) is not None and outcome_by_video[video_id] >= winner_threshold)
    }
    winners_selected = winners_in_pool & selected_ids
    return {
        "winners_in_pool": len(winners_in_pool),
        "winners_selected": len(winners_selected),
        "winner_recall": round(len(winners_selected) / len(winners_in_pool), 4) if winners_in_pool else None,
        "selected_non_winner_share": round(
            (len(selected_ids) - len(winners_selected)) / len(selected_ids),
            4,
        )
        if selected_ids
        else None,
    }


def execute_frozen_t0_sampler(
    record: dict[str, Any],
    *,
    vph_bounds: dict[str, float],
    keyword_cap: int,
    keyword_selected: dict[str, int],
    channel_selected: dict[str, int],
    max_per_channel: int,
    rng: random.Random,
) -> bool:
    """Return True if record would be selected (T0 fields only)."""
    if record.get("content_format") != "regular" or record.get("vph_at_t0") is None:
        return False
    video_id = str(record.get("video_id") or "")
    channel_id = str(record.get("channel_id") or "")
    keyword = str(record.get("keyword") or "")
    if not video_id or not channel_id or not keyword:
        return False
    if channel_selected.get(channel_id, 0) >= max_per_channel:
        return False
    if keyword_selected.get(keyword, 0) >= keyword_cap:
        return False
    vph = float(record["vph_at_t0"])
    stratum = assign_vph_stratum(vph, vph_bounds)
    accept_prob = {
        "very_high": 1.0,
        "high": 0.85,
        "medium": 0.45,
        "low": 0.20,
    }[stratum]
    if rng.random() > accept_prob:
        return False
    keyword_selected[keyword] = keyword_selected.get(keyword, 0) + 1
    channel_selected[channel_id] = channel_selected.get(channel_id, 0) + 1
    return True


def run_sampling_design_analysis(
    *,
    manifest_path: Path,
    joined_path: Path | None = None,
    unique_channel_ratio: float = PILOT_UNIQUE_CHANNEL_RATIO,
) -> dict[str, Any]:
    raw = load_t0_cohort_from_manifest(manifest_path)
    pool_raw = filter_regular_sampling_pool(raw)
    vph_bounds = compute_vph_boundaries(pool_raw)
    sub_bounds = compute_subscriber_boundaries(pool_raw)
    records = to_sampling_records(pool_raw, vph_bounds=vph_bounds, sub_bounds=sub_bounds)
    distributions = summarize_distributions(records)
    records_by_id = {record.video_id: record for record in records}

    keyword_counts = distributions["keyword_counts"]
    target_sizes = (300, 500, 700)
    cap_alloc = capped_proportional_keyword_allocation(keyword_counts, 500)

    outcome_by_video: dict[str, float] = {}
    winner_threshold: float | None = None
    retrospective_pool: set[str] = set()
    if joined_path and joined_path.is_file():
        labels = load_outcome_labels(joined_path)
        growth_values = sorted(
            float(labels[video_id]["absolute_view_growth"])
            for video_id in labels
            if video_id in records_by_id
            and labels[video_id].get("absolute_view_growth") is not None
            and labels[video_id].get("t0_content_format") == "regular"
        )
        if growth_values:
            winner_threshold = _percentile(growth_values, 90)
            for video_id, payload in labels.items():
                if video_id in records_by_id and payload.get("absolute_view_growth") is not None:
                    outcome_by_video[video_id] = float(payload["absolute_view_growth"])
                    retrospective_pool.add(video_id)

    designs: dict[str, Any] = {}
    rng = random.Random(SAMPLING_SEED)
    for target in target_sizes:
        allocation = capped_proportional_keyword_allocation(keyword_counts, target)
        for design_name, sampler in (
            ("A_vph_heavy", sample_design_a_vph_heavy),
            ("B_balanced", sample_design_b_balanced),
            ("C_retrieval_first", sample_design_c_retrieval_first),
        ):
            design_rng = random.Random(SAMPLING_SEED + target)
            selected = sampler(
                records,
                target_size=target,
                keyword_allocation=allocation,
                rng=design_rng,
                max_per_channel=2,
            )
            result = build_sample_result(
                design_name=design_name,
                target_size=target,
                selected_ids=selected,
                records_by_id=records_by_id,
                unique_channel_ratio=unique_channel_ratio,
            )
            key = f"{design_name}_n{target}"
            entry: dict[str, Any] = {
                "target_size": target,
                "selected_count": result.selected_count,
                "unique_channels": result.unique_channels,
                "expected_baseline_requests": result.expected_baseline_requests,
                "expected_runtime_seconds": result.expected_runtime_seconds,
                "keyword_counts": result.keyword_counts,
                "vph_stratum_counts": result.vph_stratum_counts,
                "channel_size_counts": result.channel_size_counts,
            }
            if winner_threshold is not None:
                entry["retrospective"] = retrospective_winner_metrics(
                    set(selected),
                    pool_ids=retrospective_pool,
                    outcome_by_video=outcome_by_video,
                    winner_threshold=winner_threshold,
                )
            designs[key] = entry

    channel_cap_analysis: dict[str, Any] = {}
    allocation_500 = capped_proportional_keyword_allocation(keyword_counts, 500)
    for cap in (None, 2, 1):
        cap_label = "unlimited" if cap is None else f"max_{cap}_per_channel"
        selected = sample_design_a_vph_heavy(
            records,
            target_size=500,
            keyword_allocation=allocation_500,
            rng=random.Random(SAMPLING_SEED),
            max_per_channel=cap,
        )
        result = build_sample_result(
            design_name="A_vph_heavy",
            target_size=500,
            selected_ids=selected,
            records_by_id=records_by_id,
            unique_channel_ratio=unique_channel_ratio,
        )
        entry = {
            "selected_count": result.selected_count,
            "unique_channels": result.unique_channels,
            "expected_runtime_seconds": result.expected_runtime_seconds,
        }
        if winner_threshold is not None:
            entry["retrospective"] = retrospective_winner_metrics(
                set(selected),
                pool_ids=retrospective_pool,
                outcome_by_video=outcome_by_video,
                winner_threshold=winner_threshold,
            )
        channel_cap_analysis[cap_label] = entry

    proportional_500 = proportional_keyword_allocation(keyword_counts, 500)
    frozen_rule = {
        "version": DESIGN_SCHEMA_VERSION,
        "seed": SAMPLING_SEED,
        "eligible_pool": "content_format=regular AND vph_at_t0 IS NOT NULL AND channel_id present",
        "dedupe": "one row per video_id globally before sampling",
        "vph_strata_boundaries": vph_bounds,
        "vph_stratum_acceptance_probability": {
            "very_high": 1.0,
            "high": 0.85,
            "medium": 0.45,
            "low": 0.20,
        },
        "keyword_allocation": "capped_proportional",
        "keyword_cap_fraction": 0.18,
        "max_candidates_per_channel": 2,
        "target_baseline_sample_sizes": list(target_sizes),
        "recommended_target": 500,
        "recommended_design": "A_vph_heavy",
        "t0_only_fields": sorted(T0_SAMPLER_FIELDS),
        "notes": [
            "Acceptance uses vph_at_t0 strata only; no T67/outcome fields at execution time.",
            "Process pool in random shuffle order within keyword after optional top-VPH pass.",
            "Channel baseline fetched once per channel_id per run (cache).",
        ],
    }

    keyword_allocation_comparison = {
        "proportional_n500": proportional_500,
        "capped_proportional_n500": cap_alloc,
        "recommendation": "capped_proportional",
        "rationale": "Prevents gaming-sized keywords from dominating baseline budget while keeping representation.",
    }

    runtime_estimates = {}
    for target in target_sizes:
        est_channels = int(round(target * unique_channel_ratio))
        if target == 500:
            est_channels = designs.get("A_vph_heavy_n500", {}).get("unique_channels", est_channels)
        runtime_estimates[f"n{target}"] = {
            "assumed_unique_channels": est_channels,
            "baseline_seconds": round(est_channels * SECONDS_PER_UNIQUE_CHANNEL_BASELINE, 1),
            "baseline_minutes": round(est_channels * SECONDS_PER_UNIQUE_CHANNEL_BASELINE / 60, 1),
        }

    return {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "manifest_path": str(manifest_path.resolve()),
        "joined_path_used_for_retrospective_only": str(joined_path.resolve()) if joined_path else None,
        "source_distributions": distributions,
        "vph_strata": {
            "labels": ["low", "medium", "high", "very_high"],
            "boundaries": vph_bounds,
            "interpretation": {
                "low": f"vph < {vph_bounds['p25']}",
                "medium": f"{vph_bounds['p25']} <= vph < {vph_bounds['p75']}",
                "high": f"{vph_bounds['p75']} <= vph < {vph_bounds['p90']}",
                "very_high": f"vph >= {vph_bounds['p90']}",
            },
        },
        "channel_size_strata": {
            "labels": ["small", "medium", "large", "unknown"],
            "boundaries": sub_bounds,
        },
        "keyword_allocation": keyword_allocation_comparison,
        "designs": designs,
        "channel_cap_analysis": channel_cap_analysis,
        "runtime_estimates": runtime_estimates,
        "frozen_sampling_rule": frozen_rule,
        "limitations": [
            "Retrospective winner recall uses Stage 1.9 T67 outcomes — diagnostic only.",
            "Subscriber strata sparse (~12% known in T0 cohort); size balancing is approximate.",
            "Unique-channel ratio extrapolated from gaming pilot (1.10A).",
            "Next cohort discovery mix may differ from 1.9A keyword distributions.",
        ],
        "verification": {"NO_NETWORK": True, "NO_DB_WRITES": True},
    }


def render_sampling_design_markdown(report: dict[str, Any]) -> str:
    dist = report["source_distributions"]
    lines = [
        "# Baseline Sampling Design (Stage 1.10B)",
        "",
        "## 1. Source distributions (regular, VPH-eligible)",
        f"- Pool size: **{dist['pool_size']}**",
        f"- Unique channels: **{dist['unique_channels']}** (rate **{dist['unique_channel_rate']}**)",
        f"- VPH P50: **{dist['vph']['p50']}**",
        "",
        "## 2. VPH strata",
        f"`{report['vph_strata']}`",
        "",
        "## 3. Channel-size strata",
        f"`{report['channel_size_strata']}`",
        "",
        "## 4. Keyword allocation",
        f"**Recommendation:** {report['keyword_allocation']['recommendation']}",
        "",
        "## 5–6. Designs & retrospective coverage",
        "See JSON `designs` for A/B/C at n=300/500/700.",
        "",
        "## 7. Per-channel cap",
        f"`{report['channel_cap_analysis']}`",
        "",
        "## 8. Runtime estimates",
        f"`{report['runtime_estimates']}`",
        "",
        "## 9. Frozen sampling rule",
        "```json",
        json.dumps(report["frozen_sampling_rule"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 10. Limitations",
    ]
    for item in report.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_sampling_design_reports(
    report: dict[str, Any],
    *,
    output_dir: Path,
    review_id: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"radar_baseline_sampling_design_{review_id}.json"
    md_path = output_dir / f"radar_baseline_sampling_design_{review_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_sampling_design_markdown(report), encoding="utf-8")
    return json_path, md_path
