"""Stage 1.10 independent validation outcome analysis (T0 → T24/T48/T72)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.radar_outcome_analysis import (
    decile_bin_analysis,
    percentile_stats,
    spearman_correlation,
    top_outcome_capture,
)
from app.services.radar_signal_robustness import bootstrap_stability, filter_vph_population
from app.services.radar_t0_data_quality import load_t0_jsonl

ANALYSIS_SCHEMA_VERSION = "1.10C_outcome"
EXPERIMENT_ID = "stage110_20260914_141029"
T0_REFERENCE = "2026-09-14T14:10:29.608646+00:00"

FROZEN_HASHES = {
    "broad": "3ded1f61efdb4d2d7ac504bf078ebdb5799e7459cb44a58afaf50159075ffe0a",
    "sample": "7fcade5724ca2b556aa86317f3110f8cea0a91c58c8e74863abb76c4fa122cc7",
    "manifest": "3034e8c1d049e6a0d43b596b258ede9734d60ce54b4673ee7f222e1671680ccd",
}

T24_JSONL_SHA256 = "9f0b3d762414736cfec0ca131309ab4cdd649e92525134e4360c0bb3801ca118"
T48_JSONL_SHA256 = "f1aa8bbbbe5c340a5a43b1fb9c72219724885e66c7b86222e86bc888ada24f12"

PRIMARY_OUTCOME = "absolute_view_growth"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_inputs(artifacts_dir: Path) -> dict[str, Any]:
    paths = {
        "broad": artifacts_dir / f"cohort_T0_{EXPERIMENT_ID}_broad.jsonl",
        "sample": artifacts_dir / f"cohort_T0_{EXPERIMENT_ID}_sample.jsonl",
        "manifest": artifacts_dir / f"cohort_T0_{EXPERIMENT_ID}_manifest.json",
        "freeze": artifacts_dir / f"cohort_T0_{EXPERIMENT_ID}_freeze.json",
    }
    observed = {key: sha256_file(path) for key, path in paths.items()}
    for key in ("broad", "sample", "manifest"):
        if observed[key] != FROZEN_HASHES[key]:
            raise ValueError(f"Frozen hash mismatch for {key}")

    sample_rows = load_t0_jsonl(paths["sample"])
    freeze = json.loads(paths["freeze"].read_text(encoding="utf-8"))
    frozen_ids = list(freeze["frozen_sample_video_ids"])
    sample_ids = [str(r["video_id"]) for r in sample_rows]

    return {
        "paths": paths,
        "observed_hashes": observed,
        "sample_row_count": len(sample_rows),
        "frozen_id_count": len(frozen_ids),
        "ids_match_freeze": sample_ids == frozen_ids,
        "duplicate_ids_in_sample": len(sample_ids) - len(set(sample_ids)),
        "sample_ids": sample_ids,
        "sample_rows_by_id": {str(r["video_id"]): r for r in sample_rows},
    }


def verify_checkpoint_artifacts(artifacts_dir: Path) -> dict[str, Any]:
    t24 = artifacts_dir / "cohort_T24_stage110_20260914_141029_20260915_141506.jsonl"
    t48 = artifacts_dir / "cohort_T48_stage110_20260914_141029_20260916_141206.jsonl"
    t72 = artifacts_dir / "cohort_T72_stage110_20260914_141029_20260917_140753.jsonl"
    t24_sha = sha256_file(t24)
    t48_sha = sha256_file(t48)
    if t24_sha != T24_JSONL_SHA256:
        raise ValueError("T24 artifact hash changed")
    if t48_sha != T48_JSONL_SHA256:
        raise ValueError("T48 artifact hash changed")
    return {
        "t24_path": t24,
        "t48_path": t48,
        "t72_path": t72,
        "t24_sha256": t24_sha,
        "t48_sha256": t48_sha,
        "t72_sha256": sha256_file(t72),
    }


def _avg_growth_rate(record: dict[str, Any]) -> float | None:
    growth = record.get("absolute_view_growth")
    elapsed = record.get("actual_elapsed_hours") or record.get("elapsed_hours_from_t0")
    if growth is None or elapsed is None or float(elapsed) <= 0:
        return None
    return round(float(growth) / float(elapsed), 4)


def build_joined_from_checkpoint(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same outcome semantics as Stage 1.9D: refreshed rows only, no imputation."""
    joined: list[dict[str, Any]] = []
    for record in records:
        if record.get("fetch_status") != "refreshed":
            continue
        joined.append(
            {
                "video_id": record.get("video_id"),
                "t0_keywords": record.get("t0_keywords") or ([record["keyword"]] if record.get("keyword") else []),
                "t0_views": record.get("t0_views") if record.get("t0_views") is not None else record.get("views_t0"),
                "t0_vph": record.get("t0_vph") if record.get("t0_vph") is not None else record.get("vph_at_t0"),
                "t0_views_per_subscriber": record.get("views_per_subscriber_at_t0"),
                "t0_final_subscribers": record.get("t0_final_subscribers") if record.get("t0_final_subscribers") is not None else record.get("final_subscribers"),
                "t0_age_hours": record.get("t0_age_hours") if record.get("t0_age_hours") is not None else record.get("age_hours_at_t0"),
                "t0_content_format": record.get("content_format") or record.get("t0_content_format"),
                "t0_qualification_outcome": record.get("t0_qualification_outcome") or record.get("qualification_state"),
                "t0_filter_reason": record.get("t0_filter_reason") or record.get("first_failure_reason"),
                "channel_baseline_status": record.get("channel_baseline_status"),
                "velocity_baseline_status": record.get("velocity_baseline_status"),
                "views_vs_channel_median": record.get("views_vs_channel_median"),
                "views_vs_channel_p75": record.get("views_vs_channel_p75"),
                "vph_vs_channel_median": record.get("vph_vs_channel_median"),
                "vph_vs_channel_p75": record.get("vph_vs_channel_p75"),
                "channel_view_baseline_available": record.get("channel_view_baseline_available"),
                "channel_velocity_baseline_available": record.get("channel_velocity_baseline_available"),
                "current_views": record.get("views_current") or record.get("current_views"),
                "absolute_view_growth": record.get("absolute_view_growth"),
                "view_growth_multiple": record.get("view_growth_multiple") or record.get("relative_view_growth"),
                "avg_growth_views_per_hour": _avg_growth_rate(record),
                "elapsed_hours_from_t0": record.get("actual_elapsed_hours") or record.get("elapsed_hours_from_t0"),
                "snapshot_captured_at": record.get("snapshot_captured_at"),
                "fetch_status": record.get("fetch_status"),
            },
        )
    return joined


def checkpoint_counts(records: list[dict[str, Any]]) -> dict[str, Any]:
    status = [str(r.get("fetch_status") or "unknown") for r in records]
    return {
        "cohort_rows": len(records),
        "refreshed": sum(1 for s in status if s == "refreshed"),
        "missing": sum(1 for s in status if s == "missing"),
        "failed": sum(1 for s in status if s == "failed"),
        "other": sum(1 for s in status if s not in {"refreshed", "missing", "failed"}),
        "elapsed_hours": records[0].get("actual_elapsed_hours") if records else None,
    }


def views_vs_vph_metrics(joined: list[dict[str, Any]]) -> dict[str, Any]:
    pairs_views = [
        (float(r["t0_views"]), float(r[PRIMARY_OUTCOME]))
        for r in joined
        if r.get("t0_views") is not None and r.get(PRIMARY_OUTCOME) is not None
    ]
    pairs_vph = [
        (float(r["t0_vph"]), float(r[PRIMARY_OUTCOME]))
        for r in joined
        if r.get("t0_vph") is not None and r.get(PRIMARY_OUTCOME) is not None
    ]
    h0 = {
        "spearman": spearman_correlation([p[0] for p in pairs_views], [p[1] for p in pairs_views]),
        "decile_bins": decile_bin_analysis(joined, "t0_views"),
        "top10_capture": top_outcome_capture(joined, predictor_field="t0_views"),
    }
    h1 = {
        "spearman": spearman_correlation([p[0] for p in pairs_vph], [p[1] for p in pairs_vph]),
        "top10_capture": top_outcome_capture(joined, predictor_field="t0_vph"),
    }
    rho_v = h0["spearman"].get("rho")
    rho_p = h1["spearman"].get("rho")
    return {
        "H0_t0_views": h0,
        "H1_t0_vph": h1,
        "delta_rho_vph_minus_views": round(rho_p - rho_v, 4) if rho_v is not None and rho_p is not None else None,
        "top10_recall_views": h0["top10_capture"].get("capture_rate"),
        "top10_recall_vph": h1["top10_capture"].get("capture_rate"),
    }


def channel_baseline_metrics(joined: list[dict[str, Any]]) -> dict[str, Any]:
    def _metrics_for_field(field: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        pairs = [
            (float(r[field]), float(r[PRIMARY_OUTCOME]))
            for r in records
            if r.get(field) is not None and r.get(PRIMARY_OUTCOME) is not None
        ]
        subset = [r for r in records if r.get(field) is not None]
        return {
            "n": len(pairs),
            "spearman": spearman_correlation([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else {"n": 0, "rho": None},
            "top10_capture": top_outcome_capture(subset, predictor_field=field) if subset else {},
        }

    by_status: dict[str, Any] = {}
    for status in ("ok", "partial", "insufficient", "unavailable"):
        subset = [r for r in joined if (r.get("channel_baseline_status") or "") == status]
        if not subset:
            continue
        by_status[status] = {
            "n_refreshed": len(subset),
            "views_vs_channel_median": _metrics_for_field("views_vs_channel_median", subset),
            "views_vs_channel_p75": _metrics_for_field("views_vs_channel_p75", subset),
            "vph_vs_channel_median": _metrics_for_field("vph_vs_channel_median", subset),
            "t0_vph_on_same_rows": _metrics_for_field("t0_vph", subset),
        }

    view_baseline_rows = [r for r in joined if r.get("channel_view_baseline_available") is True]
    velocity_rows = [r for r in joined if r.get("channel_velocity_baseline_available") is True]

    return {
        "by_channel_baseline_status": by_status,
        "view_baseline_available_n": len(view_baseline_rows),
        "velocity_baseline_available_n": len(velocity_rows),
        "incremental_view_baseline_subset": {
            "note": "Same refreshed rows with channel view baseline; compare view-relative vs raw VPH.",
            "t0_vph": _metrics_for_field("t0_vph", view_baseline_rows),
            "views_vs_channel_median": _metrics_for_field("views_vs_channel_median", view_baseline_rows),
            "vph_vs_channel_median": _metrics_for_field("vph_vs_channel_median", velocity_rows),
        },
    }


def missingness_analysis(
    checkpoint_records: list[dict[str, Any]],
    sample_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing_ids = [str(r["video_id"]) for r in checkpoint_records if r.get("fetch_status") == "missing"]
    refreshed_ids = [str(r["video_id"]) for r in checkpoint_records if r.get("fetch_status") == "refreshed"]

    def summarize(ids: list[str]) -> dict[str, Any]:
        rows = [sample_by_id[vid] for vid in ids if vid in sample_by_id]
        views = [float(r.get("t0_views") or r.get("discovery_views") or 0) for r in rows]
        vph = [float(r["vph_at_t0"]) for r in rows if r.get("vph_at_t0") is not None]
        baseline_status: dict[str, int] = {}
        for r in rows:
            st = str(r.get("channel_baseline_status") or "unknown")
            baseline_status[st] = baseline_status.get(st, 0) + 1
        return {
            "n": len(rows),
            "median_t0_views": round(sorted(views)[len(views) // 2], 4) if views else None,
            "median_t0_vph": round(sorted(vph)[len(vph) // 2], 4) if vph else None,
            "channel_baseline_status_counts": baseline_status,
        }

    return {
        "missing_video_ids": missing_ids,
        "missing_count": len(missing_ids),
        "refreshed_summary": summarize(refreshed_ids),
        "missing_summary": summarize(missing_ids),
    }


def compare_first_cohort(first_outcome_json: Path) -> dict[str, Any]:
    if not first_outcome_json.is_file():
        return {"note": "first cohort outcome file not found"}
    first = json.loads(first_outcome_json.read_text(encoding="utf-8"))
    h0 = first["hypotheses"]["H0_initial_views"]["spearman"]["rho"]
    h1 = first["hypotheses"]["H1_t0_vph"]["spearman"]["rho"]
    cap0 = first["hypotheses"]["H0_initial_views"]["top10_capture"]["capture_rate"]
    cap1 = first["hypotheses"]["H1_t0_vph"]["top10_capture"]["capture_rate"]
    return {
        "first_cohort_elapsed_hours": first.get("elapsed_hours_from_t0"),
        "first_cohort_joined_n": first["verification"]["joined_rows"],
        "first_cohort_spearman_views": h0,
        "first_cohort_spearman_vph": h1,
        "first_cohort_top10_capture_views": cap0,
        "first_cohort_top10_capture_vph": cap1,
    }


def run_stage110_outcome_analysis(
    *,
    artifacts_dir: Path,
    first_cohort_outcome: Path | None = None,
) -> dict[str, Any]:
    verified = verify_frozen_inputs(artifacts_dir)
    checkpoints = verify_checkpoint_artifacts(artifacts_dir)

    t24_records = load_t0_jsonl(checkpoints["t24_path"])
    t48_records = load_t0_jsonl(checkpoints["t48_path"])
    t72_records = load_t0_jsonl(checkpoints["t72_path"])

    for label, records in (("T24", t24_records), ("T48", t48_records), ("T72", t72_records)):
        ids = [str(r["video_id"]) for r in records]
        if ids != verified["sample_ids"]:
            raise ValueError(f"{label} video_id order mismatch vs frozen sample")
        if len(ids) != 500:
            raise ValueError(f"{label} row count {len(ids)} != 500")

    joined_t24 = build_joined_from_checkpoint(t24_records)
    joined_t48 = build_joined_from_checkpoint(t48_records)
    joined_t72 = build_joined_from_checkpoint(t72_records)

    q1_t72 = views_vs_vph_metrics(joined_t72)
    q1_t24 = views_vs_vph_metrics(joined_t24)
    q1_t48 = views_vs_vph_metrics(joined_t48)

    bootstrap = bootstrap_stability(filter_vph_population(joined_t72))

    growth = [float(r[PRIMARY_OUTCOME]) for r in joined_t72 if r.get(PRIMARY_OUTCOME) is not None]

    first_ref = compare_first_cohort(
        first_cohort_outcome or artifacts_dir / "radar_outcome_analysis_T0_to_T67_20260914_124311.json",
    )
    boot_first_path = artifacts_dir / "radar_signal_robustness_T0_to_T67_20260914_124311.json"
    if boot_first_path.is_file():
        first_ref["first_cohort_bootstrap"] = json.loads(boot_first_path.read_text(encoding="utf-8")).get("bootstrap")

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "t0_reference_timestamp": T0_REFERENCE,
        "input_verification": {
            "frozen_hashes": FROZEN_HASHES,
            "observed_hashes": verified["observed_hashes"],
            "sample_rows": verified["sample_row_count"],
            "ids_match_freeze": verified["ids_match_freeze"],
            "t24_t48_hashes_unchanged": True,
        },
        "checkpoint_usable_n": {
            "T24": checkpoint_counts(t24_records),
            "T48": checkpoint_counts(t48_records),
            "T72": checkpoint_counts(t72_records),
        },
        "outcome_definitions": {
            "primary_outcome": PRIMARY_OUTCOME,
            "secondary_outcomes": ["view_growth_multiple", "avg_growth_views_per_hour"],
            "analysis_population": "fetch_status == refreshed only; missing/failed excluded from association metrics",
            "no_imputation": True,
            "elapsed_hours_source": "actual_elapsed_hours per checkpoint artifact",
        },
        "outcome_distribution_t72": percentile_stats(growth),
        "Q1_vph_vs_views": {
            "final_T72": q1_t72,
            "interim_T24": q1_t24,
            "interim_T48": q1_t48,
            "bootstrap_t72": bootstrap,
        },
        "Q2_channel_baseline": channel_baseline_metrics(joined_t72),
        "checkpoint_stability": {
            "spearman_views": {
                "T24": q1_t24["H0_t0_views"]["spearman"],
                "T48": q1_t48["H0_t0_views"]["spearman"],
                "T72": q1_t72["H0_t0_views"]["spearman"],
            },
            "spearman_vph": {
                "T24": q1_t24["H1_t0_vph"]["spearman"],
                "T48": q1_t48["H1_t0_vph"]["spearman"],
                "T72": q1_t72["H1_t0_vph"]["spearman"],
            },
            "delta_rho_vph_minus_views": {
                "T24": q1_t24["delta_rho_vph_minus_views"],
                "T48": q1_t48["delta_rho_vph_minus_views"],
                "T72": q1_t72["delta_rho_vph_minus_views"],
            },
        },
        "missingness_t72": missingness_analysis(t72_records, verified["sample_rows_by_id"]),
        "first_cohort_comparison": first_ref,
        "verification": {
            "NO_NETWORK_REQUESTS": True,
            "NO_DB_WRITES": True,
            "NO_FROZEN_MUTATION": True,
        },
        "_joined_t72": joined_t72,
    }
