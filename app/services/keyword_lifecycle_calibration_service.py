"""Keyword lifecycle calibration dataset + observation report (Stage 1.20E)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordDiscoveryHit, KeywordScanRun, TargetKeyword
from app.services.keyword_evidence_service import list_keyword_evidence
from app.services.keyword_evidence_types import KeywordEvidence
from app.services.keyword_lifecycle_calibration_types import (
    KeywordCalibrationRow,
    KeywordLifecycleCalibrationReport,
    RuleReadinessItem,
    ScanCalibrationRow,
    SpearmanAssociation,
)
from app.services.keyword_lifecycle_recommendation_service import evaluate_lifecycle_recommendation
from app.services.keyword_performance_evaluation import (
    AttributionMode,
    compute_horizon_coverage_diagnostics,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.radar_candidate_analysis import _percentile
from app.services.radar_outcome_analysis import spearman_correlation

MIN_SPEARMAN_PAIRS = 10
MATURITY_BUCKETS = (
    ("lt_3", lambda n: n < 3),
    ("3_5", lambda n: 3 <= n <= 5),
    ("6_10", lambda n: 6 <= n <= 10),
    ("gt_10", lambda n: n > 10),
)


def maturity_group_for(successful_scan_count: int) -> str:
    for label, pred in MATURITY_BUCKETS:
        if pred(successful_scan_count):
            return label
    return "lt_3"


def _load_new_to_db_by_scan(
    session: Session,
    keyword_ids: list[int],
) -> dict[tuple[int, str], int]:
    if not keyword_ids:
        return {}
    rows = session.execute(
        select(
            KeywordDiscoveryHit.keyword_id,
            KeywordDiscoveryHit.discovery_run_id,
            func.count(),
        )
        .where(
            KeywordDiscoveryHit.keyword_id.in_(keyword_ids),
            KeywordDiscoveryHit.video_existed_before_discovery.is_(False),
        )
        .group_by(KeywordDiscoveryHit.keyword_id, KeywordDiscoveryHit.discovery_run_id),
    ).all()
    return {(int(kid), str(rid)): int(cnt or 0) for kid, rid, cnt in rows}


def _load_scan_runs(session: Session, keyword_ids: list[int]) -> list[KeywordScanRun]:
    if not keyword_ids:
        return []
    return list(
        session.scalars(
            select(KeywordScanRun)
            .where(KeywordScanRun.keyword_id.in_(keyword_ids))
            .order_by(KeywordScanRun.keyword_id.asc(), KeywordScanRun.finished_at.asc()),
        ).all(),
    )


def _streak_stats(zero_flags: list[bool]) -> tuple[int, int]:
    """Return (max_consecutive_zeros, trailing_consecutive_zeros) for successful scans only."""
    max_run = 0
    current = 0
    for flag in zero_flags:
        if flag:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    trailing = 0
    for flag in reversed(zero_flags):
        if flag:
            trailing += 1
        else:
            break
    return max_run, trailing


def build_scan_calibration_rows(
    session: Session,
    keyword_ids: list[int],
) -> list[ScanCalibrationRow]:
    new_map = _load_new_to_db_by_scan(session, keyword_ids)
    rows: list[ScanCalibrationRow] = []
    for run in _load_scan_runs(session, keyword_ids):
        new_count = new_map.get((run.keyword_id, run.discovery_run_id), 0)
        ok = run.status == "ok"
        zero_new = ok and new_count == 0
        rows.append(
            ScanCalibrationRow(
                scan_run_id=run.id,
                keyword_id=run.keyword_id,
                discovery_run_id=run.discovery_run_id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                raw_candidates=run.raw_candidates,
                unique_candidates=run.unique_candidates,
                persisted_videos=run.persisted_videos,
                new_to_database_video_count=new_count,
                zero_raw_result=ok and run.raw_candidates == 0,
                zero_persisted_result=ok and run.persisted_videos == 0,
                zero_new_video_yield=zero_new,
                scan_failed=run.status != "ok",
            ),
        )
    return rows


def _scan_span_hours(first_at: datetime | None, latest_at: datetime | None) -> float | None:
    if first_at is None or latest_at is None:
        return None
    return round((ensure_utc(latest_at) - ensure_utc(first_at)).total_seconds() / 3600.0, 3)


def _ratio(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 4)


def _max_vph(evidence: KeywordEvidence) -> float | None:
    if evidence.discovery_vph.observation_count <= 0:
        return None
    return evidence.discovery_vph.p90_discovery_vph


def build_keyword_calibration_row(
    keyword: TargetKeyword,
    evidence: KeywordEvidence,
    scan_rows: list[ScanCalibrationRow],
) -> KeywordCalibrationRow:
    rec = evaluate_lifecycle_recommendation(evidence)
    successful_scans = [r for r in scan_rows if r.keyword_id == keyword.id and not r.scan_failed]
    zero_flags = [r.zero_new_video_yield for r in successful_scans]
    zero_count = sum(1 for f in zero_flags if f)
    max_streak, tail_streak = _streak_stats(zero_flags)
    first_scan = min((r.started_at for r in scan_rows if r.keyword_id == keyword.id), default=None)
    latest_scan = max((r.finished_at for r in scan_rows if r.keyword_id == keyword.id), default=None)
    ok_n = len(successful_scans)

    return KeywordCalibrationRow(
        keyword_id=keyword.id,
        keyword=keyword.keyword,
        lifecycle_status=keyword.lifecycle_status,
        source_type=keyword.source_type,
        parent_keyword_id=keyword.parent_keyword_id,
        created_at=getattr(keyword, "created_at", None),
        status_changed_at=keyword.status_changed_at,
        total_scan_count=evidence.scan.total_scan_count,
        successful_scan_count=evidence.scan.successful_scan_count,
        failed_scan_count=evidence.scan.failed_scan_count,
        first_scan_at=first_scan,
        latest_scan_at=latest_scan or evidence.scan.latest_scan_at,
        scan_span_hours=_scan_span_hours(first_scan, latest_scan),
        total_raw_candidates=evidence.scan.total_raw_candidates,
        total_unique_candidates=evidence.scan.total_unique_candidates,
        total_persisted_videos=evidence.scan.total_persisted_videos,
        unique_discovered_video_count=evidence.discovery.unique_discovered_video_count,
        new_to_database_video_count=evidence.discovery.new_to_database_video_count,
        successful_zero_yield_scan_count=zero_count,
        zero_yield_rate=_ratio(zero_count, ok_n),
        consecutive_zero_yield_scans_at_end=tail_streak,
        max_consecutive_zero_yield_scans=max_streak,
        within_keyword_duplicate_count=evidence.redundancy.within_keyword_duplicate_count,
        cross_keyword_duplicate_count=evidence.redundancy.cross_keyword_duplicate_count,
        duplicate_rate=evidence.redundancy.duplicate_rate,
        unique_yield_rate=evidence.redundancy.unique_yield_rate,
        new_video_rate=evidence.discovery.new_video_rate,
        discovery_vph_observation_count=evidence.discovery_vph.observation_count,
        median_discovery_vph=evidence.discovery_vph.median_discovery_vph,
        p90_discovery_vph=evidence.discovery_vph.p90_discovery_vph,
        max_discovery_vph=_max_vph(evidence),
        breakout_eligible_count=evidence.breakout.breakout_eligible_count,
        top_decile_breakout_count=evidence.breakout.top_decile_breakout_count,
        top_decile_breakout_rate=evidence.breakout.top_decile_breakout_rate,
        attributed_observation_count=evidence.delayed_outcome.attributed_observation_count,
        matured_72h_count=evidence.delayed_outcome.matured_72h_count,
        valid_72h_outcome_count=evidence.delayed_outcome.valid_72h_outcome_count,
        missing_72h_outcome_count=evidence.delayed_outcome.missing_72h_outcome_count,
        median_absolute_view_growth_72h=evidence.delayed_outcome.median_72h_growth,
        p90_absolute_view_growth_72h=evidence.delayed_outcome.p90_72h_growth,
        recommendation=rec.recommendation,
        recommendation_confidence=rec.confidence,
        recommendation_reason_code=rec.reason_code,
        calibration_required=rec.calibration_required,
        maturity_group=maturity_group_for(evidence.scan.successful_scan_count),
    )


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "note": "INSUFFICIENT_SAMPLE"}
    sorted_v = sorted(values)
    return {
        "n": len(sorted_v),
        "p25": _percentile(sorted_v, 25),
        "p50": _percentile(sorted_v, 50),
        "p75": _percentile(sorted_v, 75),
        "p90": _percentile(sorted_v, 90),
    }


def _pairwise_spearman(rows: list[KeywordCalibrationRow], x_attr: str, y_attr: str, label: str) -> SpearmanAssociation:
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        x = getattr(row, x_attr)
        y = getattr(row, y_attr)
        if x is None or y is None:
            continue
        xs.append(float(x))
        ys.append(float(y))
    if len(xs) < MIN_SPEARMAN_PAIRS:
        return SpearmanAssociation(pair_label=label, n=len(xs), rho=None, note="insufficient pairs")
    result = spearman_correlation(xs, ys)
    return SpearmanAssociation(
        pair_label=label,
        n=int(result.get("n") or len(xs)),
        rho=result.get("rho"),
        note=result.get("note"),
    )


def _readiness_report(rows: list[KeywordCalibrationRow]) -> list[RuleReadinessItem]:
    probation = [r for r in rows if r.lifecycle_status == "probation"]
    with_min_scans = [r for r in probation if r.successful_scan_count >= 3]
    valid_72h_kw = sum(1 for r in rows if r.valid_72h_outcome_count >= 1)
    valid_72h_3 = sum(1 for r in rows if r.valid_72h_outcome_count >= 3)
    matured_total = sum(r.matured_72h_count for r in rows)
    valid_total = sum(r.valid_72h_outcome_count for r in rows)

    items = [
        RuleReadinessItem(
            rule_id="probation_promotion_threshold",
            readiness="NOT_READY",
            required_evidence="≥3 ok scans + calibrated sustained-yield rule (Stage 1.20A)",
            current_sample_size=len(with_min_scans),
            missing_evidence="Calibrated sustained-yield threshold not defined",
            recommendation="Observe preliminary_review counts; enable _CALIBRATED_PROMOTE after 1.20E review",
        ),
        RuleReadinessItem(
            rule_id="probation_zero_yield_weak_threshold",
            readiness="NOT_READY",
            required_evidence="≥3 ok scans + N consecutive zero-new-yield scans (CALIBRATION_REQUIRED)",
            current_sample_size=len(with_min_scans),
            missing_evidence="N consecutive zero-yield scans not calibrated",
            recommendation="Use scan-level streak distribution in this report",
        ),
        RuleReadinessItem(
            rule_id="active_demotion_threshold",
            readiness="NOT_READY",
            required_evidence="Rolling yield baseline vs M scans (CALIBRATION_REQUIRED)",
            current_sample_size=len([r for r in rows if r.lifecycle_status == "active"]),
            missing_evidence="M-scan baseline bands not calibrated",
            recommendation="CALIBRATION_NOT_READY",
        ),
        RuleReadinessItem(
            rule_id="archive_threshold",
            readiness="NOT_READY",
            required_evidence="Long-run zero yield + operator policy",
            current_sample_size=len(rows),
            missing_evidence="Archive policy not calibrated",
            recommendation="Manual archive only",
        ),
        RuleReadinessItem(
            rule_id="72h_outcome_threshold",
            readiness="PARTIALLY_READY" if valid_total >= 10 else "NOT_READY",
            required_evidence="Sufficient valid 72h outcomes at keyword level",
            current_sample_size=valid_total,
            missing_evidence=f"matured={matured_total}, keywords_with_valid={valid_72h_kw}, keywords_with_3plus={valid_72h_3}",
            recommendation="CALIBRATION_NOT_READY" if valid_total < 30 else "Review associations only",
        ),
    ]
    return items


def _case_review(rows: list[KeywordCalibrationRow]) -> dict[str, list[dict[str, Any]]]:
    def top(
        key: str,
        n: int = 3,
        reverse: bool = True,
        *,
        min_value: float | None = None,
    ) -> list[dict[str, Any]]:
        filtered = [r for r in rows if getattr(r, key) is not None]
        if min_value is not None:
            filtered = [r for r in filtered if float(getattr(r, key)) > min_value]
        filtered.sort(key=lambda r: getattr(r, key), reverse=reverse)
        out = []
        for r in filtered[:n]:
            out.append({"keyword_id": r.keyword_id, "keyword": r.keyword, key: getattr(r, key)})
        return out

    return {
        "high_yield": top("new_to_database_video_count"),
        "low_yield": top("new_to_database_video_count", reverse=False),
        "high_zero_yield_streak": top("max_consecutive_zero_yield_scans"),
        "high_redundancy": top("duplicate_rate"),
        "high_discovery_vph": top("median_discovery_vph"),
        "low_vph_high_yield": [
            {
                "keyword_id": r.keyword_id,
                "keyword": r.keyword,
                "median_discovery_vph": r.median_discovery_vph,
                "new_to_database_video_count": r.new_to_database_video_count,
            }
            for r in sorted(
                [x for x in rows if x.median_discovery_vph is not None and x.new_to_database_video_count > 0],
                key=lambda x: (x.median_discovery_vph or 0, -x.new_to_database_video_count),
            )[:3]
        ],
        "valid_72h_outcomes": top("valid_72h_outcome_count", min_value=0),
    }


def build_calibration_report(
    session: Session,
    *,
    lifecycle_status: str | None = None,
    attribution_mode: AttributionMode = "all_hits",
    include_breakout: bool = True,
    include_delayed: bool = True,
    limit: int = 5000,
    now: datetime | None = None,
) -> KeywordLifecycleCalibrationReport:
    reference = now or utc_now()
    stmt = select(TargetKeyword).order_by(TargetKeyword.id.asc())
    if lifecycle_status:
        stmt = stmt.where(TargetKeyword.lifecycle_status == lifecycle_status)
    stmt = stmt.limit(max(1, min(limit, 5000)))
    keywords = list(session.scalars(stmt).all())
    keyword_ids = [k.id for k in keywords]

    scan_rows = build_scan_calibration_rows(session, keyword_ids)
    evidence_result = list_keyword_evidence(
        session,
        lifecycle_status=lifecycle_status,
        attribution_mode=attribution_mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        limit=limit,
    )
    evidence_by_id = {ev.keyword_id: ev for ev in evidence_result.items}

    keyword_rows: list[KeywordCalibrationRow] = []
    for kw in keywords:
        ev = evidence_by_id.get(kw.id)
        if ev is None:
            continue
        keyword_rows.append(build_keyword_calibration_row(kw, ev, scan_rows))

    maturity_counts: dict[str, int] = defaultdict(int)
    for row in keyword_rows:
        maturity_counts[row.maturity_group] += 1

    rec_counts: dict[str, int] = defaultdict(int)
    rec_by_lc: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in keyword_rows:
        rec_counts[row.recommendation] += 1
        rec_by_lc[row.lifecycle_status][row.recommendation] += 1

    zero_by_mat: dict[str, Any] = {}
    for label, _ in MATURITY_BUCKETS:
        subset = [r for r in keyword_rows if r.maturity_group == label]
        rates = [r.zero_yield_rate for r in subset if r.zero_yield_rate is not None]
        tails = [float(r.consecutive_zero_yield_scans_at_end) for r in subset]
        maxs = [float(r.max_consecutive_zero_yield_scans) for r in subset]
        zero_by_mat[label] = {
            "keyword_count": len(subset),
            "zero_yield_rate": _distribution(rates),
            "consecutive_zero_tail": _distribution(tails),
            "max_zero_streak": _distribution(maxs),
        }

    per_ok_scan_new: list[float] = []
    for row in keyword_rows:
        if row.successful_scan_count > 0:
            per_ok_scan_new.append(row.new_to_database_video_count / row.successful_scan_count)

    yield_dist = {
        "new_videos_per_successful_scan": _distribution(per_ok_scan_new),
        "total_new_to_database": _distribution([float(r.new_to_database_video_count) for r in keyword_rows]),
        "total_persisted": _distribution([float(r.total_persisted_videos) for r in keyword_rows]),
    }

    vph_rows = [r for r in keyword_rows if r.discovery_vph_observation_count > 0]
    vph_analysis = {
        "keywords_with_vph_observations": len(vph_rows),
        "median_discovery_vph": _distribution(
            [r.median_discovery_vph for r in vph_rows if r.median_discovery_vph is not None],
        ),
        "note": "Association only — not causal; keyword-level VPH may differ from video-level signal",
    }

    breakout_rows = [r for r in keyword_rows if r.breakout_eligible_count > 0]
    breakout_analysis = {
        "keywords_with_breakout_eligible_observations": len(breakout_rows),
        "eligible_count_distribution": _distribution([float(r.breakout_eligible_count) for r in breakout_rows]),
        "top_decile_rate_distribution": _distribution(
            [r.top_decile_breakout_rate for r in breakout_rows if r.top_decile_breakout_rate is not None],
        ),
    }

    attributed = sum(r.attributed_observation_count for r in keyword_rows)
    matured = sum(r.matured_72h_count for r in keyword_rows)
    valid = sum(r.valid_72h_outcome_count for r in keyword_rows)
    missing = sum(r.missing_72h_outcome_count for r in keyword_rows)
    pending = max(0, attributed - matured)
    diagnostics_block: dict[str, Any] | None = None
    if include_delayed:
        diag = compute_horizon_coverage_diagnostics(
            session,
            attribution_mode=attribution_mode,
            now=reference,
            keyword_ids=keyword_ids,
        )
        diagnostics_block = diag.to_dict()
        pending = diag.pending_72h_count
    outcome_72h = {
        "attributed_observation_count": attributed,
        "pending_72h_count": pending if include_delayed else None,
        "matured_72h_count": matured,
        "valid_72h_outcome_count": valid,
        "missing_72h_outcome_count": missing,
        "coverage_rate": _ratio(valid, matured) if matured > 0 else None,
        "matured_equals_valid_plus_missing": (matured == valid + missing),
        "keywords_with_valid_1plus": sum(1 for r in keyword_rows if r.valid_72h_outcome_count >= 1),
        "keywords_with_valid_3plus": sum(1 for r in keyword_rows if r.valid_72h_outcome_count >= 3),
        "keywords_with_valid_5plus": sum(1 for r in keyword_rows if r.valid_72h_outcome_count >= 5),
        "calibration_status": "CALIBRATION_NOT_READY" if valid < 30 else "INSUFFICIENT_SAMPLE_FOR_RULES",
    }
    if diagnostics_block is not None:
        outcome_72h["72h_diagnostics"] = diagnostics_block

    associations = [
        _pairwise_spearman(keyword_rows, "successful_scan_count", "new_to_database_video_count", "scans_vs_new_videos"),
        _pairwise_spearman(keyword_rows, "zero_yield_rate", "new_video_rate", "zero_yield_vs_new_video_rate"),
        _pairwise_spearman(keyword_rows, "median_discovery_vph", "top_decile_breakout_rate", "median_vph_vs_breakout_rate"),
        _pairwise_spearman(keyword_rows, "p90_discovery_vph", "top_decile_breakout_rate", "p90_vph_vs_breakout_rate"),
        _pairwise_spearman(keyword_rows, "new_video_rate", "median_absolute_view_growth_72h", "new_video_rate_vs_72h_growth"),
        _pairwise_spearman(keyword_rows, "zero_yield_rate", "median_absolute_view_growth_72h", "zero_yield_vs_72h_growth"),
    ]

    strong = {"promote_active", "move_weak", "archive_candidate", "restore_active"}
    strong_count = sum(rec_counts.get(k, 0) for k in strong)

    findings = [
        f"Pool keywords in report: {len(keyword_rows)}",
        f"Recommendation distribution: {dict(rec_counts)}",
        f"Strong lifecycle actions emitted: {strong_count} (expected ~0 while _CALIBRATED_* disabled)",
        f"72h valid outcomes total: {valid} ({outcome_72h['calibration_status']})",
    ]

    return KeywordLifecycleCalibrationReport(
        generated_at=reference,
        attribution_mode=attribution_mode,
        include_breakout=include_breakout,
        include_delayed=include_delayed,
        keyword_count=len(keyword_rows),
        scan_row_count=len(scan_rows),
        maturity_group_counts=dict(maturity_counts),
        recommendation_counts=dict(rec_counts),
        recommendation_by_lifecycle={k: dict(v) for k, v in rec_by_lc.items()},
        zero_yield_by_maturity=zero_by_mat,
        yield_distribution=yield_dist,
        vph_analysis=vph_analysis,
        breakout_analysis=breakout_analysis,
        outcome_72h_coverage=outcome_72h,
        associations=associations,
        readiness=_readiness_report(keyword_rows),
        case_review=_case_review(keyword_rows),
        production_findings=findings,
        keyword_rows=keyword_rows,
        scan_rows=scan_rows,
    )


def report_to_summary_dict(report: KeywordLifecycleCalibrationReport) -> dict[str, Any]:
    """JSON-serializable summary without full datasets."""
    return {
        "generated_at": report.generated_at.isoformat(),
        "attribution_mode": report.attribution_mode,
        "include_breakout": report.include_breakout,
        "include_delayed": report.include_delayed,
        "keyword_count": report.keyword_count,
        "scan_row_count": report.scan_row_count,
        "maturity_group_counts": report.maturity_group_counts,
        "recommendation_counts": report.recommendation_counts,
        "recommendation_by_lifecycle": report.recommendation_by_lifecycle,
        "zero_yield_by_maturity": report.zero_yield_by_maturity,
        "yield_distribution": report.yield_distribution,
        "vph_analysis": report.vph_analysis,
        "breakout_analysis": report.breakout_analysis,
        "outcome_72h_coverage": report.outcome_72h_coverage,
        "associations": [asdict(a) for a in report.associations],
        "readiness": [asdict(r) for r in report.readiness],
        "case_review": report.case_review,
        "production_findings": report.production_findings,
    }
