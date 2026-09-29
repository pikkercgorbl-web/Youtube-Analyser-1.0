"""Offline T0 → T67 outcome analysis (Stage 1.9D)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_candidate_analysis import _percentile, numeric_distribution
from app.services.radar_t0_data_quality import load_t0_jsonl

ANALYSIS_SCHEMA_VERSION = "1.9D"
ELAPSED_HOURS_LABEL = 67.0689

VPH_ANALYSIS_BINS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<=100", None, 100.0),
    ("100-1k", 100.0, 1000.0),
    ("1k-5k", 1000.0, 5000.0),
    ("5k-10k", 5000.0, 10000.0),
    ("10k-25k", 10000.0, 25000.0),
    ("25k-50k", 25000.0, 50000.0),
    (">50k", 50000.0, None),
)


def load_snapshot_jsonl(path: Path) -> list[dict[str, Any]]:
    return load_t0_jsonl(path)


def load_snapshot_meta(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_joined_dataset(snapshot_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per unique video_id with refresh_status == refreshed."""
    joined: list[dict[str, Any]] = []
    for record in snapshot_records:
        if record.get("refresh_status") != "refreshed":
            continue
        joined.append(
            {
                "video_id": record.get("video_id"),
                "t0_keywords": record.get("t0_keywords") or [],
                "t0_views": record.get("t0_views"),
                "t0_vph": record.get("t0_vph"),
                "t0_views_per_subscriber": record.get("t0_views_per_subscriber"),
                "t0_final_subscribers": record.get("t0_final_subscribers"),
                "t0_age_hours": record.get("t0_age_hours"),
                "t0_content_format": record.get("t0_content_format"),
                "t0_qualification_outcome": record.get("t0_qualification_outcome"),
                "t0_filter_reason": record.get("t0_filter_reason"),
                "current_views": record.get("current_views"),
                "absolute_view_growth": record.get("absolute_view_growth"),
                "view_growth_multiple": record.get("view_growth_multiple"),
                "avg_growth_views_per_hour": record.get("avg_growth_views_per_hour"),
                "elapsed_hours_from_t0": record.get("elapsed_hours_from_t0"),
            },
        )
    return joined


def _values(records: list[dict[str, Any]], field: str) -> list[float]:
    out: list[float] = []
    for record in records:
        value = record.get(field)
        if value is not None:
            out.append(float(value))
    return out


def spearman_correlation(xs: list[float], ys: list[float]) -> dict[str, Any]:
    if len(xs) != len(ys) or len(xs) < 2:
        return {"n": len(xs), "rho": None, "note": "insufficient pairs"}

    def ranks(values: list[float]) -> list[float]:
        indexed = sorted(enumerate(values), key=lambda item: item[1])
        ranks_out = [0.0] * len(values)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks_out[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks_out

    rx = ranks(xs)
    ry = ranks(ys)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(rx)))
    den_x = math.sqrt(sum((r - mx) ** 2 for r in rx))
    den_y = math.sqrt(sum((r - my) ** 2 for r in ry))
    if den_x == 0 or den_y == 0:
        return {"n": len(xs), "rho": None, "note": "zero variance"}
    rho = num / (den_x * den_y)
    return {"n": len(xs), "rho": round(rho, 4)}


def percentile_stats(values: list[float], *, include_p99: bool = True) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    sorted_values = sorted(values)
    stats = {
        "count": len(sorted_values),
        "min": round(sorted_values[0], 4),
        "median": round(_percentile(sorted_values, 50), 4),
        "p75": round(_percentile(sorted_values, 75), 4),
        "p90": round(_percentile(sorted_values, 90), 4),
        "p95": round(_percentile(sorted_values, 95), 4),
        "max": round(sorted_values[-1], 4),
    }
    if include_p99:
        stats["p99"] = round(_percentile(sorted_values, 99), 4)
    return stats


def percentile_thresholds(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p75": None, "p90": None, "p95": None, "p99": None}
    sorted_values = sorted(values)
    return {
        "p50": round(_percentile(sorted_values, 50), 4),
        "p75": round(_percentile(sorted_values, 75), 4),
        "p90": round(_percentile(sorted_values, 90), 4),
        "p95": round(_percentile(sorted_values, 95), 4),
        "p99": round(_percentile(sorted_values, 99), 4),
    }


def outcome_threshold_counts(values: list[float]) -> dict[str, Any]:
    thresholds = percentile_thresholds(values)
    counts: dict[str, Any] = {"thresholds": thresholds}
    for label, key in (
        ("top_50_pct", "p50"),
        ("top_25_pct", "p75"),
        ("top_10_pct", "p90"),
        ("top_5_pct", "p95"),
        ("top_1_pct", "p99"),
    ):
        threshold = thresholds.get(key.replace("p", "p") if False else key)
        if threshold is None:
            counts[label] = {"threshold": None, "count": 0}
        else:
            counts[label] = {
                "threshold": threshold,
                "count": sum(1 for value in values if value >= threshold),
            }
    return counts


def _assign_vph_bin(value: float | None) -> str:
    if value is None:
        return "missing"
    for label, lower, upper in VPH_ANALYSIS_BINS:
        if lower is None and upper is not None and value <= upper:
            return label
        if upper is None and lower is not None and value > lower:
            return label
        if lower is not None and upper is not None and lower < value <= upper:
            return label
    return ">50k"


def bin_analysis(
    records: list[dict[str, Any]],
    *,
    predictor_field: str,
    outcome_field: str = "absolute_view_growth",
    bin_fn: Any,
) -> dict[str, Any]:
    groups: dict[str, list[float]] = {}
    for record in records:
        outcome = record.get(outcome_field)
        if outcome is None:
            continue
        label = bin_fn(record.get(predictor_field))
        groups.setdefault(label, []).append(float(outcome))

    bins: dict[str, Any] = {}
    for label, values in sorted(groups.items(), key=lambda item: item[0]):
        bins[label] = {
            "n": len(values),
            "median_growth": round(_percentile(sorted(values), 50), 4) if values else None,
            "mean_growth": round(sum(values) / len(values), 4) if values else None,
        }
    return bins


def top_outcome_capture(
    records: list[dict[str, Any]],
    *,
    predictor_field: str,
    outcome_field: str = "absolute_view_growth",
    top_fraction: float = 0.10,
    predictor_top_fn: Any | None = None,
) -> dict[str, Any]:
    pairs = [
        (record, float(record[outcome_field]))
        for record in records
        if record.get(outcome_field) is not None and record.get(predictor_field) is not None
    ]
    if not pairs:
        return {"top_n": 0, "captured_in_predictor_top_bin": 0, "capture_rate": None}

    pairs.sort(key=lambda item: item[1], reverse=True)
    top_n = max(1, int(math.ceil(len(pairs) * top_fraction)))
    top_records = {item[0]["video_id"] for item in pairs[:top_n]}

    if predictor_top_fn is None:
        predictor_values = [float(item[0][predictor_field]) for item in pairs]
        cutoff = _percentile(sorted(predictor_values), 90)
        captured = sum(
            1
            for record, _ in pairs[:top_n]
            if float(record[predictor_field]) >= cutoff
        )
    else:
        captured = sum(1 for record, _ in pairs[:top_n] if predictor_top_fn(record.get(predictor_field)))

    return {
        "top_n": top_n,
        "captured_in_predictor_top_bin": captured,
        "capture_rate": round(captured / top_n, 4),
    }


def verify_data_quality(
    snapshot_records: list[dict[str, Any]],
    joined: list[dict[str, Any]],
) -> dict[str, Any]:
    video_ids = [str(record.get("video_id")) for record in joined]
    growth_values = _values(joined, "absolute_view_growth")
    return {
        "snapshot_rows": len(snapshot_records),
        "joined_refreshed_rows": len(joined),
        "missing_refresh_excluded": sum(
            1 for record in snapshot_records if record.get("refresh_status") != "refreshed"
        ),
        "duplicate_video_id_in_joined": len(video_ids) - len(set(video_ids)),
        "negative_absolute_growth_count": sum(
            1 for value in growth_values if value < 0
        ),
        "zero_absolute_growth_count": sum(1 for value in growth_values if value == 0),
        "t0_vph_available": sum(1 for record in joined if record.get("t0_vph") is not None),
        "t0_vph_missing": sum(1 for record in joined if record.get("t0_vph") is None),
        "t0_v_s_available": sum(
            1 for record in joined if record.get("t0_views_per_subscriber") is not None
        ),
        "t0_v_s_missing": sum(
            1 for record in joined if record.get("t0_views_per_subscriber") is None
        ),
        "t0_subscribers_available": sum(
            1 for record in joined if record.get("t0_final_subscribers") is not None
        ),
        "t0_age_available": sum(1 for record in joined if record.get("t0_age_hours") is not None),
    }


def _tertile_label(value: float | None, p33: float, p67: float) -> str:
    if value is None:
        return "missing"
    if value <= p33:
        return "low"
    if value <= p67:
        return "medium"
    return "high"


def _age_category(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0:
        return "invalid_or_zero"
    if value < 6:
        return "<6h"
    if value < 12:
        return "6-12h"
    if value < 18:
        return "12-18h"
    if value <= 24:
        return "18-24h"
    return ">24h"


def analyze_h3_combinations(joined: list[dict[str, Any]]) -> dict[str, Any]:
    vph_values = _values(joined, "t0_vph")
    vps_values = _values(joined, "t0_views_per_subscriber")
    if not vph_values:
        return {"note": "insufficient VPH data"}

    vph_p33 = _percentile(sorted(vph_values), 33.33)
    vph_p67 = _percentile(sorted(vph_values), 66.67)
    vps_p33 = _percentile(sorted(vps_values), 33.33) if vps_values else None
    vps_p67 = _percentile(sorted(vps_values), 66.67) if vps_values else None

    def vps_label(value: float | None) -> str:
        if value is None:
            return "missing"
        if vps_p33 is None or vps_p67 is None:
            return "missing"
        return _tertile_label(value, vps_p33, vps_p67)

    groups: dict[str, list[float]] = {}
    for record in joined:
        growth = record.get("absolute_view_growth")
        if growth is None:
            continue
        key = "|".join(
            [
                _tertile_label(record.get("t0_vph"), vph_p33, vph_p67),
                vps_label(record.get("t0_views_per_subscriber")),
                _age_category(record.get("t0_age_hours")),
            ],
        )
        groups.setdefault(key, []).append(float(growth))

    top10_threshold = _percentile(sorted(_values(joined, "absolute_view_growth")), 90)
    combo_stats: dict[str, Any] = {}
    for key, values in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        sorted_values = sorted(values)
        combo_stats[key] = {
            "n": len(values),
            "median_absolute_growth": round(_percentile(sorted_values, 50), 4),
            "p90_growth": round(_percentile(sorted_values, 90), 4),
            "top_10pct_hit_rate": round(
                sum(1 for value in values if value >= top10_threshold) / len(values),
                4,
            ),
        }
    return {
        "vph_cutoffs": {"p33": round(vph_p33, 4), "p67": round(vph_p67, 4)},
        "v_s_cutoffs": {"p33": round(vps_p33, 4) if vps_p33 else None, "p67": round(vps_p67, 4) if vps_p67 else None},
        "combinations": combo_stats,
    }


def _subscriber_size_band(value: float | None, p33: float, p67: float) -> str:
    if value is None:
        return "missing"
    if value <= p33:
        return "small"
    if value <= p67:
        return "medium"
    return "large"


def analyze_h4(joined: list[dict[str, Any]]) -> dict[str, Any]:
    with_subs = [
        record
        for record in joined
        if record.get("t0_final_subscribers") is not None
        and record.get("t0_vph") is not None
        and record.get("t0_views_per_subscriber") is not None
    ]
    if len(with_subs) < 30:
        return {"n": len(with_subs), "note": "sample too small for stable H4 comparison"}

    subs_values = sorted(_values(with_subs, "t0_final_subscribers"))
    vph_values = sorted(_values(with_subs, "t0_vph"))
    vps_values = sorted(_values(with_subs, "t0_views_per_subscriber"))
    subs_p33 = _percentile(subs_values, 33.33)
    subs_p67 = _percentile(subs_values, 66.67)
    vph_high = _percentile(vph_values, 67)
    vps_high = _percentile(vps_values, 67)

    def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        growth = _values(records, "absolute_view_growth")
        if not growth:
            return {"n": 0}
        sorted_growth = sorted(growth)
        return {
            "n": len(growth),
            "median_absolute_growth": round(_percentile(sorted_growth, 50), 4),
            "p90_absolute_growth": round(_percentile(sorted_growth, 90), 4),
        }

    def is_high_vph(record: dict[str, Any]) -> bool:
        vph = record.get("t0_vph")
        return vph is not None and float(vph) >= vph_high

    def is_high_vps(record: dict[str, Any]) -> bool:
        vps = record.get("t0_views_per_subscriber")
        return vps is not None and float(vps) >= vps_high

    cohorts = {
        "baseline_all_with_subs": with_subs,
        "high_vph_only": [record for record in with_subs if is_high_vph(record)],
        "high_v_s_only": [record for record in with_subs if is_high_vps(record)],
        "high_vph_high_v_s_small_or_medium_channel": [
            record
            for record in with_subs
            if is_high_vph(record)
            and is_high_vps(record)
            and _subscriber_size_band(record.get("t0_final_subscribers"), subs_p33, subs_p67)
            in {"small", "medium"}
        ],
        "large_channel_high_vph": [
            record
            for record in with_subs
            if is_high_vph(record)
            and _subscriber_size_band(record.get("t0_final_subscribers"), subs_p33, subs_p67) == "large"
        ],
    }

    return {
        "n_with_subscribers_vph_vps": len(with_subs),
        "subscriber_bands": {"p33": round(subs_p33, 4), "p67": round(subs_p67, 4)},
        "high_vph_cutoff": round(vph_high, 4),
        "high_v_s_cutoff": round(vps_high, 4),
        "cohorts": {name: summarize(records) for name, records in cohorts.items()},
    }


def qualification_comparison(joined: list[dict[str, Any]]) -> dict[str, Any]:
    growth_all = _values(joined, "absolute_view_growth")
    top10 = _percentile(sorted(growth_all), 90) if growth_all else None
    top5 = _percentile(sorted(growth_all), 95) if growth_all else None

    def group_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
        growth = _values(records, "absolute_view_growth")
        if not growth:
            return {"n": 0}
        sorted_growth = sorted(growth)
        return {
            "n": len(growth),
            "median_absolute_growth": round(_percentile(sorted_growth, 50), 4),
            "p90_absolute_growth": round(_percentile(sorted_growth, 90), 4),
            "top_10pct_share": round(
                sum(1 for value in growth if top10 is not None and value >= top10) / len(growth),
                4,
            )
            if top10 is not None
            else None,
            "top_5pct_share": round(
                sum(1 for value in growth if top5 is not None and value >= top5) / len(growth),
                4,
            )
            if top5 is not None
            else None,
        }

    passed = [record for record in joined if record.get("t0_qualification_outcome") == "passed"]
    rejected = [record for record in joined if record.get("t0_qualification_outcome") == "rejected"]

    rejected_top10 = [
        record
        for record in rejected
        if top10 is not None
        and record.get("absolute_view_growth") is not None
        and float(record["absolute_view_growth"]) >= top10
    ]
    reason_breakdown: dict[str, int] = {}
    for record in rejected_top10:
        reason = str(record.get("t0_filter_reason") or "unknown")
        reason_breakdown[reason] = reason_breakdown.get(reason, 0) + 1

    return {
        "passed": group_stats(passed),
        "rejected": group_stats(rejected),
        "rejected_in_top_10pct_future_growth": {
            "count": len(rejected_top10),
            "by_filter_reason": dict(sorted(reason_breakdown.items())),
        },
    }


def keyword_analysis(joined: list[dict[str, Any]]) -> dict[str, Any]:
    """Keyword strata allow multi-membership (documented)."""
    growth_all = _values(joined, "absolute_view_growth")
    top10 = _percentile(sorted(growth_all), 90) if growth_all else None
    by_keyword: dict[str, list[dict[str, Any]]] = {}
    for record in joined:
        for keyword in record.get("t0_keywords") or []:
            by_keyword.setdefault(str(keyword), []).append(record)

    rows: dict[str, Any] = {}
    for keyword, records in sorted(by_keyword.items()):
        growth = _values(records, "absolute_view_growth")
        vph = _values(records, "t0_vph")
        sorted_growth = sorted(growth)
        winner_count = (
            sum(1 for value in growth if top10 is not None and value >= top10)
            if top10 is not None
            else 0
        )
        rows[keyword] = {
            "n_membership_rows": len(records),
            "median_t0_vph": round(_percentile(sorted(vph), 50), 4) if vph else None,
            "median_absolute_growth": round(_percentile(sorted_growth, 50), 4) if growth else None,
            "p90_absolute_growth": round(_percentile(sorted_growth, 90), 4) if growth else None,
            "top_10pct_winner_count": winner_count,
            "winner_rate": round(winner_count / len(records), 4) if records else None,
        }
    return {
        "multi_keyword_membership_allowed": True,
        "keywords": rows,
    }


def extract_top_winners(joined: list[dict[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    records = [
        record
        for record in joined
        if record.get("absolute_view_growth") is not None
    ]
    records.sort(key=lambda item: float(item["absolute_view_growth"]), reverse=True)
    top: list[dict[str, Any]] = []
    for record in records[:limit]:
        top.append(
            {
                "video_id": record.get("video_id"),
                "keywords": record.get("t0_keywords"),
                "t0_views": record.get("t0_views"),
                "t0_vph": record.get("t0_vph"),
                "t0_v_s": record.get("t0_views_per_subscriber"),
                "subscribers": record.get("t0_final_subscribers"),
                "age": record.get("t0_age_hours"),
                "qualification_outcome": record.get("t0_qualification_outcome"),
                "filter_reason": record.get("t0_filter_reason"),
                "current_views": record.get("current_views"),
                "absolute_growth": record.get("absolute_view_growth"),
                "growth_multiple": record.get("view_growth_multiple"),
            },
        )
    return top


def extract_surprises(joined: list[dict[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    growth_values = _values(joined, "t0_views")
    views_median = _percentile(sorted(growth_values), 50) if growth_values else None
    top_records = extract_top_winners(joined, limit=max(limit * 3, 150))
    surprises: list[dict[str, Any]] = []
    for record in top_records:
        t0_views = record.get("t0_views")
        rejected = record.get("qualification_outcome") == "rejected"
        moderate_views = views_median is not None and t0_views is not None and float(t0_views) <= views_median
        if rejected or moderate_views:
            surprises.append({**record, "surprise_reason": "rejected" if rejected else "moderate_t0_views"})
        if len(surprises) >= limit:
            break
    return surprises


def run_outcome_analysis(
    *,
    snapshot_path: Path,
    snapshot_meta_path: Path,
    t0_manifest_path: Path | None = None,
) -> dict[str, Any]:
    snapshot_records = load_snapshot_jsonl(snapshot_path)
    meta = load_snapshot_meta(snapshot_meta_path)
    joined = build_joined_dataset(snapshot_records)
    data_quality = verify_data_quality(snapshot_records, joined)

    abs_growth = _values(joined, "absolute_view_growth")
    multiples = _values(joined, "view_growth_multiple")
    avg_rate = _values(joined, "avg_growth_views_per_hour")

    pairs_h0 = [
        (float(record["t0_views"]), float(record["absolute_view_growth"]))
        for record in joined
        if record.get("t0_views") is not None and record.get("absolute_view_growth") is not None
    ]
    pairs_h1 = [
        (float(record["t0_vph"]), float(record["absolute_view_growth"]))
        for record in joined
        if record.get("t0_vph") is not None and record.get("absolute_view_growth") is not None
    ]
    vps_rows = [
        record
        for record in joined
        if record.get("t0_views_per_subscriber") is not None
        and record.get("absolute_view_growth") is not None
    ]
    pairs_h2 = [
        (float(record["t0_views_per_subscriber"]), float(record["absolute_view_growth"]))
        for record in vps_rows
    ]

    h0 = {
        "spearman": spearman_correlation([p[0] for p in pairs_h0], [p[1] for p in pairs_h0]),
        "decile_bins": decile_bin_analysis(joined, "t0_views"),
        "top10_capture": top_outcome_capture(joined, predictor_field="t0_views"),
    }

    h1 = {
        "spearman": spearman_correlation([p[0] for p in pairs_h1], [p[1] for p in pairs_h1]),
        "vph_bins": bin_analysis(joined, predictor_field="t0_vph", bin_fn=_assign_vph_bin),
        "top10_capture": top_outcome_capture(
            joined,
            predictor_field="t0_vph",
            predictor_top_fn=lambda value: value is not None and float(value) >= _percentile(sorted(_values(joined, "t0_vph")), 90),
        ),
    }

    h2 = {
        "sample_size": len(vps_rows),
        "selection_bias_note": (
            "T0 V/S is only available where subscriber fetch succeeded; "
            "historically concentrated among passed / homepage_fetched channels."
        ),
        "spearman": spearman_correlation([p[0] for p in pairs_h2], [p[1] for p in pairs_h2]),
        "v_s_bins": bin_analysis(
            vps_rows,
            predictor_field="t0_views_per_subscriber",
            bin_fn=lambda value: _v_s_bin(float(value)) if value is not None else "missing",
        ),
        "top10_capture": top_outcome_capture(vps_rows, predictor_field="t0_views_per_subscriber"),
    }

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "elapsed_hours_from_t0": meta.get("elapsed_hours_from_t0", ELAPSED_HOURS_LABEL),
        "t0_manifest_path": str(t0_manifest_path) if t0_manifest_path else None,
        "snapshot_path": str(snapshot_path.resolve()),
        "snapshot_meta_path": str(snapshot_meta_path.resolve()),
        "data_quality": data_quality,
        "outcome_distributions": {
            "absolute_view_growth": {
                **percentile_stats(abs_growth),
                **outcome_threshold_counts(abs_growth),
            },
            "view_growth_multiple": percentile_stats(multiples),
            "avg_growth_views_per_hour": percentile_stats(avg_rate),
        },
        "hypotheses": {
            "H0_initial_views": h0,
            "H1_t0_vph": h1,
            "H2_views_per_subscriber": h2,
            "H3_vph_v_s_age": analyze_h3_combinations(joined),
            "H4_high_velocity_v_s_channel_size": analyze_h4(joined),
        },
        "qualification_comparison": qualification_comparison(joined),
        "keyword_analysis": keyword_analysis(joined),
        "top_winners": extract_top_winners(joined),
        "top_surprises": extract_surprises(joined),
        "conclusions": build_conclusions(h0, h1, h2),
        "limitations": [
            "Observational snapshot over ~67h; not causal.",
            "Missing refresh videos excluded; not counted as zero growth.",
            "V/S coverage is sparse and selection-biased.",
            "Cross-keyword duplicates collapsed in snapshot; keyword analysis uses multi-membership.",
            "Negative growth preserved and may reflect YouTube view count corrections.",
        ],
        "recommended_next_experiment": [
            "Define stratified sampling using keyword + VPH + age; keep missing V/S explicit.",
            "Re-run outcome window at >=72h if a longer horizon is needed.",
            "Compare qualification rule changes using rejected top-growth cohort as audit set.",
        ],
        "verification": {
            "NO_NETWORK_REQUESTS": True,
            "NO_DB_WRITES": True,
            "joined_rows": len(joined),
        },
        "_joined": joined,
    }


def decile_bin_analysis(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = _values(records, field)
    if not values:
        return {}
    sorted_values = sorted(values)
    decile_edges = [_percentile(sorted_values, p) for p in range(0, 101, 10)]

    def decile_label(value: float | None) -> str:
        if value is None:
            return "missing"
        v = float(value)
        for index in range(10):
            lower = decile_edges[index]
            upper = decile_edges[index + 1]
            if index == 9:
                if v >= lower:
                    return f"D{index + 1}"
            elif lower <= v <= upper:
                return f"D{index + 1}"
        return "D10"

    return bin_analysis(records, predictor_field=field, bin_fn=decile_label)


def _v_s_bin(value: float) -> str:
    if value < 0.1:
        return "<0.1"
    if value < 0.5:
        return "0.1-0.5"
    if value < 1.0:
        return "0.5-1"
    if value < 2.0:
        return "1-2"
    if value < 5.0:
        return "2-5"
    return ">=5"


def build_conclusions(h0: dict[str, Any], h1: dict[str, Any], h2: dict[str, Any]) -> dict[str, Any]:
    def strength(rho: float | None) -> str:
        if rho is None:
            return "unknown"
        ar = abs(rho)
        if ar < 0.1:
            return "weak"
        if ar < 0.3:
            return "medium"
        return "strong"

    h0_rho = h0["spearman"].get("rho")
    h1_rho = h1["spearman"].get("rho")
    h2_rho = h2["spearman"].get("rho")
    signals = [
        ("H0_t0_views", h0_rho),
        ("H1_t0_vph", h1_rho),
        ("H2_t0_v_s", h2_rho),
    ]
    strongest = max(signals, key=lambda item: abs(item[1]) if item[1] is not None else -1.0)
    return {
        "H0_summary": f"Initial T0 views were {strength(h0_rho)} associated with absolute growth (Spearman rho={h0_rho}).",
        "H1_summary": f"T0 VPH was {strength(h1_rho)} associated with absolute growth (Spearman rho={h1_rho}).",
        "H2_summary": f"T0 V/S was {strength(h2_rho)} associated with absolute growth among V/S-available rows (Spearman rho={h2_rho}); exploratory only.",
        "strongest_observed_signal": strongest[0],
        "strongest_rho": strongest[1],
    }


def render_outcome_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Outcome Analysis T0 → T67",
        "",
        f"**Elapsed hours:** {report.get('elapsed_hours_from_t0')}",
        f"**Joined refreshed rows:** {report['verification']['joined_rows']}",
        "",
        "## 1. Data quality",
        "",
        f"`{report['data_quality']}`",
        "",
        "## 2. Outcome distribution",
        "",
        f"`{report['outcome_distributions']}`",
        "",
        "## 3. H0 — initial views",
        "",
        f"`{report['hypotheses']['H0_initial_views']}`",
        "",
        "## 4. H1 — T0 VPH",
        "",
        f"`{report['hypotheses']['H1_t0_vph']}`",
        "",
        "## 5. H2 — Views/Subscribers",
        "",
        f"`{report['hypotheses']['H2_views_per_subscriber']}`",
        "",
        "## 6. H3 — VPH + V/S + Age",
        "",
        f"`{report['hypotheses']['H3_vph_v_s_age']}`",
        "",
        "## 7. H4 — velocity + V/S + channel size",
        "",
        f"`{report['hypotheses']['H4_high_velocity_v_s_channel_size']}`",
        "",
        "## 8. Passed vs rejected",
        "",
        f"`{report['qualification_comparison']}`",
        "",
        "## 9. Rejected future winners",
        "",
        f"`{report['qualification_comparison']['rejected_in_top_10pct_future_growth']}`",
        "",
        "## 10. Keyword differences",
        "",
        f"`{report['keyword_analysis']}`",
        "",
        "## 11. Top winners",
        "",
    ]
    for item in report.get("top_winners", [])[:10]:
        lines.append(f"- `{item['video_id']}` growth={item['absolute_growth']} vph={item['t0_vph']} outcome={item['qualification_outcome']}")
    lines.extend(["", "## 12. Conclusions", ""])
    for key, value in report.get("conclusions", {}).items():
        lines.append(f"- **{key}:** {value}")
    lines.extend(["", "## 13. Limitations", ""])
    for item in report.get("limitations", []):
        lines.append(f"- {item}")
    lines.extend(["", "## 14. Recommended next experiment", ""])
    for item in report.get("recommended_next_experiment", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_outcome_reports(
    report: dict[str, Any],
    *,
    output_dir: Path,
    review_id: str,
    export_joined: bool = True,
) -> tuple[Path, Path, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"radar_outcome_analysis_T0_to_T67_{review_id}.json"
    md_path = output_dir / f"radar_outcome_analysis_T0_to_T67_{review_id}.md"

    export_report = {key: value for key, value in report.items() if key != "_joined"}
    json_path.write_text(json.dumps(export_report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_outcome_markdown(export_report), encoding="utf-8")

    joined_path = None
    if export_joined and report.get("_joined"):
        joined_path = output_dir / f"radar_outcome_joined_T0_T67_{review_id}.jsonl"
        with joined_path.open("w", encoding="utf-8") as handle:
            for record in report["_joined"]:
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
    return json_path, md_path, joined_path
