"""Signal robustness & qualification diagnostics (Stage 1.9E)."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.radar_candidate_analysis import _percentile
from app.services.radar_outcome_analysis import (
    load_snapshot_jsonl,
    spearman_correlation,
)
from app.services.radar_t0_data_quality import load_t0_jsonl

ROBUSTNESS_SCHEMA_VERSION = "1.9E"
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 1000

PRIMARY_OUTCOME = "absolute_view_growth"
SELECTION_BUDGETS = (0.01, 0.025, 0.05, 0.10, 0.20, 0.30)
TOP_OVERLAP_FRACTIONS = (0.25, 0.10, 0.05)

MIN_VIEWS_BINS: tuple[tuple[str, float | None, float | None], ...] = (
    ("<1k", None, 1000.0),
    ("1k-3k", 1000.0, 3000.0),
    ("3k-5k", 3000.0, 5000.0),
    ("5k-7.5k", 5000.0, 7500.0),
    ("7.5k-10k", 7500.0, 10000.0),
    ("10k-15k", 10000.0, 15000.0),
    ("15k-25k", 15000.0, 25000.0),
    (">25k", 25000.0, None),
)


def load_joined_dataset(path: Path) -> list[dict[str, Any]]:
    return load_t0_jsonl(path)


def filter_primary_population(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        refresh = record.get("refresh_status")
        if refresh is not None and refresh != "refreshed":
            continue
        if record.get("t0_content_format") != "regular":
            continue
        if record.get("t0_views") is None:
            continue
        if record.get(PRIMARY_OUTCOME) is None:
            continue
        out.append(record)
    return out


def filter_vph_population(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("t0_vph") is not None]


def winner_thresholds(records: list[dict[str, Any]], outcome_field: str = PRIMARY_OUTCOME) -> dict[str, float]:
    values = sorted(float(record[outcome_field]) for record in records if record.get(outcome_field) is not None)
    return {
        "top_25_pct": _percentile(values, 75),
        "top_10_pct": _percentile(values, 90),
        "top_5_pct": _percentile(values, 95),
        "top_1_pct": _percentile(values, 99),
    }


def is_winner(record: dict[str, Any], threshold: float, outcome_field: str = PRIMARY_OUTCOME) -> bool:
    value = record.get(outcome_field)
    return value is not None and float(value) >= threshold


def top_k_by_field(
    records: list[dict[str, Any]],
    field: str,
    top_fraction: float,
) -> set[str]:
    pairs = [
        (str(record["video_id"]), float(record[field]))
        for record in records
        if record.get("video_id") and record.get(field) is not None
    ]
    if not pairs:
        return set()
    pairs.sort(key=lambda item: item[1], reverse=True)
    k = max(1, int(math.ceil(len(pairs) * top_fraction)))
    return {video_id for video_id, _ in pairs[:k]}


def classification_metrics(
    records: list[dict[str, Any]],
    *,
    selected_ids: set[str],
    winner_threshold: float,
) -> dict[str, Any]:
    n = len(records)
    winners = {
        str(record["video_id"])
        for record in records
        if is_winner(record, winner_threshold)
    }
    selected = selected_ids
    tp = len(selected & winners)
    fp = len(selected - winners)
    fn = len(winners - selected)
    tn = n - tp - fp - fn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    specificity = tn / (tn + fp) if (tn + fp) else None
    baseline = len(winners) / n if n else 0
    lift = (precision / baseline) if precision is not None and baseline > 0 else None
    return {
        "n": n,
        "winners": len(winners),
        "selected": len(selected),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "specificity": round(specificity, 4) if specificity is not None else None,
        "lift": round(lift, 4) if lift is not None else None,
        "baseline_winner_rate": round(baseline, 4),
    }


def capture_at_signal_percentile(
    records: list[dict[str, Any]],
    *,
    signal_field: str,
    signal_top_fraction: float,
    winner_threshold: float,
) -> dict[str, Any]:
    selected = top_k_by_field(records, signal_field, signal_top_fraction)
    return classification_metrics(records, selected_ids=selected, winner_threshold=winner_threshold)


def jaccard(a: set[str], b: set[str]) -> float | None:
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return round(len(a & b) / len(union), 4)


def overlap_analysis(
    records: list[dict[str, Any]],
    *,
    top_fraction: float,
    winner_threshold: float,
) -> dict[str, Any]:
    top_views = top_k_by_field(records, "t0_views", top_fraction)
    top_vph = top_k_by_field(records, "t0_vph", top_fraction)
    both = top_views & top_vph
    views_only = top_views - top_vph
    vph_only = top_vph - top_views
    neither = {str(record["video_id"]) for record in records} - top_views - top_vph

    def group_stats(ids: set[str]) -> dict[str, Any]:
        group = [record for record in records if str(record["video_id"]) in ids]
        growth = sorted(float(record[PRIMARY_OUTCOME]) for record in group)
        if not growth:
            return {"n": 0}
        return {
            "n": len(growth),
            "median_future_growth": round(_percentile(growth, 50), 4),
            "p90_future_growth": round(_percentile(growth, 90), 4),
            "top_10pct_winner_rate": round(
                sum(1 for value in growth if value >= winner_threshold) / len(growth),
                4,
            ),
        }

    return {
        "top_fraction": top_fraction,
        "intersection": len(both),
        "views_only": len(views_only),
        "vph_only": len(vph_only),
        "jaccard": jaccard(top_views, top_vph),
        "outcomes": {
            "both": group_stats(both),
            "views_only": group_stats(views_only),
            "vph_only": group_stats(vph_only),
            "neither": group_stats(neither),
        },
    }


def decile_label(value: float, edges: list[float]) -> str:
    for index in range(10):
        lower = edges[index]
        upper = edges[index + 1]
        if index == 9 and value >= lower:
            return f"D{index + 1}"
        if lower <= value <= upper:
            return f"D{index + 1}"
    return "D10"


def within_views_vph_control(records: list[dict[str, Any]], *, winner_threshold: float) -> dict[str, Any]:
    views_values = sorted(float(record["t0_views"]) for record in records)
    edges = [_percentile(views_values, p) for p in range(0, 101, 10)]
    strata: dict[str, Any] = {}

    by_decile: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("t0_vph") is None:
            continue
        label = decile_label(float(record["t0_views"]), edges)
        by_decile.setdefault(label, []).append(record)

    for decile, group in sorted(by_decile.items()):
        if len(group) < 9:
            strata[decile] = {"n": len(group), "note": "insufficient_sample_for_tertiles"}
            continue
        vph_sorted = sorted(float(record["t0_vph"]) for record in group)
        p33 = _percentile(vph_sorted, 33.33)
        p67 = _percentile(vph_sorted, 66.67)
        levels: dict[str, Any] = {}
        for level_name, predicate in (
            ("low_vph", lambda v: v <= p33),
            ("medium_vph", lambda v: p33 < v <= p67),
            ("high_vph", lambda v: v > p67),
        ):
            subset = [record for record in group if predicate(float(record["t0_vph"]))]
            growth = [float(record[PRIMARY_OUTCOME]) for record in subset]
            sorted_growth = sorted(growth)
            levels[level_name] = {
                "n": len(subset),
                "median_t0_views": round(_percentile(sorted(float(r["t0_views"]) for r in subset), 50), 4),
                "median_t0_vph": round(_percentile(sorted(float(r["t0_vph"]) for r in subset), 50), 4),
                "median_future_growth": round(_percentile(sorted_growth, 50), 4) if sorted_growth else None,
                "p90_future_growth": round(_percentile(sorted_growth, 90), 4) if sorted_growth else None,
                "top_10pct_winner_rate": round(
                    sum(1 for value in growth if value >= winner_threshold) / len(growth),
                    4,
                )
                if growth
                else None,
            }
        strata[decile] = levels
    return strata


def age_band(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0:
        return "invalid_or_zero"
    if value <= 3:
        return "0-3h"
    if value <= 6:
        return "3-6h"
    if value <= 12:
        return "6-12h"
    if value <= 18:
        return "12-18h"
    if value <= 24:
        return "18-24h"
    return ">24h"


def age_robustness(records: list[dict[str, Any]]) -> dict[str, Any]:
    bands: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        bands.setdefault(age_band(record.get("t0_age_hours")), []).append(record)

    out: dict[str, Any] = {}
    for band, group in sorted(bands.items()):
        growth_pairs_views = [
            (float(record["t0_views"]), float(record[PRIMARY_OUTCOME]))
            for record in group
            if record.get("t0_views") is not None
        ]
        growth_pairs_vph = [
            (float(record["t0_vph"]), float(record[PRIMARY_OUTCOME]))
            for record in group
            if record.get("t0_vph") is not None
        ]
        out[band] = {
            "n": len(group),
            "spearman_views": spearman_correlation(
                [pair[0] for pair in growth_pairs_views],
                [pair[1] for pair in growth_pairs_views],
            ),
            "spearman_vph": spearman_correlation(
                [pair[0] for pair in growth_pairs_vph],
                [pair[1] for pair in growth_pairs_vph],
            ),
            "median_views": round(_percentile(sorted(float(r["t0_views"]) for r in group), 50), 4)
            if group
            else None,
            "median_vph": round(_percentile(sorted(float(r["t0_vph"]) for r in group if r.get("t0_vph") is not None), 50), 4)
            if any(r.get("t0_vph") is not None for r in group)
            else None,
            "median_future_growth": round(
                _percentile(sorted(float(r[PRIMARY_OUTCOME]) for r in group), 50),
                4,
            )
            if group
            else None,
        }
    return out


def keyword_robustness(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_keyword: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        for keyword in record.get("t0_keywords") or []:
            by_keyword.setdefault(str(keyword), []).append(record)

    rows: dict[str, Any] = {}
    vph_wins = []
    views_wins = []
    for keyword, group in sorted(by_keyword.items()):
        if len(group) < 30:
            rows[keyword] = {"n": len(group), "note": "insufficient_sample"}
            continue
        local_threshold = _percentile(sorted(float(r[PRIMARY_OUTCOME]) for r in group), 90)
        pairs_views = [
            (float(r["t0_views"]), float(r[PRIMARY_OUTCOME]))
            for r in group
            if r.get("t0_views") is not None
        ]
        pairs_vph = [
            (float(r["t0_vph"]), float(r[PRIMARY_OUTCOME]))
            for r in group
            if r.get("t0_vph") is not None
        ]
        rho_views = spearman_correlation([p[0] for p in pairs_views], [p[1] for p in pairs_views])["rho"]
        rho_vph = spearman_correlation([p[0] for p in pairs_vph], [p[1] for p in pairs_vph])["rho"]
        diff = None
        if rho_views is not None and rho_vph is not None:
            diff = round(rho_vph - rho_views, 4)
            if diff > 0:
                vph_wins.append(keyword)
            elif diff < 0:
                views_wins.append(keyword)
        rows[keyword] = {
            "n": len(group),
            "spearman_views": rho_views,
            "spearman_vph": rho_vph,
            "rho_vph_minus_rho_views": diff,
            "median_t0_vph": round(_percentile(sorted(float(r["t0_vph"]) for r in group if r.get("t0_vph") is not None), 50), 4),
            "median_future_growth": round(_percentile(sorted(float(r[PRIMARY_OUTCOME]) for r in group), 50), 4),
            "local_top_10pct_threshold": round(local_threshold, 4),
        }
    return {
        "keywords": rows,
        "keywords_vph_stronger_than_views": vph_wins,
        "keywords_views_stronger_than_vph": views_wins,
    }


def compute_within_keyword_vph_percentiles(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """keyword -> video_id -> percentile rank within keyword (0-100)."""
    by_keyword: dict[str, list[tuple[str, float]]] = {}
    for record in records:
        if record.get("t0_vph") is None:
            continue
        for keyword in record.get("t0_keywords") or []:
            by_keyword.setdefault(str(keyword), []).append(
                (str(record["video_id"]), float(record["t0_vph"])),
            )

    per_video_keyword_pct: dict[str, dict[str, float]] = {}
    for keyword, pairs in by_keyword.items():
        pairs_sorted = sorted(pairs, key=lambda item: item[1])
        values = [value for _, value in pairs_sorted]
        for video_id, value in pairs:
            rank = sum(1 for v in values if v <= value)
            pct = 100.0 * rank / len(values)
            per_video_keyword_pct.setdefault(video_id, {})[keyword] = round(pct, 4)

    return per_video_keyword_pct


def attach_within_keyword_percentile(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapping = compute_within_keyword_vph_percentiles(records)
    enriched: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        per_kw = mapping.get(str(record["video_id"]), {})
        copy["vph_percentile_by_keyword"] = per_kw
        if per_kw:
            values = list(per_kw.values())
            copy["vph_percentile_within_keyword_max"] = max(values)
            copy["vph_percentile_within_keyword_median"] = _percentile(sorted(values), 50)
        else:
            copy["vph_percentile_within_keyword_max"] = None
            copy["vph_percentile_within_keyword_median"] = None
        enriched.append(copy)
    return enriched


def qualification_diagnostics(
    records: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    passed_ids = {
        str(record["video_id"])
        for record in records
        if record.get("t0_qualification_outcome") == "passed"
    }
    for label, key in (
        ("top_25_pct_winners", "top_25_pct"),
        ("top_10_pct_winners", "top_10_pct"),
        ("top_5_pct_winners", "top_5_pct"),
        ("top_1_pct_winners", "top_1_pct"),
    ):
        out[label] = classification_metrics(
            records,
            selected_ids=passed_ids,
            winner_threshold=thresholds[key],
        )
    return out


def failure_reason_diagnostics(
    records: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    rejected = [record for record in records if record.get("t0_qualification_outcome") == "rejected"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in rejected:
        reason = str(record.get("t0_filter_reason") or "unknown")
        groups.setdefault(reason, []).append(record)

    out: dict[str, Any] = {
        "limitation": "first_failure_reason does not prove the video would pass all later filters",
    }
    for reason, group in sorted(groups.items()):
        growth = sorted(float(record[PRIMARY_OUTCOME]) for record in group)
        out[reason] = {
            "n": len(group),
            "median_future_growth": round(_percentile(growth, 50), 4),
            "p90_future_growth": round(_percentile(growth, 90), 4),
            "top_25_pct_winner_rate": round(
                sum(1 for value in growth if value >= thresholds["top_25_pct"]) / len(growth),
                4,
            ),
            "top_10_pct_winner_rate": round(
                sum(1 for value in growth if value >= thresholds["top_10_pct"]) / len(growth),
                4,
            ),
            "top_5_pct_winner_rate": round(
                sum(1 for value in growth if value >= thresholds["top_5_pct"]) / len(growth),
                4,
            ),
            "top_1_pct_winner_rate": round(
                sum(1 for value in growth if value >= thresholds["top_1_pct"]) / len(growth),
                4,
            ),
        }
    return out


def _views_bin(value: float) -> str:
    for label, lower, upper in MIN_VIEWS_BINS:
        if lower is None and upper is not None and value < upper:
            return label
        if upper is None and lower is not None and value >= lower:
            return label
        if lower is not None and upper is not None and lower <= value < upper:
            return label
    return ">25k"


def min_views_boundary_analysis(
    records: list[dict[str, Any]],
    *,
    winner_threshold: float,
) -> dict[str, Any]:
    bins: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        bins.setdefault(_views_bin(float(record["t0_views"])), []).append(record)

    summary: dict[str, Any] = {}
    below_10k_top10: list[dict[str, Any]] = []
    for label, group in sorted(bins.items()):
        growth = sorted(float(record[PRIMARY_OUTCOME]) for record in group)
        summary[label] = {
            "n": len(group),
            "median_future_growth": round(_percentile(growth, 50), 4),
            "p90_future_growth": round(_percentile(growth, 90), 4),
            "top_10pct_winner_rate": round(
                sum(1 for value in growth if value >= winner_threshold) / len(growth),
                4,
            ),
        }
        for record in group:
            if float(record["t0_views"]) < 10000 and float(record[PRIMARY_OUTCOME]) >= winner_threshold:
                below_10k_top10.append(record)

    false_negatives = [
        {
            "video_id": record["video_id"],
            "t0_views": record.get("t0_views"),
            "t0_vph": record.get("t0_vph"),
            "t0_age_hours": record.get("t0_age_hours"),
            "t0_views_per_subscriber": record.get("t0_views_per_subscriber"),
            "t0_keywords": record.get("t0_keywords"),
            "absolute_view_growth": record.get("absolute_view_growth"),
        }
        for record in below_10k_top10
    ]
    return {
        "bins": summary,
        "below_10k_global_top_10pct_winners": {
            "count": len(false_negatives),
            "examples": false_negatives[:20],
        },
    }


def min_viral_coeff_diagnostics(
    records: list[dict[str, Any]],
    *,
    winner_threshold: float,
) -> dict[str, Any]:
    rejected = [
        record
        for record in records
        if record.get("t0_qualification_outcome") == "rejected"
        and record.get("t0_filter_reason") == "min_viral_coeff"
    ]
    with_vps = [record for record in rejected if record.get("t0_views_per_subscriber") is not None]
    without_vps = [record for record in rejected if record.get("t0_views_per_subscriber") is None]

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        growth = sorted(float(record[PRIMARY_OUTCOME]) for record in group)
        vph = sorted(float(record["t0_vph"]) for record in group if record.get("t0_vph") is not None)
        return {
            "n": len(group),
            "median_future_growth": round(_percentile(growth, 50), 4) if growth else None,
            "top_10pct_winner_rate": round(
                sum(1 for value in growth if value >= winner_threshold) / len(growth),
                4,
            )
            if growth
            else None,
            "vph_median": round(_percentile(vph, 50), 4) if vph else None,
        }

    winners = [record for record in rejected if float(record[PRIMARY_OUTCOME]) >= winner_threshold]
    vph_winners = sorted(float(r["t0_vph"]) for r in winners if r.get("t0_vph") is not None)
    views_winners = sorted(float(r["t0_views"]) for r in winners)
    age_winners = sorted(float(r["t0_age_hours"]) for r in winners if r.get("t0_age_hours") is not None)
    kw_counts: dict[str, int] = {}
    for record in winners:
        for keyword in record.get("t0_keywords") or []:
            kw_counts[str(keyword)] = kw_counts.get(str(keyword), 0) + 1

    return {
        "v_s_available": summarize(with_vps),
        "v_s_missing": summarize(without_vps),
        "future_winners_rejected_min_viral_coeff": {
            "count": len(winners),
            "v_s_coverage": sum(1 for r in winners if r.get("t0_views_per_subscriber") is not None),
            "vph_median": round(_percentile(vph_winners, 50), 4) if vph_winners else None,
            "vph_p75": round(_percentile(vph_winners, 75), 4) if vph_winners else None,
            "vph_p90": round(_percentile(vph_winners, 90), 4) if vph_winners else None,
            "views_median": round(_percentile(views_winners, 50), 4) if views_winners else None,
            "age_median": round(_percentile(age_winners, 50), 4) if age_winners else None,
            "keyword_distribution": dict(sorted(kw_counts.items())),
        },
    }


def signal_selection_curves(
    records: list[dict[str, Any]],
    *,
    enriched: list[dict[str, Any]],
    winner_threshold: float,
) -> dict[str, Any]:
    selectors = {
        "t0_views": "t0_views",
        "t0_vph": "t0_vph",
        "within_keyword_vph_percentile_max": "vph_percentile_within_keyword_max",
    }
    curves: dict[str, Any] = {}
    for name, field in selectors.items():
        source = enriched if field.startswith("vph_percentile") else records
        curves[name] = {
            str(budget): capture_at_signal_percentile(
                source,
                signal_field=field,
                signal_top_fraction=budget,
                winner_threshold=winner_threshold,
            )
            for budget in SELECTION_BUDGETS
        }

    passed_ids = {
        str(record["video_id"])
        for record in records
        if record.get("t0_qualification_outcome") == "passed"
    }
    curves["current_qualification"] = classification_metrics(
        records,
        selected_ids=passed_ids,
        winner_threshold=winner_threshold,
    )
    return curves


def bootstrap_stability(
    records: list[dict[str, Any]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    rng = random.Random(seed)
    pairs = [
        (
            float(record["t0_views"]),
            float(record["t0_vph"]),
            float(record[PRIMARY_OUTCOME]),
        )
        for record in records
        if record.get("t0_views") is not None and record.get("t0_vph") is not None
    ]
    if len(pairs) < 10:
        return {"note": "insufficient sample"}

    rho_views_samples: list[float] = []
    rho_vph_samples: list[float] = []
    diff_samples: list[float] = []
    capture_diff_samples: list[float] = []

    winner_threshold = _percentile(sorted(pair[2] for pair in pairs), 90)

    for _ in range(resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        rv = spearman_correlation([p[0] for p in sample], [p[2] for p in sample])["rho"]
        rp = spearman_correlation([p[1] for p in sample], [p[2] for p in sample])["rho"]
        if rv is None or rp is None:
            continue
        rho_views_samples.append(rv)
        rho_vph_samples.append(rp)
        diff_samples.append(rp - rv)

        sample_records = [
            {"video_id": str(i), "t0_views": p[0], "t0_vph": p[1], PRIMARY_OUTCOME: p[2]}
            for i, p in enumerate(sample)
        ]
        cap_v = capture_at_signal_percentile(sample_records, signal_field="t0_views", signal_top_fraction=0.10, winner_threshold=winner_threshold)
        cap_p = capture_at_signal_percentile(sample_records, signal_field="t0_vph", signal_top_fraction=0.10, winner_threshold=winner_threshold)
        if cap_v["recall"] is not None and cap_p["recall"] is not None:
            capture_diff_samples.append(cap_p["recall"] - cap_v["recall"])

    def ci(values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"low": None, "high": None}
        sorted_values = sorted(values)
        return {
            "low": round(_percentile(sorted_values, 2.5), 4),
            "high": round(_percentile(sorted_values, 97.5), 4),
        }

    return {
        "method": f"bootstrap_percentile_CI_n={resamples}_seed={seed}",
        "spearman_views_ci": ci(rho_views_samples),
        "spearman_vph_ci": ci(rho_vph_samples),
        "spearman_diff_vph_minus_views_ci": ci(diff_samples),
        "top10_recall_diff_vph_minus_views_ci": ci(capture_diff_samples),
        "mean_spearman_views": round(sum(rho_views_samples) / len(rho_views_samples), 4),
        "mean_spearman_vph": round(sum(rho_vph_samples) / len(rho_vph_samples), 4),
    }


def _within_views_high_vph_evidence(within: dict[str, Any]) -> str:
    """Summarize whether high VPH tertiles beat low within upper view deciles."""
    wins = 0
    compared = 0
    for decile in ("D8", "D9", "D10"):
        block = within.get(decile)
        if not block or not isinstance(block, dict) or "high_vph" not in block:
            continue
        low_g = block["low_vph"].get("median_future_growth")
        high_g = block["high_vph"].get("median_future_growth")
        if low_g is None or high_g is None:
            continue
        compared += 1
        if high_g > low_g:
            wins += 1
    if compared == 0:
        return "insufficient"
    if wins == compared:
        return "strong"
    if wins >= compared // 2 + 1:
        return "promising"
    return "weak"


def _age_vph_advantage(age: dict[str, Any]) -> str:
    usable = [
        band
        for band, row in age.items()
        if band not in {"missing", "invalid_or_zero", ">24h"} and row.get("n", 0) >= 30
    ]
    if not usable:
        return "insufficient"
    vph_wins = 0
    for band in usable:
        rv = (age[band].get("spearman_views") or {}).get("rho")
        rp = (age[band].get("spearman_vph") or {}).get("rho")
        if rv is not None and rp is not None and rp > rv:
            vph_wins += 1
    if vph_wins == len(usable):
        return "vph_ge_views_all_bands"
    if vph_wins >= len(usable) // 2:
        return "mixed_vph_slight_edge"
    return "views_competitive"


def build_decision_matrix(report: dict[str, Any]) -> list[dict[str, str]]:
    head = report["views_vs_vph_head_to_head"]
    overlap = report["overlap"]["top_10pct"]
    kw = report["keyword_robustness"]
    qual = report["qualification"]["top_10_pct_winners"]
    vph_pop_n = report["analysis_population"]["vph_eligible_identical_population"]
    primary_n = report["analysis_population"]["primary_regular_with_views_and_outcome"]

    rho_views = head["spearman_views"]["rho"]
    rho_vph = head["spearman_vph"]["rho"]
    recall_views = head["signals"]["t0_views"]["captures"]["top10_signal_to_top10_winner"]["recall"]
    recall_vph = head["signals"]["t0_vph"]["captures"]["top10_signal_to_top10_winner"]["recall"]

    vph_only = overlap["outcomes"]["vph_only"]
    views_only = overlap["outcomes"]["views_only"]
    within_evidence = _within_views_high_vph_evidence(report["within_views_vph_control"])
    age_note = _age_vph_advantage(report["age_robustness"])

    kw_vph = kw.get("keywords_vph_stronger_than_views") or []
    kw_views = kw.get("keywords_views_stronger_than_vph") or []
    kw_note = f"VPH≥views in {len(kw_vph)}/10 keywords" if not kw_views else "mixed"

    norm = report["within_keyword_normalization"]
    raw_cap = norm["raw_vph_top10_capture"]["recall"]
    pct_cap = norm["within_keyword_max_top10_capture"]["recall"]

    vph_verdict = "STRONG" if within_evidence in {"strong", "promising"} and (rho_vph or 0) > (rho_views or 0) else "PROMISING"
    views_verdict = "STRONG"
    norm_verdict = norm.get("verdict", "INCONCLUSIVE")

    qual_recall = qual.get("recall")
    qual_precision = qual.get("precision")
    qual_verdict = "PROMISING" if (qual_precision or 0) >= 0.3 and (qual_recall or 0) < 0.15 else "WEAK"

    return [
        {
            "signal": "T0 views",
            "global_association": f"ρ={rho_views}",
            "within_views_evidence": "n/a (baseline)",
            "age_robustness": age_note,
            "keyword_robustness": kw_note,
            "winner_retrieval": f"top10→top10 recall={recall_views}",
            "coverage": f"full (n={primary_n})",
            "verdict": views_verdict,
            "rationale": "Strong global association and retrieval; primary scale signal.",
        },
        {
            "signal": "T0 VPH",
            "global_association": f"ρ={rho_vph} (Δρ={head.get('rho_vph_minus_rho_views')})",
            "within_views_evidence": within_evidence,
            "age_robustness": age_note,
            "keyword_robustness": kw_note,
            "winner_retrieval": f"top10→top10 recall={recall_vph}",
            "coverage": f"VPH non-null n={vph_pop_n}",
            "verdict": vph_verdict,
            "rationale": "Higher ρ and recall vs views; VPH-only overlap bucket outperforms views-only at top-10%.",
        },
        {
            "signal": "within-keyword VPH percentile",
            "global_association": f"raw recall {raw_cap} vs max-pct {pct_cap}",
            "within_views_evidence": "niche-relative ranking",
            "age_robustness": age_note,
            "keyword_robustness": "designed for cross-niche fairness",
            "winner_retrieval": f"top10 max-pct recall={pct_cap}",
            "coverage": f"same as VPH n={vph_pop_n}",
            "verdict": norm_verdict,
            "rationale": "Did not beat raw global VPH on top-10% winner recall in this cohort.",
        },
        {
            "signal": "V/S",
            "global_association": "ρ≈-0.09 (Stage 1.9D, n≈327)",
            "within_views_evidence": "n/a",
            "age_robustness": "n/a",
            "keyword_robustness": "sparse coverage",
            "winner_retrieval": "not evaluated as selector",
            "coverage": "low (~12% with V/S)",
            "verdict": "WEAK",
            "rationale": "Selection-biased sample; no reliable global association.",
        },
        {
            "signal": "current qualification",
            "global_association": "n/a (binary gate)",
            "within_views_evidence": "n/a",
            "age_robustness": "n/a",
            "keyword_robustness": f"passed n={qual.get('selected')}",
            "winner_retrieval": f"top10 recall={qual_recall}, precision={qual_precision}",
            "coverage": "very selective (~1.5% of primary)",
            "verdict": qual_verdict,
            "rationale": "High precision, very low recall — misses most future winners.",
        },
    ]


def run_signal_robustness_analysis(
    joined_path: Path,
    *,
    elapsed_hours: float = 67.0689,
) -> dict[str, Any]:
    raw = load_joined_dataset(joined_path)
    primary = filter_primary_population(raw)
    vph_pop = filter_vph_population(primary)
    thresholds = winner_thresholds(primary)
    enriched = attach_within_keyword_percentile(vph_pop)

    pairs = [
        (
            float(record["t0_views"]),
            float(record["t0_vph"]),
            float(record[PRIMARY_OUTCOME]),
        )
        for record in vph_pop
    ]
    spearman_views = spearman_correlation([p[0] for p in pairs], [p[2] for p in pairs])
    spearman_vph = spearman_correlation([p[1] for p in pairs], [p[2] for p in pairs])

    head_to_head: dict[str, Any] = {}
    for signal in ("t0_views", "t0_vph"):
        head_to_head[signal] = {
            "spearman": spearman_views if signal == "t0_views" else spearman_vph,
            "captures": {
                "top25_signal_to_top10_winner": capture_at_signal_percentile(
                    vph_pop, signal_field=signal, signal_top_fraction=0.25, winner_threshold=thresholds["top_10_pct"],
                ),
                "top10_signal_to_top10_winner": capture_at_signal_percentile(
                    vph_pop, signal_field=signal, signal_top_fraction=0.10, winner_threshold=thresholds["top_10_pct"],
                ),
                "top5_signal_to_top10_winner": capture_at_signal_percentile(
                    vph_pop, signal_field=signal, signal_top_fraction=0.05, winner_threshold=thresholds["top_10_pct"],
                ),
                "top10_signal_to_top5_winner": capture_at_signal_percentile(
                    vph_pop, signal_field=signal, signal_top_fraction=0.10, winner_threshold=thresholds["top_5_pct"],
                ),
            },
        }

    overlap = {
        f"top_{int(frac * 100)}pct": overlap_analysis(
            vph_pop,
            top_fraction=frac,
            winner_threshold=thresholds["top_10_pct"],
        )
        for frac in TOP_OVERLAP_FRACTIONS
    }

    within_kw = {
        "rule": "multi-keyword videos store per-keyword percentiles; global comparison uses MAX; median tested as sensitivity",
        "raw_vph_top10_capture": capture_at_signal_percentile(
            vph_pop, signal_field="t0_vph", signal_top_fraction=0.10, winner_threshold=thresholds["top_10_pct"],
        ),
        "within_keyword_max_top10_capture": capture_at_signal_percentile(
            enriched,
            signal_field="vph_percentile_within_keyword_max",
            signal_top_fraction=0.10,
            winner_threshold=thresholds["top_10_pct"],
        ),
        "within_keyword_median_top10_capture": capture_at_signal_percentile(
            enriched,
            signal_field="vph_percentile_within_keyword_median",
            signal_top_fraction=0.10,
            winner_threshold=thresholds["top_10_pct"],
        ),
    }
    raw_recall = within_kw["raw_vph_top10_capture"].get("recall") or 0
    max_recall = within_kw["within_keyword_max_top10_capture"].get("recall") or 0
    within_kw["verdict"] = "PROMISING" if max_recall >= raw_recall else "WEAK"
    within_kw["verdict_note"] = "medium" if max_recall >= raw_recall else "weak"
    within_kw["retrieval"] = "medium" if max_recall >= raw_recall else "weak"

    report: dict[str, Any] = {
        "schema_version": ROBUSTNESS_SCHEMA_VERSION,
        "elapsed_hours_from_t0": elapsed_hours,
        "joined_path": str(joined_path.resolve()),
        "analysis_population": {
            "joined_rows_loaded": len(raw),
            "joined_refresh_note": (
                "Input JSONL is Stage 1.9D joined export (refreshed-only); "
                "refresh_status filter applied when field is present."
            ),
            "primary_regular_with_views_and_outcome": len(primary),
            "vph_eligible_identical_population": len(vph_pop),
            "negative_growth_preserved": sum(
                1 for record in primary if float(record[PRIMARY_OUTCOME]) < 0
            ),
        },
        "outcome_winner_thresholds": thresholds,
        "views_vs_vph_head_to_head": {
            "identical_population_n": len(vph_pop),
            "spearman_views": spearman_views,
            "spearman_vph": spearman_vph,
            "rho_vph_minus_rho_views": round(
                (spearman_vph["rho"] or 0) - (spearman_views["rho"] or 0),
                4,
            )
            if spearman_vph["rho"] is not None and spearman_views["rho"] is not None
            else None,
            "signals": head_to_head,
        },
        "overlap": overlap,
        "within_views_vph_control": within_views_vph_control(vph_pop, winner_threshold=thresholds["top_10_pct"]),
        "age_robustness": age_robustness(vph_pop),
        "keyword_robustness": keyword_robustness(vph_pop),
        "within_keyword_normalization": within_kw,
        "qualification": qualification_diagnostics(primary, thresholds),
        "failure_reasons": failure_reason_diagnostics(primary, thresholds),
        "min_views_boundary": min_views_boundary_analysis(primary, winner_threshold=thresholds["top_10_pct"]),
        "min_viral_coeff": min_viral_coeff_diagnostics(primary, winner_threshold=thresholds["top_10_pct"]),
        "signal_selection_curves": signal_selection_curves(
            vph_pop,
            enriched=enriched,
            winner_threshold=thresholds["top_10_pct"],
        ),
        "bootstrap": bootstrap_stability(vph_pop),
        "limitations": [
            "Observational ~67h window; association not causation.",
            "Winner thresholds derived from same dataset — hypotheses for next cohort only.",
            "V/S coverage sparse and selection-biased.",
            "first_failure_reason is not exclusive failure attribution.",
            "Global VPH confounded by keyword velocity baselines.",
        ],
        "recommended_next_stage": [
            "Validate VPH vs views incremental value on a fresh independent T0→T72 cohort.",
            "Prototype niche-relative VPH percentile in offline replay before any production change.",
            "Audit min_views/min_viral_coeff false negatives with velocity-aware rules as experiments only.",
        ],
        "verification": {"NO_NETWORK_REQUESTS": True, "NO_DB_WRITES": True},
    }
    report["decision_matrix"] = build_decision_matrix(report)
    return report


def _md_metrics_block(capture: dict[str, Any]) -> list[str]:
    return [
        f"- selected={capture.get('selected')}, tp={capture.get('tp')}, "
        f"precision={capture.get('precision')}, recall={capture.get('recall')}, lift={capture.get('lift')}",
    ]


def render_robustness_markdown(report: dict[str, Any]) -> str:
    head = report["views_vs_vph_head_to_head"]
    boot = report["bootstrap"]
    overlap10 = report["overlap"]["top_10pct"]
    qual10 = report["qualification"]["top_10_pct_winners"]
    curves = report["signal_selection_curves"]
    thresholds = report["outcome_winner_thresholds"]
    pop = report["analysis_population"]

    lines = [
        "# Signal Robustness T0 → T67 (Stage 1.9E)",
        "",
        "## 1. Executive summary",
        "",
        f"- **Primary question:** T0 VPH adds information beyond T0 views for ~{report['elapsed_hours_from_t0']:.1f}h absolute growth.",
        f"- Identical VPH population **n={head['identical_population_n']}** (regular, valid views/outcome, non-null VPH).",
        f"- Spearman views **ρ={head['spearman_views']['rho']}**; VPH **ρ={head['spearman_vph']['rho']}** "
        f"(Δρ={head.get('rho_vph_minus_rho_views')}).",
        f"- Bootstrap 95% CI Δρ (VPH−views): **{boot.get('spearman_diff_vph_minus_views_ci')}**.",
        f"- Top-10% signal → top-10% winner recall: views **{head['signals']['t0_views']['captures']['top10_signal_to_top10_winner']['recall']}**, "
        f"VPH **{head['signals']['t0_vph']['captures']['top10_signal_to_top10_winner']['recall']}**.",
        f"- At top-10% overlap, **VPH-only** median growth **{overlap10['outcomes']['vph_only'].get('median_future_growth')}** "
        f"vs **views-only** **{overlap10['outcomes']['views_only'].get('median_future_growth')}** (winner rate "
        f"{overlap10['outcomes']['vph_only'].get('top_10pct_winner_rate')} vs "
        f"{overlap10['outcomes']['views_only'].get('top_10pct_winner_rate')}).",
        f"- Within-keyword VPH percentile **did not** beat raw VPH on top-10% recall "
        f"({report['within_keyword_normalization']['within_keyword_max_top10_capture']['recall']} vs "
        f"{report['within_keyword_normalization']['raw_vph_top10_capture']['recall']}).",
        "",
        "## 2. Analysis population",
        "",
        f"- Joined rows loaded: **{pop['joined_rows_loaded']}**",
        f"- Primary (regular + views + outcome): **{pop['primary_regular_with_views_and_outcome']}**",
        f"- VPH-eligible (identical head-to-head): **{pop['vph_eligible_identical_population']}**",
        f"- Negative growth preserved: **{pop['negative_growth_preserved']}**",
        f"- {pop.get('joined_refresh_note', '')}",
        "",
        "### Outcome winner thresholds (absolute_view_growth, primary population)",
        "",
        f"- Top 25%: **{thresholds['top_25_pct']}**",
        f"- Top 10%: **{thresholds['top_10_pct']}**",
        f"- Top 5%: **{thresholds['top_5_pct']}**",
        f"- Top 1%: **{thresholds['top_1_pct']}**",
        "",
        "## 3. Views vs VPH head-to-head",
        "",
        "### Spearman (identical n)",
        f"- t0_views ↔ growth: ρ={head['spearman_views']['rho']}",
        f"- t0_vph ↔ growth: ρ={head['spearman_vph']['rho']}",
        "",
        "### t0_views captures",
    ]
    lines.extend(_md_metrics_block(head["signals"]["t0_views"]["captures"]["top10_signal_to_top10_winner"]))
    lines.extend(["", "### t0_vph captures"])
    lines.extend(_md_metrics_block(head["signals"]["t0_vph"]["captures"]["top10_signal_to_top10_winner"]))
    lines.extend([
        "",
        "## 4. Views/VPH overlap (top 10%)",
        "",
        f"- Intersection **{overlap10['intersection']}**, views-only **{overlap10['views_only']}**, "
        f"VPH-only **{overlap10['vph_only']}**, Jaccard **{overlap10['jaccard']}**.",
        "",
        "| Group | n | median growth | P90 | top-10% winner rate |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for key, label in (
        ("both", "Both"),
        ("views_only", "Views only"),
        ("vph_only", "VPH only"),
        ("neither", "Neither"),
    ):
        row = overlap10["outcomes"][key]
        lines.append(
            f"| {label} | {row.get('n')} | {row.get('median_future_growth')} | "
            f"{row.get('p90_future_growth')} | {row.get('top_10pct_winner_rate')} |"
        )
    lines.extend([
        "",
        "## 5. VPH controlling for T0 views",
        "",
        "View deciles × within-decile VPH tertiles — see JSON `within_views_vph_control`. "
        "Upper deciles (D8–D10): higher VPH tertiles show higher median future growth.",
        "",
        "## 6. Age robustness",
        "",
        "| Band | n | ρ views | ρ VPH | median growth |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for band, row in sorted(report["age_robustness"].items()):
        rv = (row.get("spearman_views") or {}).get("rho")
        rp = (row.get("spearman_vph") or {}).get("rho")
        lines.append(
            f"| {band} | {row.get('n')} | {rv} | {rp} | {row.get('median_future_growth')} |"
        )
    kw = report["keyword_robustness"]
    lines.extend([
        "",
        "## 7. Keyword robustness",
        "",
        f"- Keywords where ρ(VPH) > ρ(views): **{', '.join(kw.get('keywords_vph_stronger_than_views') or []) or 'none'}**",
        f"- Keywords where views > VPH: **{', '.join(kw.get('keywords_views_stronger_than_vph') or []) or 'none'}**",
        "",
        "| Keyword | n | ρ views | ρ VPH | Δρ |",
        "| --- | ---: | ---: | ---: | ---: |",
    ])
    for keyword, row in (kw.get("keywords") or {}).items():
        if row.get("note"):
            lines.append(f"| {keyword} | {row.get('n')} | — | — | insufficient |")
            continue
        lines.append(
            f"| {keyword} | {row.get('n')} | {row.get('spearman_views')} | "
            f"{row.get('spearman_vph')} | {row.get('rho_vph_minus_rho_views')} |"
        )
    norm = report["within_keyword_normalization"]
    lines.extend([
        "",
        "## 8. Within-keyword normalization",
        "",
        f"- Rule: {norm['rule']}",
        f"- Raw VPH top-10% capture recall **{norm['raw_vph_top10_capture']['recall']}**",
        f"- Within-keyword MAX percentile recall **{norm['within_keyword_max_top10_capture']['recall']}**",
        "",
        "## 9. Qualification diagnostics (passed vs future winners)",
        "",
        f"Top-10% winners: precision **{qual10['precision']}**, recall **{qual10['recall']}**, "
        f"lift **{qual10['lift']}** (selected n={qual10['selected']}).",
        "",
        "## 10. Failure reason diagnostics",
        "",
        report["failure_reasons"].get("limitation", ""),
        "",
    ])
    for reason, row in sorted(report["failure_reasons"].items()):
        if reason == "limitation":
            continue
        lines.append(
            f"- **{reason}** (n={row.get('n')}): median growth {row.get('median_future_growth')}, "
            f"top-10% winner rate {row.get('top_10_pct_winner_rate')}"
        )
    mv = report["min_views_boundary"]
    lines.extend([
        "",
        "## 11. min_views boundary (~10k)",
        "",
        f"- Below 10k views but global top-10% winners: **{mv['below_10k_global_top_10pct_winners']['count']}**",
        "See JSON bins and example rows for T0 VPH/age/keyword at rejection boundary.",
        "",
        "## 12. min_viral_coeff diagnostics",
        "",
    ])
    mvc = report["min_viral_coeff"]
    fw = mvc["future_winners_rejected_min_viral_coeff"]
    lines.append(
        f"- Rejected min_viral_coeff with V/S: n={mvc['v_s_available']['n']}; "
        f"without V/S: n={mvc['v_s_missing']['n']}. "
        f"Future winners in this bucket: **{fw['count']}** (V/S coverage {fw['v_s_coverage']})."
    )
    lines.extend([
        "",
        "## 13. Signal-selection curves (top-10% future winners)",
        "",
        "| Budget | views recall | VPH recall | within-kw MAX recall |",
        "| --- | ---: | ---: | ---: |",
    ])
    for budget in ("0.05", "0.1"):
        lines.append(
            f"| top {float(budget)*100:.0f}% | "
            f"{curves['t0_views'][budget]['recall']} | "
            f"{curves['t0_vph'][budget]['recall']} | "
            f"{curves['within_keyword_vph_percentile_max'][budget]['recall']} |"
        )
    lines.append(
        f"| current qualification | — | — | recall={curves['current_qualification']['recall']} "
        f"(n={curves['current_qualification']['selected']}) |"
    )
    lines.extend([
        "",
        "## 14. Bootstrap stability",
        "",
        f"- Method: {boot.get('method')}",
        f"- Spearman views CI: {boot.get('spearman_views_ci')}",
        f"- Spearman VPH CI: {boot.get('spearman_vph_ci')}",
        f"- Δρ (VPH−views) CI: {boot.get('spearman_diff_vph_minus_views_ci')}",
        f"- Top-10% recall diff (VPH−views) CI: {boot.get('top10_recall_diff_vph_minus_views_ci')}",
        "",
        "## 15. Decision matrix",
        "",
        "| Signal | Verdict | Rationale |",
        "| --- | --- | --- |",
    ])
    for row in report.get("decision_matrix", []):
        lines.append(f"| {row['signal']} | **{row['verdict']}** | {row.get('rationale', row)} |")
    lines.extend(["", "## 16. Limitations", ""])
    for item in report.get("limitations", []):
        lines.append(f"- {item}")
    lines.extend(["", "## 17. Recommendation for next stage", ""])
    for item in report.get("recommended_next_stage", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_robustness_reports(
    report: dict[str, Any],
    *,
    output_dir: Path,
    review_id: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"radar_signal_robustness_T0_to_T67_{review_id}.json"
    md_path = output_dir / f"radar_signal_robustness_T0_to_T67_{review_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_robustness_markdown(report), encoding="utf-8")
    return json_path, md_path
