"""Leakage-safe historical validation for keyword performance (Stage 1.18C)."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    AttributionMode,
    KeywordVideoBaseline,
    _first_discovery_owner,
    _first_hit_per_keyword_video,
    _time_clauses,
    attributed_videos_for_keyword,
    load_snapshots_for_horizon,
    match_horizon_outcome,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.radar_candidate_analysis import _percentile
from app.services.radar_outcome_analysis import spearman_correlation
from app.services.radar_t0_data_quality import load_t0_jsonl

VALIDATION_SCHEMA_VERSION = "1.18C"
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 500

COHORT_1_JOINED = "radar_outcome_joined_T0_T67_20260914_124311.jsonl"
COHORT_2_JOINED = "radar_outcome_joined_stage110_T0_to_T72_stage110_20260914_141029.jsonl"

FROZEN_JOINED_SHA256 = {
    COHORT_1_JOINED: "4ad54a3725a8a777e63436bba26308fbcccb8e17227355f9c8d3380c8412dc11",
    COHORT_2_JOINED: "69613d88581a8f2c45bee441ddd5e40cec64c1ca06a79022d9412dc30e26e504",
}

DataSourceKind = Literal["frozen_pseudo_keyword", "production_target_keyword"]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 4)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def bootstrap_spearman_ci(
    xs: list[float],
    ys: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    if len(xs) != len(ys) or len(xs) < 3:
        return {"n": len(xs), "note": "insufficient pairs for bootstrap"}
    rng = random.Random(seed)
    pairs = list(zip(xs, ys))
    samples: list[float] = []
    for _ in range(resamples):
        draw = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        rho = spearman_correlation([p[0] for p in draw], [p[1] for p in draw]).get("rho")
        if rho is not None:
            samples.append(float(rho))
    if len(samples) < 10:
        return {"n": len(xs), "note": "too few successful resamples"}
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[int(0.975 * len(samples))]
    return {
        "n": len(xs),
        "point_rho": spearman_correlation(xs, ys).get("rho"),
        "ci95_low": round(lo, 4),
        "ci95_high": round(hi, 4),
        "resamples": len(samples),
    }


@dataclass
class LeakageSafeFeatureContract:
    """Early (allowed) vs forbidden predictors for historical validation."""

    allowed_early: tuple[str, ...] = (
        "vph_at_discovery",
        "views_at_discovery",
        "early_global_vph_rank",
        "early_top_decile_by_discovery_vph",
        "discovery_yield_counts",
        "new_to_corpus",
        "duplicate_flags",
        "scan_run_metadata",
    )
    forbidden_leaky: tuple[str, ...] = (
        "current_vph_after_horizon",
        "current_breakout_rank_after_outcome",
        "future_snapshots",
        "future_lifecycle_state",
        "outcome_derived_features",
        "production_breakout_leaderboard_at_evaluated_at",
    )
    delayed_target: str = "absolute_view_growth_72h"
    horizon_hours: int = HORIZON_HOURS
    horizon_tolerance_hours: int = HORIZON_SNAPSHOT_TOLERANCE_HOURS


@dataclass
class VideoObservation:
    keyword_key: str
    video_id: str
    source: DataSourceKind
    vph_at_discovery: float | None
    views_at_discovery: int | None
    early_top_decile: bool
    absolute_view_growth_72h: float | None
    new_to_corpus: bool | None = None
    cross_keyword_duplicate: bool | None = None
    within_keyword_duplicate: bool | None = None
    discovery_run_id: str | None = None
    discovery_at: datetime | None = None


@dataclass
class KeywordValidationAgg:
    keyword_key: str
    source: DataSourceKind
    attributed_video_count: int = 0
    median_vph_at_discovery: float | None = None
    p90_vph_at_discovery: float | None = None
    early_top_decile_count: int = 0
    early_top_decile_rate: float | None = None
    new_to_corpus_rate: float | None = None
    cross_keyword_duplicate_rate: float | None = None
    scan_count: int = 0
    unique_videos_per_scan_median: float | None = None
    observed_72h_video_count: int = 0
    median_absolute_view_growth_72h: float | None = None
    p90_absolute_view_growth_72h: float | None = None
    delayed_top_decile_growth_rate: float | None = None
    top_video_share_of_total_growth: float | None = None
    top_video_share_of_top_decile_breakouts: float | None = None
    median_vs_mean_growth_gap: float | None = None
    outlier_dominated: bool = False


def filter_frozen_signal_row(row: dict[str, Any]) -> bool:
    if row.get("fetch_status") is not None and row.get("fetch_status") != "refreshed":
        return False
    if row.get("t0_content_format") != "regular":
        return False
    if row.get("t0_views") is None:
        return False
    if row.get("absolute_view_growth") is None:
        return False
    return True


def build_early_top_decile_video_set(
    rows: list[dict[str, Any]],
    *,
    vph_field: str = "t0_vph",
) -> set[str]:
    """Global top decile by discovery-time VPH within evaluation population (unique videos)."""
    vph_by_video: dict[str, float] = {}
    for row in rows:
        vph = row.get(vph_field)
        if vph is None:
            continue
        vid = str(row["video_id"])
        vph_by_video[vid] = float(vph)
    if not vph_by_video:
        return set()
    ordered = sorted(vph_by_video.items(), key=lambda item: (-item[1], item[0]))
    cutoff = max(1, int(math.ceil(len(ordered) * 0.10)))
    return {vid for vid, _ in ordered[:cutoff]}


def global_delayed_top_decile_threshold(growth_values: list[float]) -> float | None:
    if len(growth_values) < 2:
        return None
    return float(_percentile(sorted(growth_values), 90))


def expand_frozen_observations(
    rows: list[dict[str, Any]],
    *,
    mode: AttributionMode,
    early_top_decile_videos: set[str],
) -> list[VideoObservation]:
    observations: list[VideoObservation] = []
    for row in rows:
        if not filter_frozen_signal_row(row):
            continue
        keywords = row.get("t0_keywords") or []
        if not keywords:
            continue
        labels = [str(k).strip() for k in keywords if str(k).strip()]
        if not labels:
            continue
        vid = str(row["video_id"])
        growth = float(row["absolute_view_growth"])
        vph = float(row["t0_vph"]) if row.get("t0_vph") is not None else None
        views = int(row["t0_views"])
        in_early = vid in early_top_decile_videos

        if mode == "first_discovery":
            credited = [labels[0]]
        else:
            credited = labels

        for label in credited:
            observations.append(
                VideoObservation(
                    keyword_key=label,
                    video_id=vid,
                    source="frozen_pseudo_keyword",
                    vph_at_discovery=vph,
                    views_at_discovery=views,
                    early_top_decile=in_early,
                    absolute_view_growth_72h=growth,
                    new_to_corpus=None,
                    cross_keyword_duplicate=len(labels) > 1,
                    within_keyword_duplicate=False,
                    discovery_run_id=None,
                    discovery_at=None,
                ),
            )
    return observations


def aggregate_keywords(observations: list[VideoObservation]) -> dict[str, KeywordValidationAgg]:
    by_kw: dict[str, list[VideoObservation]] = defaultdict(list)
    for obs in observations:
        by_kw[obs.keyword_key].append(obs)

    all_growths = [
        float(o.absolute_view_growth_72h)
        for o in observations
        if o.absolute_view_growth_72h is not None
    ]
    growth_p90 = global_delayed_top_decile_threshold(all_growths)

    aggs: dict[str, KeywordValidationAgg] = {}
    for key, rows in by_kw.items():
        source = rows[0].source
        agg = KeywordValidationAgg(keyword_key=key, source=source)
        agg.attributed_video_count = len(rows)
        vphs = [float(o.vph_at_discovery) for o in rows if o.vph_at_discovery is not None]
        if vphs:
            ordered = sorted(vphs)
            agg.median_vph_at_discovery = _median(vphs)
            agg.p90_vph_at_discovery = round(_percentile(ordered, 90), 4)
        agg.early_top_decile_count = sum(1 for o in rows if o.early_top_decile)
        agg.early_top_decile_rate = (
            round(agg.early_top_decile_count / agg.attributed_video_count, 4)
            if agg.attributed_video_count
            else None
        )
        new_flags = [o.new_to_corpus for o in rows if o.new_to_corpus is not None]
        if new_flags:
            agg.new_to_corpus_rate = round(sum(1 for f in new_flags if f) / len(new_flags), 4)
        cross_flags = [o.cross_keyword_duplicate for o in rows if o.cross_keyword_duplicate is not None]
        if cross_flags:
            agg.cross_keyword_duplicate_rate = round(
                sum(1 for f in cross_flags if f) / len(cross_flags),
                4,
            )
        run_ids = {o.discovery_run_id for o in rows if o.discovery_run_id}
        agg.scan_count = len(run_ids) if run_ids else 1
        if run_ids:
            per_scan: dict[str, set[str]] = defaultdict(set)
            for o in rows:
                if o.discovery_run_id:
                    per_scan[o.discovery_run_id].add(o.video_id)
            counts = [len(vids) for vids in per_scan.values()]
            agg.unique_videos_per_scan_median = _median([float(c) for c in counts])

        growths: list[float] = []
        for o in rows:
            if o.absolute_view_growth_72h is not None:
                growths.append(float(o.absolute_view_growth_72h))
        agg.observed_72h_video_count = len(growths)
        if growths:
            ordered_g = sorted(growths)
            agg.median_absolute_view_growth_72h = _median(growths)
            agg.p90_absolute_view_growth_72h = round(_percentile(ordered_g, 90), 4)
            if growth_p90 is not None:
                top = sum(1 for g in growths if g >= growth_p90)
                agg.delayed_top_decile_growth_rate = round(top / len(growths), 4)
            mean_g = _mean(growths)
            if mean_g is not None and agg.median_absolute_view_growth_72h is not None:
                agg.median_vs_mean_growth_gap = round(
                    mean_g - agg.median_absolute_view_growth_72h,
                    4,
                )
            total = sum(growths)
            if total > 0:
                top_vid_growth = max(growths)
                agg.top_video_share_of_total_growth = round(top_vid_growth / total, 4)
                if agg.early_top_decile_count:
                    early_growths = [
                        float(o.absolute_view_growth_72h)
                        for o in rows
                        if o.early_top_decile and o.absolute_view_growth_72h is not None
                    ]
                    if early_growths:
                        top_early = max(early_growths)
                        agg.top_video_share_of_top_decile_breakouts = round(
                            top_early / sum(early_growths),
                            4,
                        )
                agg.outlier_dominated = bool(
                    agg.top_video_share_of_total_growth is not None
                    and agg.top_video_share_of_total_growth >= 0.5
                    and agg.median_vs_mean_growth_gap is not None
                    and agg.median_vs_mean_growth_gap > 0
                )
        aggs[key] = agg
    return aggs


def keyword_level_q1_analysis(aggs: dict[str, KeywordValidationAgg]) -> dict[str, Any]:
    """Spearman at keyword grain: early metrics vs delayed aggregates."""
    usable = [
        a
        for a in aggs.values()
        if a.observed_72h_video_count >= 1
        and a.median_absolute_view_growth_72h is not None
    ]
    pairs_early_rate_vs_median_growth: list[tuple[float, float]] = []
    pairs_median_vph_vs_median_growth: list[tuple[float, float]] = []
    pairs_p90_vph_vs_p90_growth: list[tuple[float, float]] = []
    pairs_early_rate_vs_delayed_top_rate: list[tuple[float, float]] = []

    for a in usable:
        if a.early_top_decile_rate is not None:
            pairs_early_rate_vs_median_growth.append(
                (a.early_top_decile_rate, float(a.median_absolute_view_growth_72h)),
            )
            if a.delayed_top_decile_growth_rate is not None:
                pairs_early_rate_vs_delayed_top_rate.append(
                    (a.early_top_decile_rate, float(a.delayed_top_decile_growth_rate)),
                )
        if a.median_vph_at_discovery is not None:
            pairs_median_vph_vs_median_growth.append(
                (a.median_vph_at_discovery, float(a.median_absolute_view_growth_72h)),
            )
        if a.p90_vph_at_discovery is not None and a.p90_absolute_view_growth_72h is not None:
            pairs_p90_vph_vs_p90_growth.append(
                (a.p90_vph_at_discovery, float(a.p90_absolute_view_growth_72h)),
            )

    def _pack(pairs: list[tuple[float, float]]) -> dict[str, Any]:
        if len(pairs) < 2:
            return {"usable_keyword_n": len(pairs), "spearman": {"n": len(pairs), "rho": None}}
        xs, ys = zip(*pairs)
        return {
            "usable_keyword_n": len(pairs),
            "spearman": spearman_correlation(list(xs), list(ys)),
            "bootstrap_ci": bootstrap_spearman_ci(list(xs), list(ys)),
        }

    return {
        "early_top_decile_rate_vs_median_absolute_view_growth_72h": _pack(
            pairs_early_rate_vs_median_growth,
        ),
        "median_vph_at_discovery_vs_median_absolute_view_growth_72h": _pack(
            pairs_median_vph_vs_median_growth,
        ),
        "p90_vph_at_discovery_vs_p90_absolute_view_growth_72h": _pack(
            pairs_p90_vph_vs_p90_growth,
        ),
        "early_top_decile_rate_vs_delayed_top_decile_growth_rate": _pack(
            pairs_early_rate_vs_delayed_top_rate,
        ),
        "keywords_with_any_72h_outcome": len(usable),
        "keywords_total": len(aggs),
    }


def stratify_evidence(aggs: dict[str, KeywordValidationAgg]) -> dict[str, Any]:
    def bucket_scan(n: int) -> str:
        if n <= 1:
            return "scan_1"
        if n <= 5:
            return "scan_2_5"
        return "scan_6_plus"

    def bucket_videos(n: int) -> str:
        if n < 10:
            return "attr_lt_10"
        if n < 50:
            return "attr_10_49"
        return "attr_50_plus"

    def bucket_observed(n: int) -> str:
        if n == 0:
            return "obs_0"
        if n < 10:
            return "obs_1_9"
        return "obs_10_plus"

    strata: dict[str, list[KeywordValidationAgg]] = defaultdict(list)
    for a in aggs.values():
        key = f"{bucket_scan(a.scan_count)}|{bucket_videos(a.attributed_video_count)}|{bucket_observed(a.observed_72h_video_count)}"
        strata[key].append(a)

    summary: dict[str, Any] = {}
    for key, items in sorted(strata.items()):
        rates = [a.early_top_decile_rate for a in items if a.early_top_decile_rate is not None]
        med_growth = [
            a.median_absolute_view_growth_72h
            for a in items
            if a.median_absolute_view_growth_72h is not None
        ]
        summary[key] = {
            "keyword_count": len(items),
            "early_top_decile_rate_mean": _mean([float(r) for r in rates]) if rates else None,
            "early_top_decile_rate_std": (
                round(
                    math.sqrt(
                        sum((float(r) - sum(rates) / len(rates)) ** 2 for r in rates)
                        / len(rates),
                    ),
                    4,
                )
                if len(rates) > 1
                else None
            ),
            "median_growth_mean": _mean([float(g) for g in med_growth]) if med_growth else None,
        }
    return summary


def outlier_summary(aggs: dict[str, KeywordValidationAgg]) -> dict[str, Any]:
    dominated = [a.keyword_key for a in aggs.values() if a.outlier_dominated]
    shares = [
        a.top_video_share_of_total_growth
        for a in aggs.values()
        if a.top_video_share_of_total_growth is not None
    ]
    return {
        "outlier_dominated_keyword_count": len(dominated),
        "outlier_dominated_keywords_sample": dominated[:20],
        "top_video_share_of_total_growth_median": _median([float(s) for s in shares]) if shares else None,
        "top_video_share_of_total_growth_p90": (
            round(_percentile(sorted(shares), 90), 4) if shares else None
        ),
    }


def redundancy_analysis(observations: list[VideoObservation]) -> dict[str, Any]:
    by_video: dict[str, set[str]] = defaultdict(set)
    for o in observations:
        by_video[o.video_id].add(o.keyword_key)
    multi = {vid: kids for vid, kids in by_video.items() if len(kids) > 1}
    cross_rate = (
        round(sum(1 for o in observations if o.cross_keyword_duplicate) / len(observations), 4)
        if observations
        else None
    )
    return {
        "observation_count": len(observations),
        "unique_videos": len(by_video),
        "videos_with_multiple_keywords": len(multi),
        "mean_keywords_per_multi_video": (
            round(sum(len(kids) for kids in multi.values()) / len(multi), 4) if multi else None
        ),
        "cross_keyword_duplicate_observation_rate": cross_rate,
    }


def compare_attribution_modes(
    rows: list[dict[str, Any]],
    *,
    early_top_decile_videos: set[str],
) -> dict[str, Any]:
    all_obs = expand_frozen_observations(
        rows,
        mode="all_hits",
        early_top_decile_videos=early_top_decile_videos,
    )
    first_obs = expand_frozen_observations(
        rows,
        mode="first_discovery",
        early_top_decile_videos=early_top_decile_videos,
    )
    all_aggs = aggregate_keywords(all_obs)
    first_aggs = aggregate_keywords(first_obs)
    all_q1 = keyword_level_q1_analysis(all_aggs)
    first_q1 = keyword_level_q1_analysis(first_aggs)

    shared_keys = set(all_aggs.keys()) & set(first_aggs.keys())
    rank_deltas: list[float] = []
    for key in shared_keys:
        a = all_aggs[key]
        f = first_aggs[key]
        if a.median_vph_at_discovery is None or f.median_vph_at_discovery is None:
            continue
        rank_deltas.append(abs(a.median_vph_at_discovery - f.median_vph_at_discovery))

    return {
        "all_hits": {
            "keyword_count": len(all_aggs),
            "observation_count": len(all_obs),
            "q1": all_q1,
            "redundancy": redundancy_analysis(all_obs),
        },
        "first_discovery": {
            "keyword_count": len(first_aggs),
            "observation_count": len(first_obs),
            "q1": first_q1,
            "redundancy": redundancy_analysis(first_obs),
            "scan_order_bias_note": (
                "Frozen cohort credits first label in t0_keywords[] only; "
                "order is export metadata, not production scan order."
            ),
        },
        "shared_keyword_labels": len(shared_keys),
        "median_vph_abs_delta_on_shared": _median(rank_deltas),
    }


def per_scan_stability_production(
    observations: list[VideoObservation],
) -> dict[str, Any]:
    """Per keyword×scan early rate vs scan-level median growth (production only)."""
    by_kw_scan: dict[tuple[str, str], list[VideoObservation]] = defaultdict(list)
    for o in observations:
        if o.discovery_run_id is None:
            continue
        by_kw_scan[(o.keyword_key, o.discovery_run_id)].append(o)

    multi_scan_keywords: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (kw, run_id), rows in by_kw_scan.items():
        vphs = [float(r.vph_at_discovery) for r in rows if r.vph_at_discovery is not None]
        growths = [
            float(r.absolute_view_growth_72h)
            for r in rows
            if r.absolute_view_growth_72h is not None
        ]
        multi_scan_keywords[kw].append(
            {
                "discovery_run_id": run_id,
                "video_count": len(rows),
                "early_top_decile_rate": (
                    round(sum(1 for r in rows if r.early_top_decile) / len(rows), 4) if rows else None
                ),
                "median_growth_72h": _median(growths),
            },
        )

    stability_rows: list[dict[str, Any]] = []
    for kw, scans in multi_scan_keywords.items():
        if len(scans) < 2:
            continue
        rates = [s["early_top_decile_rate"] for s in scans if s["early_top_decile_rate"] is not None]
        growths = [s["median_growth_72h"] for s in scans if s["median_growth_72h"] is not None]
        stability_rows.append(
            {
                "keyword_key": kw,
                "scan_count": len(scans),
                "early_top_decile_rate_range": (
                    round(max(rates) - min(rates), 4) if len(rates) > 1 else None
                ),
                "median_growth_range": (
                    round(max(growths) - min(growths), 4) if len(growths) > 1 else None
                ),
            },
        )

    return {
        "keywords_with_multiple_scans": len(stability_rows),
        "sample": stability_rows[:25],
        "note": "Frozen pseudo-keywords lack KeywordScanRun granularity; use production block.",
    }


def build_production_observations(
    session: Session,
    *,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    mode: AttributionMode,
) -> tuple[list[VideoObservation], dict[str, Any]]:
    t0 = time.perf_counter()
    hit_filters = list(_time_clauses(KeywordDiscoveryHit.discovered_at, window_from, window_to))
    all_hits = list(session.scalars(select(KeywordDiscoveryHit).where(*hit_filters)).all())
    if not all_hits:
        return [], {"hit_count": 0, "elapsed_seconds": round(time.perf_counter() - t0, 3)}

    baselines_map = _first_hit_per_keyword_video(all_hits)
    first_owner = _first_discovery_owner(all_hits)

    vph_by_video: dict[str, tuple[datetime, float]] = {}
    for (_kid, vid), hit in baselines_map.items():
        if hit.vph_at_discovery is None:
            continue
        at = ensure_utc(hit.discovered_at)
        vph = float(hit.vph_at_discovery)
        prev = vph_by_video.get(vid)
        if prev is None or at < prev[0]:
            vph_by_video[vid] = (at, vph)

    ordered_videos = sorted(
        ((vid, vph) for vid, (_at, vph) in vph_by_video.items()),
        key=lambda item: (-item[1], item[0]),
    )
    cutoff = max(1, int(math.ceil(len(ordered_videos) * 0.10))) if ordered_videos else 0
    early_top_videos = {vid for vid, _ in ordered_videos[:cutoff]}

    keyword_ids = sorted({h.keyword_id for h in all_hits})
    id_to_label = {
        int(k.id): k.keyword
        for k in session.scalars(select(TargetKeyword).where(TargetKeyword.id.in_(keyword_ids))).all()
    }

    hits_by_keyword: dict[int, list[KeywordDiscoveryHit]] = defaultdict(list)
    for hit in all_hits:
        hits_by_keyword[hit.keyword_id].append(hit)

    attr_videos: set[str] = set()
    per_kw_vids: dict[int, set[str]] = {}
    for kid in keyword_ids:
        vids = attributed_videos_for_keyword(
            kid,
            mode=mode,
            hits_for_keyword=hits_by_keyword.get(kid, []),
            first_owner=first_owner,
        )
        per_kw_vids[kid] = vids
        attr_videos |= vids

    snapshots = load_snapshots_for_horizon(session, attr_videos)

    by_vid_kws: dict[str, set[int]] = defaultdict(set)
    for hit in all_hits:
        by_vid_kws[hit.video_id].add(hit.keyword_id)
    shared_videos = {vid for vid, kids in by_vid_kws.items() if len(kids) > 1}

    observations: list[VideoObservation] = []
    for kid, vids in per_kw_vids.items():
        label = id_to_label.get(kid, str(kid))
        for vid in vids:
            base_hit = baselines_map.get((kid, vid))
            if base_hit is None:
                continue
            baseline = KeywordVideoBaseline(
                keyword_id=kid,
                video_id=vid,
                discovery_at=base_hit.discovered_at,
                views_at_discovery=base_hit.views_at_discovery,
                vph_at_discovery=base_hit.vph_at_discovery,
            )
            outcome = match_horizon_outcome(baseline, snapshots)
            growth = float(outcome.absolute_view_growth) if outcome else None
            observations.append(
                VideoObservation(
                    keyword_key=label,
                    video_id=vid,
                    source="production_target_keyword",
                    vph_at_discovery=(
                        float(base_hit.vph_at_discovery)
                        if base_hit.vph_at_discovery is not None
                        else None
                    ),
                    views_at_discovery=base_hit.views_at_discovery,
                    early_top_decile=vid in early_top_videos,
                    absolute_view_growth_72h=growth,
                    new_to_corpus=(
                        not bool(base_hit.video_existed_before_discovery)
                        if base_hit.video_existed_before_discovery is not None
                        else None
                    ),
                    cross_keyword_duplicate=vid in shared_videos,
                    within_keyword_duplicate=bool(base_hit.was_within_keyword_duplicate),
                    discovery_run_id=base_hit.discovery_run_id,
                    discovery_at=ensure_utc(base_hit.discovered_at),
                ),
            )

    scan_filters = [
        KeywordScanRun.keyword_id.in_(keyword_ids),
        *_time_clauses(KeywordScanRun.started_at, window_from, window_to),
    ]
    scan_rows = session.execute(
        select(KeywordScanRun.keyword_id, func.count()).where(*scan_filters).group_by(
            KeywordScanRun.keyword_id,
        ),
    ).all()
    meta = {
        "hit_count": len(all_hits),
        "keyword_count": len(keyword_ids),
        "attributed_observation_count": len(observations),
        "unique_videos_early_pool": len(ordered_videos),
        "scan_count_by_keyword": {int(k): int(c) for k, c in scan_rows},
        "elapsed_seconds": round(time.perf_counter() - t0, 3),
    }
    return observations, meta


def analyze_frozen_cohort(
    joined_path: Path,
    *,
    cohort_id: str,
    elapsed_hours_label: float | None = None,
) -> dict[str, Any]:
    rows = load_t0_jsonl(joined_path)
    signal_rows = [r for r in rows if filter_frozen_signal_row(r)]
    early_top = build_early_top_decile_video_set(signal_rows)
    attribution = compare_attribution_modes(signal_rows, early_top_decile_videos=early_top)
    all_aggs = aggregate_keywords(
        expand_frozen_observations(
            signal_rows,
            mode="all_hits",
            early_top_decile_videos=early_top,
        ),
    )
    return {
        "cohort_id": cohort_id,
        "joined_path": joined_path.name,
        "joined_sha256": sha256_file(joined_path),
        "elapsed_hours_from_t0": elapsed_hours_label,
        "limitations": [
            "Pseudo-keywords from t0_keywords[] are not TargetKeyword.id.",
            "No KeywordScanRun / rescan timeline in join file.",
            "Outcome is pre-joined ~72h growth, not recomputed from VideoSnapshot.",
            "first_discovery uses first array element only (export order).",
        ],
        "row_counts": {
            "joined_total": len(rows),
            "signal_validation_rows": len(signal_rows),
            "early_top_decile_video_count": len(early_top),
        },
        "attribution_comparison": attribution,
        "all_hits_keyword_aggregates_sample": [
            asdict(all_aggs[k])
            for k in sorted(all_aggs.keys())[:5]
        ],
        "evidence_strata_all_hits": stratify_evidence(all_aggs),
        "outlier_all_hits": outlier_summary(all_aggs),
        "scan_stability": per_scan_stability_production([]),
    }


def metric_decision_matrix(report: dict[str, Any]) -> dict[str, Any]:
    """Classify metrics for lifecycle design input (no scores/thresholds)."""
    c2 = (
        report.get("data_sources", {})
        .get("A_frozen_experiment_cohorts", {})
        .get("cohort_2", {})
    )
    q1 = (
        c2.get("attribution_comparison", {})
        .get("all_hits", {})
        .get("q1", {})
    )
    rho_early = (
        q1.get("early_top_decile_rate_vs_median_absolute_view_growth_72h", {})
        .get("spearman", {})
        .get("rho")
    )
    rho_vph = (
        q1.get("median_vph_at_discovery_vs_median_absolute_view_growth_72h", {})
        .get("spearman", {})
        .get("rho")
    )
    prod = report.get("production", {})
    prod_usable = prod.get("coverage", {}).get("keywords_with_72h_outcomes", 0)

    def classify(name: str, rho: float | None, n: int) -> str:
        if n < 5:
            return "not_testable_with_current_data"
        if rho is None:
            return "not_testable_with_current_data"
        if abs(rho) >= 0.25 and n >= 8:
            return "useful_evidence"
        if abs(rho) >= 0.15:
            return "promising_but_insufficient_evidence"
        return "weak_or_redundant"

    kw_n = q1.get("keywords_with_any_72h_outcome", 0)
    matrix = {
        "early_top_decile_rate": classify("early_top_decile_rate", rho_early, kw_n),
        "median_vph_at_discovery": classify("median_vph_at_discovery", rho_vph, kw_n),
        "p90_vph_at_discovery": classify(
            "p90_vph_at_discovery",
            q1.get("p90_vph_at_discovery_vs_p90_absolute_view_growth_72h", {})
            .get("spearman", {})
            .get("rho"),
            kw_n,
        ),
        "cross_keyword_duplicate_rate": "promising_but_insufficient_evidence",
        "new_to_corpus_rate": (
            "not_testable_with_current_data"
            if prod_usable < 5
            else "promising_but_insufficient_evidence"
        ),
        "current_breakout_rank_live": "weak_or_redundant_for_historical_prediction",
        "confirmed_breakout_count_api_field": "legacy_alias_document_only",
    }
    return matrix


def confirmed_breakout_semantics_recommendation() -> dict[str, Any]:
    return {
        "current_mapping": "confirmed_breakout_count == top_decile_breakout_count (live global pool at evaluated_at)",
        "not_delayed_confirmation": True,
        "recommendation": "B",
        "recommendation_text": (
            "Retain API field for backward compatibility but document explicitly as "
            "top_decile_breakout_count alias; do not use the word 'confirmed' in "
            "historical validation or lifecycle copy."
        ),
        "optional_future_rename": "top_decile_breakout_count_live",
    }


def run_full_validation(
    artifacts_dir: Path,
    *,
    session: Session | None = None,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    contract = LeakageSafeFeatureContract()
    cohort1_path = artifacts_dir / COHORT_1_JOINED
    cohort2_path = artifacts_dir / COHORT_2_JOINED

    for name, expected in FROZEN_JOINED_SHA256.items():
        path = artifacts_dir / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"Frozen joined artifact missing or hash mismatch: {name}")

    frozen_1 = analyze_frozen_cohort(
        cohort1_path,
        cohort_id="T0_T67_20260914",
        elapsed_hours_label=67.0,
    )
    frozen_2 = analyze_frozen_cohort(
        cohort2_path,
        cohort_id="stage110_T0_T72_20260914",
        elapsed_hours_label=71.9567,
    )

    production_block: dict[str, Any] = {
        "attempted": session is not None,
        "limitations": [
            "Requires KeywordDiscoveryHit + VideoSnapshot coverage for 72h horizons.",
            "Early top decile uses discovery VPH across unique videos in window (not breakout_v1).",
        ],
    }
    if session is not None:
        prod_all, meta_all = build_production_observations(
            session,
            window_from=window_from,
            window_to=window_to,
            mode="all_hits",
        )
        prod_first, meta_first = build_production_observations(
            session,
            window_from=window_from,
            window_to=window_to,
            mode="first_discovery",
        )
        aggs_all = aggregate_keywords(prod_all)
        aggs_first = aggregate_keywords(prod_first)
        production_block.update(
            {
                "coverage": {
                    "all_hits_observations": meta_all.get("attributed_observation_count", 0),
                    "first_discovery_observations": meta_first.get("attributed_observation_count", 0),
                    "keywords_all_hits": len(aggs_all),
                    "keywords_with_72h_outcomes": sum(
                        1 for a in aggs_all.values() if a.observed_72h_video_count > 0
                    ),
                    "load_elapsed_seconds": meta_all.get("elapsed_seconds"),
                },
                "all_hits_q1": keyword_level_q1_analysis(aggs_all),
                "first_discovery_q1": keyword_level_q1_analysis(aggs_first),
                "scan_stability": per_scan_stability_production(prod_all),
                "evidence_strata": stratify_evidence(aggs_all),
                "outlier": outlier_summary(aggs_all),
                "redundancy_all_hits": redundancy_analysis(prod_all),
            },
        )
    else:
        production_block["note"] = "No DB session supplied; production section skipped."

    evidence_design = {
        "empirical_noise": (
            "Keyword-level Spearman usable N often <15 on stage110 pseudo-keywords; "
            "bootstrap CIs wide when attr_lt_10."
        ),
        "stability_improves": (
            "Frozen cohort 1 (broader multi-keyword export) increases keyword N vs cohort 2; "
            "strata attr_50_plus not populated for pseudo-keywords."
        ),
        "scan_vs_video_evidence": (
            "Production scan_stability requires discovery_run_id; video-count strata more "
            "informative than scan_count=1 frozen exports."
        ),
        "no_thresholds_set": True,
    }

    report: dict[str, Any] = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "leakage_safe_feature_contract": asdict(contract),
        "delayed_outcome_contract": {
            "target": contract.delayed_target,
            "horizon_hours": contract.horizon_hours,
            "tolerance_hours": contract.horizon_tolerance_hours,
            "first_hit_per_keyword_video": True,
            "no_imputation": True,
        },
        "data_sources": {
            "A_frozen_experiment_cohorts": {
                "cohort_1": frozen_1,
                "cohort_2": frozen_2,
            },
            "B_production_provenance": production_block,
            "C_pseudo_keyword_t0_keywords": {
                "equivalent_to_target_keyword_id": False,
                "used_in": ["frozen cohort attribution expansion"],
            },
        },
        "confirmed_breakout_count": confirmed_breakout_semantics_recommendation(),
        "metric_decision_matrix": {},
        "evidence_threshold_design_input": evidence_design,
        "implications_lifecycle_design": [
            "Prefer leakage-safe early_top_decile_by_discovery_vph over live breakout rank for feedback loops.",
            "Require minimum observed_72h_video_count before keyword promotion decisions (threshold TBD in 1.18E).",
            "Report scan-order sensitivity when showing first_discovery metrics alongside all_hits.",
            "Treat high duplicate rate as contextual (popular topics), not automatically penalized.",
        ],
        "limitations": [
            "Pseudo-keywords ≠ production TargetKeyword scheduling entities.",
            "Frozen outcomes fixed at join time; production path depends on snapshot density.",
            "Keyword-level N small; do not overclaim weak Spearman estimates.",
            "No keyword score or lifecycle automation produced in this stage.",
        ],
        "verification": {"NO_NETWORK": True, "NO_DB_WRITES": True},
    }
    report["metric_decision_matrix"] = metric_decision_matrix(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    c2 = report["data_sources"]["A_frozen_experiment_cohorts"]["cohort_2"]
    q1 = c2["attribution_comparison"]["all_hits"]["q1"]
    lines = [
        "# Keyword Performance Historical Validation (Stage 1.18C)",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Runtime: {report['runtime_seconds']}s",
        "",
        "## A. Data sources and coverage",
        "",
        f"- Cohort 2 joined: `{c2['joined_path']}` SHA256 `{c2['joined_sha256']}`",
        f"- Signal rows: {c2['row_counts']['signal_validation_rows']}",
        f"- Pseudo-keyword limitations: {', '.join(c2['limitations'])}",
        "",
        "## B. Leakage-safe early features",
        "",
    ]
    contract = report["leakage_safe_feature_contract"]
    lines.append(f"- Allowed: {', '.join(contract['allowed_early'])}")
    lines.append(f"- Forbidden: {', '.join(contract['forbidden_leaky'])}")
    lines.extend(
        [
            "",
            "## C. Delayed outcome",
            "",
            f"- {json.dumps(report['delayed_outcome_contract'], ensure_ascii=False)}",
            "",
            "## D. Q1 early signal vs delayed outcome (cohort 2, all_hits)",
            "",
        ],
    )
    for key, block in q1.items():
        if key.startswith("early_") or key.startswith("median_") or key.startswith("p90_"):
            sp = block.get("spearman", {})
            lines.append(f"- **{key}**: n={block.get('usable_keyword_n', sp.get('n'))} ρ={sp.get('rho')}")
            boot = block.get("bootstrap_ci", {})
            if boot.get("ci95_low") is not None:
                lines.append(f"  - bootstrap 95% CI: [{boot['ci95_low']}, {boot['ci95_high']}]")
    lines.extend(
        [
            "",
            "## E–H. Robustness, outliers, stability, redundancy",
            "",
            f"- Evidence strata (sample keys): {list(c2['evidence_strata_all_hits'].keys())[:5]}",
            f"- Outlier dominated keywords: {c2['outlier_all_hits']['outlier_dominated_keyword_count']}",
            f"- Attribution shared labels: {c2['attribution_comparison']['shared_keyword_labels']}",
            "",
            "## I. all_hits vs first_discovery",
            "",
        ],
    )
    comp = c2["attribution_comparison"]
    lines.append(
        f"- all_hits keywords={comp['all_hits']['keyword_count']} "
        f"obs={comp['all_hits']['observation_count']}",
    )
    lines.append(
        f"- first_discovery keywords={comp['first_discovery']['keyword_count']} "
        f"obs={comp['first_discovery']['observation_count']}",
    )
    lines.extend(
        [
            "",
            "## J. confirmed_breakout_count",
            "",
            f"- {report['confirmed_breakout_count']['recommendation_text']}",
            "",
            "## K–L. Metric decision matrix",
            "",
        ],
    )
    for metric, verdict in report["metric_decision_matrix"].items():
        lines.append(f"- `{metric}`: **{verdict}**")
    prod = report["data_sources"]["B_production_provenance"]
    lines.extend(
        [
            "",
            "## Production batch (if run)",
            "",
            f"- Attempted: {prod.get('attempted')}",
            f"- Coverage: {prod.get('coverage', prod.get('note', 'n/a'))}",
            "",
            "## M. Lifecycle design implications",
            "",
        ],
    )
    for item in report["implications_lifecycle_design"]:
        lines.append(f"- {item}")
    lines.extend(["", "## P. Limitations", ""])
    for item in report["limitations"]:
        lines.append(f"- {item}")
    return "\n".join(lines)


def write_artifacts(report: dict[str, Any], artifacts_dir: Path) -> dict[str, str]:
    json_path = artifacts_dir / "keyword_performance_validation_1_18c.json"
    md_path = artifacts_dir / "keyword_performance_validation_1_18c.md"
    json_text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    json_sha = sha256_file(json_path)
    md_body = render_markdown(report) + "\n"
    md_text = md_body + f"\n## N. Artifact SHA256\n\n- JSON: `{json_sha}`\n"
    md_path.write_text(md_text, encoding="utf-8")
    md_sha = sha256_file(md_path)
    return {
        "json_path": str(json_path.resolve()),
        "md_path": str(md_path.resolve()),
        "json_sha256": json_sha,
        "md_sha256": md_sha,
    }
