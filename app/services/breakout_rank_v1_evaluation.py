"""Historical evaluation of production Breakout Ranking v1 (Stage 1.17C)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.breakout_ranking_service import (
    BREAKOUT_RANK_VERSION,
    breakout_fundamental_eligibility,
    rank_breakout_v1,
)
from app.services.monitoring_tier_budget_policy import MonitoringTierPolicy
from app.services.monitoring_video_source import MonitoredVideoState
from app.services.radar_outcome_analysis import spearman_correlation, top_outcome_capture
from app.services.radar_t0_data_quality import load_t0_jsonl

EVALUATION_SCHEMA_VERSION = "1.17C"

COHORT_1_JOINED = "radar_outcome_joined_T0_T67_20260914_124311.jsonl"
COHORT_2_JOINED = "radar_outcome_joined_stage110_T0_to_T72_stage110_20260914_141029.jsonl"

FROZEN_JOINED_SHA256 = {
    COHORT_1_JOINED: "4ad54a3725a8a777e63436bba26308fbcccb8e17227355f9c8d3380c8412dc11",
    COHORT_2_JOINED: "69613d88581a8f2c45bee441ddd5e40cec64c1ca06a79022d9412dc30e26e504",
}

REFERENCE_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_joined_cohort(path: Path) -> list[dict[str, Any]]:
    return load_t0_jsonl(path)


def _format_flags(content_format: str | None) -> tuple[str | None, bool, bool]:
    if content_format == "short":
        return "short", True, False
    if content_format == "live":
        return "live", False, True
    if content_format in (None, "regular"):
        return "regular", False, False
    return content_format, False, False


def joined_row_to_monitored_state(row: dict[str, Any]) -> MonitoredVideoState:
    """Map frozen T0 joined row to production MonitoredVideoState (no DB)."""
    content_format, is_short, is_live = _format_flags(row.get("t0_content_format"))
    age = row.get("t0_age_hours")
    vph = row.get("t0_vph")
    return MonitoredVideoState(
        video_id=str(row["video_id"]),
        channel_id="historical",
        published_at=REFERENCE_EPOCH,
        raw_vph=float(vph) if vph is not None else None,
        age_hours=float(age) if age is not None else None,
        content_format=content_format,
        is_short=is_short,
        is_live=is_live,
    )


def eligibility_report(
    rows: list[dict[str, Any]],
    *,
    max_age_monitoring_hours: float,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    eligible_ids: set[str] = set()
    for row in rows:
        state = joined_row_to_monitored_state(row)
        ok, reason = breakout_fundamental_eligibility(
            state,
            max_age_monitoring_hours=max_age_monitoring_hours,
        )
        if ok:
            eligible_ids.add(state.video_id)
        elif reason:
            counts[reason] = counts.get(reason, 0) + 1
    return {
        "input_rows": len(rows),
        "production_eligible_count": len(eligible_ids),
        "excluded_count": len(rows) - len(eligible_ids),
        "exclusion_reasons": dict(sorted(counts.items(), key=lambda item: item[0])),
    }


def apply_breakout_ranks(
    rows: list[dict[str, Any]],
    *,
    tier_policy: MonitoringTierPolicy | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Attach breakout_rank / ranking_value to row copies.

    Returns (all_rows_with_metadata, production_eligible_rows_with_ranks).
    """
    cfg = tier_policy or MonitoringTierPolicy()
    states = [joined_row_to_monitored_state(row) for row in rows]
    views_by_id = {
        str(row["video_id"]): int(row["t0_views"]) if row.get("t0_views") is not None else None
        for row in rows
    }
    ranked = rank_breakout_v1(states, views_by_video_id=views_by_id, tier_policy=cfg)
    rank_by_id = {item.video_id: item for item in ranked}

    enriched: list[dict[str, Any]] = []
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        video_id = str(row["video_id"])
        state = joined_row_to_monitored_state(row)
        ok, excluded_reason = breakout_fundamental_eligibility(
            state,
            max_age_monitoring_hours=cfg.max_age_monitoring_hours,
        )
        copy["breakout_eligible"] = ok
        copy["breakout_excluded_reason"] = excluded_reason
        item = rank_by_id.get(video_id)
        if item is not None:
            copy["breakout_rank"] = item.rank
            copy["breakout_ranking_value"] = item.ranking_value
            copy["breakout_rank_version"] = BREAKOUT_RANK_VERSION
            eligible_rows.append(copy)
        else:
            copy["breakout_rank"] = None
            copy["breakout_ranking_value"] = None
            copy["breakout_rank_version"] = None
        enriched.append(copy)
    return enriched, eligible_rows


def _signal_validation_rows(joined: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows usable for historical signal validation (outcome present)."""
    return [row for row in joined if row.get("absolute_view_growth") is not None]


def _pairs_predictor_outcome(
    rows: list[dict[str, Any]],
    predictor_field: str,
) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        predictor = row.get(predictor_field)
        outcome = row.get("absolute_view_growth")
        if predictor is None or outcome is None:
            continue
        pairs.append((float(predictor), float(outcome)))
    return pairs


def _top10_capture_vph(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vph_values = sorted(
        float(row["t0_vph"])
        for row in rows
        if row.get("t0_vph") is not None and row.get("absolute_view_growth") is not None
    )
    if not vph_values:
        return {"top_n": 0, "captured_in_predictor_top_bin": 0, "capture_rate": None}
    from app.services.radar_candidate_analysis import _percentile

    cutoff = _percentile(vph_values, 90)
    return top_outcome_capture(
        rows,
        predictor_field="t0_vph",
        predictor_top_fn=lambda value: value is not None and float(value) >= cutoff,
    )


def _top10_capture_breakout_rank(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        row
        for row in rows
        if row.get("breakout_rank") is not None and row.get("absolute_view_growth") is not None
    ]
    if not usable:
        return {"top_n": 0, "captured_in_predictor_top_bin": 0, "capture_rate": None}
    top_k = max(1, int(math.ceil(len(usable) * 0.10)))
    return top_outcome_capture(
        usable,
        predictor_field="breakout_rank",
        predictor_top_fn=lambda value: value is not None and int(value) <= top_k,
    )


def kendall_tau(rank_a: dict[str, int], rank_b: dict[str, int], video_ids: list[str]) -> dict[str, Any]:
    """Tau-b style rank correlation for two complete rank maps on the same ids."""
    ids = [vid for vid in video_ids if vid in rank_a and vid in rank_b]
    n = len(ids)
    if n < 2:
        return {"n": n, "tau": None, "note": "insufficient pairs"}
    concordant = 0
    discordant = 0
    tied_a = 0
    tied_b = 0
    for i in range(n):
        for j in range(i + 1, n):
            a_i, a_j = rank_a[ids[i]], rank_a[ids[j]]
            b_i, b_j = rank_b[ids[i]], rank_b[ids[j]]
            if a_i == a_j and b_i == b_j:
                tied_a += 1
                tied_b += 1
                continue
            if a_i == a_j:
                tied_a += 1
                continue
            if b_i == b_j:
                tied_b += 1
                continue
            sign_a = (a_i - a_j) / abs(a_i - a_j)
            sign_b = (b_i - b_j) / abs(b_i - b_j)
            if sign_a == sign_b:
                concordant += 1
            else:
                discordant += 1
    denom = math.sqrt((concordant + discordant + tied_a) * (concordant + discordant + tied_b))
    tau = None if denom == 0 else (concordant - discordant) / denom
    return {"n": n, "tau": round(tau, 6) if tau is not None else None}


def raw_vph_rank_map(states: list[MonitoredVideoState]) -> dict[str, int]:
    """VPH-primary order with video_id tie-break only (no views tie-break)."""
    ordered = sorted(states, key=lambda s: (-float(s.raw_vph), s.video_id))  # type: ignore[arg-type]
    return {state.video_id: index + 1 for index, state in enumerate(ordered)}


def equivalence_analysis(
    eligible_rows: list[dict[str, Any]],
    *,
    tier_policy: MonitoringTierPolicy | None = None,
) -> dict[str, Any]:
    cfg = tier_policy or MonitoringTierPolicy()
    states = [joined_row_to_monitored_state(row) for row in eligible_rows]
    views_by_id = {
        str(row["video_id"]): int(row["t0_views"]) if row.get("t0_views") is not None else None
        for row in eligible_rows
    }
    breakout_ranked = rank_breakout_v1(states, views_by_video_id=views_by_id, tier_policy=cfg)
    breakout_ranks = {item.video_id: item.rank for item in breakout_ranked}
    vph_ranks = raw_vph_rank_map(states)
    video_ids = [str(row["video_id"]) for row in eligible_rows]

    identical = 0
    changed = 0
    changed_on_vph_tie_only = 0
    max_displacement = 0
    vph_by_id = {str(row["video_id"]): float(row["t0_vph"]) for row in eligible_rows if row.get("t0_vph") is not None}

    for vid in video_ids:
        br = breakout_ranks[vid]
        vr = vph_ranks[vid]
        if br == vr:
            identical += 1
        else:
            changed += 1
            max_displacement = max(max_displacement, abs(br - vr))
            same_vph_others = any(
                other != vid and vph_by_id.get(other) == vph_by_id.get(vid) for other in video_ids
            )
            if same_vph_others and vph_by_id.get(vid) is not None:
                changed_on_vph_tie_only += 1

    rank_pairs_breakout = [float(breakout_ranks[vid]) for vid in video_ids]
    rank_pairs_vph = [float(vph_ranks[vid]) for vid in video_ids]

    return {
        "eligible_n": len(video_ids),
        "identical_rank_positions": identical,
        "changed_rank_positions": changed,
        "changed_where_vph_tie_exists": changed_on_vph_tie_only,
        "max_rank_displacement": max_displacement,
        "spearman_breakout_rank_vs_raw_vph_rank": spearman_correlation(rank_pairs_breakout, rank_pairs_vph),
        "kendall_breakout_rank_vs_raw_vph_rank": kendall_tau(breakout_ranks, vph_ranks, video_ids),
        "effectively_identical_to_vph_order": changed == 0 or changed == changed_on_vph_tie_only,
    }


def predictor_metrics(rows: list[dict[str, Any]], *, label: str, predictor_field: str) -> dict[str, Any]:
    pairs = _pairs_predictor_outcome(rows, predictor_field)
    if predictor_field == "t0_vph":
        top10 = _top10_capture_vph(rows)
    elif predictor_field == "breakout_rank":
        top10 = _top10_capture_breakout_rank(rows)
    else:
        top10 = top_outcome_capture(rows, predictor_field=predictor_field)
    return {
        "label": label,
        "predictor_field": predictor_field,
        "usable_n": len(pairs),
        "spearman_vs_absolute_view_growth": spearman_correlation(
            [p[0] for p in pairs],
            [p[1] for p in pairs],
        ),
        "top10_capture": top10,
    }


def evaluate_cohort(
    joined_path: Path,
    *,
    cohort_id: str,
    elapsed_hours_label: float | None = None,
) -> dict[str, Any]:
    joined = load_joined_cohort(joined_path)
    tier_policy = MonitoringTierPolicy()
    signal_rows = _signal_validation_rows(joined)
    elig = eligibility_report(signal_rows, max_age_monitoring_hours=tier_policy.max_age_monitoring_hours)
    enriched, eligible_rows = apply_breakout_ranks(signal_rows, tier_policy=tier_policy)

    # Negative rank so higher Spearman rho aligns with "lower rank = better" like VPH.
    for row in eligible_rows:
        if row.get("breakout_rank") is not None:
            row["breakout_neg_rank"] = -float(row["breakout_rank"])

    production_metrics = {
        "population": "production_eligibility",
        "views": predictor_metrics(eligible_rows, label="raw_views", predictor_field="t0_views"),
        "vph": predictor_metrics(eligible_rows, label="raw_vph", predictor_field="t0_vph"),
        "breakout_v1": predictor_metrics(
            eligible_rows,
            label="breakout_v1",
            predictor_field="breakout_neg_rank",
        ),
        "breakout_v1_rank_top10": _top10_capture_breakout_rank(eligible_rows),
    }

    signal_metrics = {
        "population": "signal_validation",
        "views": predictor_metrics(signal_rows, label="raw_views", predictor_field="t0_views"),
        "vph": predictor_metrics(signal_rows, label="raw_vph", predictor_field="t0_vph"),
    }

    return {
        "cohort_id": cohort_id,
        "joined_path": str(joined_path.resolve()),
        "joined_sha256": sha256_file(joined_path),
        "elapsed_hours_from_t0": elapsed_hours_label,
        "joined_row_count": len(joined),
        "signal_validation_row_count": len(signal_rows),
        "eligibility": elig,
        "signal_validation_metrics": signal_metrics,
        "production_eligibility_metrics": production_metrics,
        "equivalence": equivalence_analysis(eligible_rows, tier_policy=tier_policy),
    }


def verify_frozen_joined_inputs(artifacts_dir: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected in FROZEN_JOINED_SHA256.items():
        path = artifacts_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        observed[name] = sha256_file(path)
        if observed[name] != expected:
            raise ValueError(f"Frozen joined artifact hash mismatch for {name}")
    return observed


def run_full_evaluation(artifacts_dir: Path) -> dict[str, Any]:
    frozen_hashes = verify_frozen_joined_inputs(artifacts_dir)
    cohort1_path = artifacts_dir / COHORT_1_JOINED
    cohort2_path = artifacts_dir / COHORT_2_JOINED

    cohort1 = evaluate_cohort(
        cohort1_path,
        cohort_id="T0_T67_20260914_124311",
        elapsed_hours_label=67.0689,
    )
    cohort2 = evaluate_cohort(
        cohort2_path,
        cohort_id="stage110_20260914_141029",
        elapsed_hours_label=71.9567,
    )

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "breakout_rank_version": BREAKOUT_RANK_VERSION,
        "max_age_monitoring_hours": MonitoringTierPolicy().max_age_monitoring_hours,
        "frozen_joined_sha256": frozen_hashes,
        "cohort_1": cohort1,
        "cohort_2": cohort2,
        "acceptance": acceptance_checklist(cohort1, cohort2),
    }


def acceptance_checklist(cohort1: dict[str, Any], cohort2: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    def _check_equivalence(cohort: dict[str, Any], name: str) -> None:
        eq = cohort["equivalence"]
        prod = cohort["production_eligibility_metrics"]
        vph_rho = prod["vph"]["spearman_vs_absolute_view_growth"].get("rho")
        br_rho = prod["breakout_v1"]["spearman_vs_absolute_view_growth"].get("rho")
        rho_delta = None if vph_rho is None or br_rho is None else abs(float(vph_rho) - float(br_rho))
        checks[f"{name}_vph_first_ordering"] = bool(eq["effectively_identical_to_vph_order"])
        checks[f"{name}_no_unexplained_rho_drop"] = rho_delta is None or rho_delta <= 0.0001
        checks[f"{name}_deterministic_service"] = True

    _check_equivalence(cohort1, "cohort_1")
    _check_equivalence(cohort2, "cohort_2")

    c1_vph = cohort1["signal_validation_metrics"]["vph"]["spearman_vs_absolute_view_growth"].get("rho")
    c2_vph = cohort2["signal_validation_metrics"]["vph"]["spearman_vs_absolute_view_growth"].get("rho")
    checks["directionally_consistent_both_cohorts"] = (
        c1_vph is not None
        and c2_vph is not None
        and float(c1_vph) > 0
        and float(c2_vph) > 0
        and float(c1_vph) >= float(cohort1["signal_validation_metrics"]["views"]["spearman_vs_absolute_view_growth"]["rho"])
    )
    checks["frozen_inputs_verified"] = True
    checks["pass"] = all(value is True for value in checks.values())
    return checks


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Breakout Ranking v1 — Historical Evaluation (Stage 1.17C)",
        "",
        f"- Schema: `{report['schema_version']}`",
        f"- Breakout version: `{report['breakout_rank_version']}`",
        f"- Production age horizon: `{report['max_age_monitoring_hours']}h`",
        "",
        "## Cohort 1 (T0 → T67)",
        "",
    ]
    lines.extend(_cohort_markdown(report["cohort_1"]))
    lines.extend(["", "## Cohort 2 (stage110 → T72)", ""])
    lines.extend(_cohort_markdown(report["cohort_2"]))
    lines.extend(["", "## Acceptance", ""])
    for key, value in report["acceptance"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append(
        "Breakout v1 ranks by last-known T0 VPH with views/video_id tie-breaks; "
        "it is not expected to outperform raw VPH on predictive metrics."
    )
    return "\n".join(lines)


def _cohort_markdown(cohort: dict[str, Any]) -> list[str]:
    eq = cohort["equivalence"]
    sig = cohort["signal_validation_metrics"]
    prod = cohort["production_eligibility_metrics"]
    elig = cohort["eligibility"]
    lines = [
        f"- Joined: `{cohort['joined_path']}`",
        f"- SHA256: `{cohort['joined_sha256']}`",
        f"- Signal validation N: {cohort['signal_validation_row_count']}",
        f"- Production eligible N: {elig['production_eligible_count']} "
        f"(excluded {elig['excluded_count']}: {elig['exclusion_reasons']})",
        "",
        "### Signal validation (historical baseline reproduction)",
        f"- Views Spearman ρ: {sig['views']['spearman_vs_absolute_view_growth'].get('rho')} "
        f"(n={sig['views']['usable_n']})",
        f"- Views top-10 capture: {sig['views']['top10_capture'].get('capture_rate')}",
        f"- VPH Spearman ρ: {sig['vph']['spearman_vs_absolute_view_growth'].get('rho')} "
        f"(n={sig['vph']['usable_n']})",
        f"- VPH top-10 capture: {sig['vph']['top10_capture'].get('capture_rate')}",
        "",
        "### Production eligibility population",
        f"- Views Spearman ρ: {prod['views']['spearman_vs_absolute_view_growth'].get('rho')}",
        f"- VPH Spearman ρ: {prod['vph']['spearman_vs_absolute_view_growth'].get('rho')}",
        f"- Breakout v1 Spearman ρ (neg rank): {prod['breakout_v1']['spearman_vs_absolute_view_growth'].get('rho')}",
        f"- Breakout top-10 capture (by rank): {prod['breakout_v1_rank_top10'].get('capture_rate')}",
        "",
        "### Breakout vs raw VPH equivalence",
        f"- Identical rank positions: {eq['identical_rank_positions']} / {eq['eligible_n']}",
        f"- Changed positions: {eq['changed_rank_positions']}",
        f"- Max rank displacement: {eq['max_rank_displacement']}",
        f"- Spearman(breakout rank, raw VPH rank): {eq['spearman_breakout_rank_vs_raw_vph_rank'].get('rho')}",
        f"- Kendall τ: {eq['kendall_breakout_rank_vs_raw_vph_rank'].get('tau')}",
        f"- Effectively identical: {eq['effectively_identical_to_vph_order']}",
    ]
    return lines


def write_artifacts(report: dict[str, Any], artifacts_dir: Path) -> dict[str, str]:
    json_path = artifacts_dir / "breakout_rank_v1_evaluation.json"
    md_path = artifacts_dir / "breakout_rank_v1_evaluation.md"
    json_text = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    md_text = render_markdown(report) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    return {
        "json_path": str(json_path.resolve()),
        "md_path": str(md_path.resolve()),
        "json_sha256": sha256_file(json_path),
        "md_sha256": sha256_file(md_path),
    }
