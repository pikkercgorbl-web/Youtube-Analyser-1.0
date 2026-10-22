"""Historical outcome follow-up for Daily Intelligence winners (Stage 1.23C.1B.1)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import (
    DailyIntelligenceReport,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunWinnerAppearance,
    VideoSnapshot,
)
from app.services.keyword_performance_evaluation import (
    HORIZON_HOURS,
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    KeywordVideoBaseline,
    match_horizon_outcome,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.video_snapshot_storage import get_latest_snapshots_for_videos, get_snapshots_for_videos

AttentionViewsSource = Literal[
    "verified_snapshot",
    "frozen_payload_unknown_source",
    "fallback_unknown",
]

MetricsInterpretation = Literal[
    "no_outcome_measurement",
    "descriptive_frozen_vs_horizon_outcome",
    "verified_post_signal_growth_unavailable",
    "pre_signal_outcome_only",
    "insufficient_attention_baseline",
]

CoverageCategory = Literal[
    "NOT_MATURED",
    "MEASURED_POST_SIGNAL",
    "MEASURED_PRE_SIGNAL",
    "MATURED_MISSING",
    "INVALID_TIMELINE",
    "INSUFFICIENT_EVIDENCE",
]

OutcomeWindowPhase = Literal[
    "not_yet_open",
    "open_awaiting_measurement",
    "closed",
    "not_applicable",
]


def _snapshots_by_video(rows: list[VideoSnapshot]) -> dict[str, list[VideoSnapshot]]:
    grouped: dict[str, list[VideoSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[row.video_id].append(row)
    return grouped


def _json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return ensure_utc(dt)


def _outcome_window_bounds(discovered_at: datetime) -> tuple[datetime, datetime, datetime]:
    discovery = ensure_utc(discovered_at)
    target = discovery + timedelta(hours=HORIZON_HOURS)
    tol = timedelta(hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS)
    return target - tol, target, target + tol


def _classify_coverage(
    *,
    provenance: dict[str, Any],
    edition_signal: datetime | None,
    first_signal: datetime | None,
    outcome: Any | None,
    reference_now: datetime,
) -> tuple[CoverageCategory, OutcomeWindowPhase, str | None]:
    if provenance.get("available") is not True:
        return "INSUFFICIENT_EVIDENCE", "not_applicable", provenance.get("reason") or "provenance_unavailable"

    discovered_at = _parse_dt(provenance.get("discovered_at"))
    if discovered_at is None:
        return "INSUFFICIENT_EVIDENCE", "not_applicable", "invalid_discovered_at"

    if provenance.get("views_at_discovery") is None:
        return "INSUFFICIENT_EVIDENCE", "not_applicable", "no_views_at_discovery"

    if edition_signal is None:
        return "INSUFFICIENT_EVIDENCE", "not_applicable", "missing_edition_signal"

    if discovered_at > edition_signal:
        return "INVALID_TIMELINE", "not_applicable", "discovered_after_edition_signal"

    window_start, _target, window_end = _outcome_window_bounds(discovered_at)
    ref = ensure_utc(reference_now)

    if outcome is not None:
        captured = ensure_utc(outcome.snapshot_captured_at)
        if captured < discovered_at:
            return "INVALID_TIMELINE", "closed", "outcome_before_discovery"
        if captured >= edition_signal:
            return "MEASURED_POST_SIGNAL", "closed", None
        return "MEASURED_PRE_SIGNAL", "closed", None

    if ref < window_start:
        return "NOT_MATURED", "not_yet_open", None
    if ref <= window_end:
        return "NOT_MATURED", "open_awaiting_measurement", None
    return "MATURED_MISSING", "closed", None


def _frozen_views_from_payload(payload: dict[str, Any]) -> int | None:
    raw = payload.get("views")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _baseline_provenance_verified_from_payload(payload: dict[str, Any]) -> bool:
    """True only when frozen payload carries explicit snapshot provenance (future / rare)."""
    if payload.get("views_source_kind") != "video_snapshot":
        return False
    if payload.get("views_snapshot_id") in (None, ""):
        return False
    return _parse_dt(payload.get("views_measured_at")) is not None


def _resolve_attention_views_provenance(
    *,
    payload: dict[str, Any],
    edition_signal: datetime | None,
    edition_latest_snapshot: VideoSnapshot | None = None,
) -> dict[str, Any]:
    frozen_views = _frozen_views_from_payload(payload)
    verified = _baseline_provenance_verified_from_payload(payload)

    if frozen_views is None:
        return {
            "frozen_attention_views": None,
            "attention_views_source": "fallback_unknown",
            "candidate_baseline_snapshot_at": None,
            "baseline_provenance_verified": False,
        }

    if verified:
        source: AttentionViewsSource = "verified_snapshot"
        candidate_at = _parse_dt(payload.get("views_measured_at"))
        return {
            "frozen_attention_views": frozen_views,
            "attention_views_source": source,
            "candidate_baseline_snapshot_at": candidate_at.isoformat() if candidate_at else None,
            "baseline_provenance_verified": True,
        }

    candidate_at: datetime | None = None
    candidate_snap = edition_latest_snapshot
    if edition_signal is not None and candidate_snap is not None and candidate_snap.views is not None:
        if ensure_utc(candidate_snap.captured_at) <= ensure_utc(edition_signal):
            if int(candidate_snap.views) == frozen_views:
                candidate_at = ensure_utc(candidate_snap.captured_at)

    return {
        "frozen_attention_views": frozen_views,
        "attention_views_source": "frozen_payload_unknown_source",
        "candidate_baseline_snapshot_at": candidate_at.isoformat() if candidate_at else None,
        "baseline_provenance_verified": False,
    }


def _comparison_metrics(
    *,
    category: CoverageCategory,
    edition_signal: datetime | None,
    frozen_views_at_attention: int | None,
    outcome: Any | None,
    baseline_provenance_verified: bool,
) -> tuple[dict[str, Any], MetricsInterpretation]:
    base: dict[str, Any] = {
        "views_at_attention_frozen": frozen_views_at_attention,
        "views_at_outcome_horizon": None,
        "delta_views_descriptive": None,
        "descriptive_growth_ratio": None,
        "verified_post_signal_growth": None,
        "verified_post_signal_growth_ratio": None,
        "elapsed_hours_edition_signal_to_outcome": None,
        "metrics_reason": None,
    }
    if category not in ("MEASURED_POST_SIGNAL", "MEASURED_PRE_SIGNAL"):
        base["metrics_reason"] = "no_valid_outcome_measurement"
        return base, "no_outcome_measurement"
    if frozen_views_at_attention is None:
        base["metrics_reason"] = "missing_frozen_attention_views"
        return base, "insufficient_attention_baseline"
    if outcome is None or edition_signal is None:
        base["metrics_reason"] = "missing_outcome_or_signal"
        return base, "no_outcome_measurement"

    views_out = int(outcome.outcome_views)
    base["views_at_outcome_horizon"] = views_out

    if category == "MEASURED_PRE_SIGNAL":
        base["metrics_reason"] = "outcome_snapshot_before_edition_signal"
        return base, "pre_signal_outcome_only"

    views_att = int(frozen_views_at_attention)
    delta = views_out - views_att
    base["delta_views_descriptive"] = delta
    if views_att > 0:
        base["descriptive_growth_ratio"] = round(views_out / views_att, 6)
    else:
        base["metrics_reason"] = "non_positive_frozen_attention_baseline"

    elapsed = (ensure_utc(outcome.snapshot_captured_at) - ensure_utc(edition_signal)).total_seconds() / 3600.0
    base["elapsed_hours_edition_signal_to_outcome"] = round(elapsed, 4)

    if baseline_provenance_verified:
        base["verified_post_signal_growth"] = delta
        if views_att > 0:
            base["verified_post_signal_growth_ratio"] = round(views_out / views_att, 6)
        interpretation: MetricsInterpretation = "descriptive_frozen_vs_horizon_outcome"
    else:
        base["metrics_reason"] = (
            base.get("metrics_reason") or "baseline_measurement_time_not_verified"
        )
        interpretation = "verified_post_signal_growth_unavailable"

    return base, interpretation


def _build_followup_row(
    *,
    finding: DailyIntelligenceReportWinnerFinding,
    report: DailyIntelligenceReport,
    appearances: list[DailyIntelligenceRunWinnerAppearance],
    snapshots: list[VideoSnapshot],
    reference_now: datetime,
    edition_latest_snapshot: VideoSnapshot | None = None,
) -> dict[str, Any]:
    provenance = _json_loads(finding.discovery_provenance_json, {})
    payload = _json_loads(finding.payload_json, {})
    edition_signal = ensure_utc(report.source_computed_at) if report.source_computed_at else None
    appearance_times = sorted(ensure_utc(a.source_computed_at) for a in appearances)
    first_signal = appearance_times[0] if appearance_times else edition_signal

    baseline: KeywordVideoBaseline | None = None
    outcome = None
    if provenance.get("available") is True:
        discovered_at = _parse_dt(provenance.get("discovered_at"))
        if discovered_at is not None and provenance.get("views_at_discovery") is not None:
            baseline = KeywordVideoBaseline(
                keyword_id=int(provenance.get("keyword_id") or 0),
                video_id=finding.video_id,
                discovery_at=discovered_at,
                views_at_discovery=int(provenance["views_at_discovery"]),
                vph_at_discovery=provenance.get("vph_at_discovery"),
            )
            outcome = match_horizon_outcome(
                baseline,
                {finding.video_id: snapshots},
                tolerance_hours=HORIZON_SNAPSHOT_TOLERANCE_HOURS,
            )

    category, window_phase, category_reason = _classify_coverage(
        provenance=provenance,
        edition_signal=edition_signal,
        first_signal=first_signal,
        outcome=outcome,
        reference_now=reference_now,
    )

    attention_prov = _resolve_attention_views_provenance(
        payload=payload,
        edition_signal=edition_signal,
        edition_latest_snapshot=edition_latest_snapshot,
    )
    frozen_views = attention_prov["frozen_attention_views"]

    window_start, window_target, window_end = (
        _outcome_window_bounds(baseline.discovery_at)
        if baseline is not None
        else (None, None, None)
    )

    outcome_snap: VideoSnapshot | None = None
    if outcome is not None:
        for snap in snapshots:
            if snap.views is not None and ensure_utc(snap.captured_at) == ensure_utc(outcome.snapshot_captured_at):
                outcome_snap = snap
                break

    metrics, metrics_interpretation = _comparison_metrics(
        category=category,
        edition_signal=edition_signal,
        frozen_views_at_attention=frozen_views,
        outcome=outcome,
        baseline_provenance_verified=bool(attention_prov["baseline_provenance_verified"]),
    )

    return {
        "report_date": finding.report_date.isoformat(),
        "video_id": finding.video_id,
        "rank": finding.rank,
        "coverage_category": category,
        "coverage_reason": category_reason,
        "outcome_window_phase": window_phase,
        "signal_timestamps": {
            "first_signal_source_computed_at": first_signal.isoformat() if first_signal else None,
            "edition_signal_source_computed_at": edition_signal.isoformat() if edition_signal else None,
            "appearance_count_on_report_date": len(appearances),
            "appearance_source_computed_at": [t.isoformat() for t in appearance_times],
        },
        "discovery_outcome_anchor": {
            "discovered_at": provenance.get("discovered_at"),
            "views_at_discovery": provenance.get("views_at_discovery"),
            "outcome_window_start_at": window_start.isoformat() if window_start else None,
            "outcome_window_target_at": window_target.isoformat() if window_target else None,
            "outcome_window_end_at": window_end.isoformat() if window_end else None,
            "horizon_hours": HORIZON_HOURS,
            "tolerance_hours": HORIZON_SNAPSHOT_TOLERANCE_HOURS,
        },
        "outcome_measurement": {
            "snapshot_captured_at": outcome.snapshot_captured_at.isoformat() if outcome else None,
            "snapshot_source": outcome_snap.source if outcome_snap else None,
            "snapshot_run_id": outcome_snap.run_id if outcome_snap else None,
            "views_at_outcome_horizon": outcome.outcome_views if outcome else None,
            "absolute_view_growth_from_discovery": outcome.absolute_view_growth if outcome else None,
            "actual_elapsed_hours_from_discovery": outcome.actual_elapsed_hours if outcome else None,
        },
        "attention_views_provenance": attention_prov,
        "metrics_interpretation": metrics_interpretation,
        "comparison_metrics": metrics,
        "frozen_delayed_outcome": {
            "delayed_outcome_state": payload.get("delayed_outcome_state"),
            "delayed_outcome_growth": payload.get("delayed_outcome_growth"),
        },
        "reference_evaluated_at": ensure_utc(reference_now).isoformat(),
    }


def _load_report_context(
    session: Session,
    report_date: date,
) -> tuple[DailyIntelligenceReport | None, list[DailyIntelligenceReportWinnerFinding], dict[str, list[DailyIntelligenceRunWinnerAppearance]]]:
    report = session.get(DailyIntelligenceReport, report_date)
    findings = list(
        session.scalars(
            select(DailyIntelligenceReportWinnerFinding)
            .where(DailyIntelligenceReportWinnerFinding.report_date == report_date)
            .order_by(DailyIntelligenceReportWinnerFinding.rank.asc()),
        ).all(),
    )
    appearances = list(
        session.scalars(
            select(DailyIntelligenceRunWinnerAppearance).where(
                DailyIntelligenceRunWinnerAppearance.report_date == report_date,
            ),
        ).all(),
    )
    by_video: dict[str, list[DailyIntelligenceRunWinnerAppearance]] = defaultdict(list)
    for row in appearances:
        by_video[row.video_id].append(row)
    return report, findings, by_video


def get_report_outcome_coverage(
    session: Session,
    report_date: date,
    *,
    reference_now: datetime | None = None,
) -> dict[str, Any] | None:
    report, findings, appearances_by_video = _load_report_context(session, report_date)
    if report is None:
        return None
    ref = ensure_utc(reference_now or utc_now())
    if not findings:
        return {
            "report_date": report_date.isoformat(),
            "reference_evaluated_at": ref.isoformat(),
            "winner_count": 0,
            "coverage_counts": {},
            "coverage_by_category": {},
            "items": [],
        }

    video_ids = [f.video_id for f in findings]
    snapshots_by_video = _snapshots_by_video(get_snapshots_for_videos(session, video_ids))
    edition_signal = ensure_utc(report.source_computed_at) if report.source_computed_at else None
    latest_at_edition = (
        get_latest_snapshots_for_videos(session, video_ids, compute_before=edition_signal)
        if edition_signal is not None
        else {}
    )

    items: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for finding in findings:
        row = _build_followup_row(
            finding=finding,
            report=report,
            appearances=appearances_by_video.get(finding.video_id, []),
            snapshots=snapshots_by_video.get(finding.video_id, []),
            reference_now=ref,
            edition_latest_snapshot=latest_at_edition.get(finding.video_id),
        )
        items.append(
            {
                "video_id": row["video_id"],
                "rank": row["rank"],
                "coverage_category": row["coverage_category"],
                "outcome_window_phase": row["outcome_window_phase"],
                "coverage_reason": row["coverage_reason"],
            },
        )
        counts[row["coverage_category"]] += 1

    return {
        "report_date": report_date.isoformat(),
        "edition_signal_source_computed_at": (
            ensure_utc(report.source_computed_at).isoformat() if report.source_computed_at else None
        ),
        "reference_evaluated_at": ref.isoformat(),
        "winner_count": len(findings),
        "coverage_counts": dict(sorted(counts.items())),
        "coverage_by_category": {k: counts[k] for k in sorted(counts.keys())},
        "items": items,
    }


def get_winner_outcome_followup(
    session: Session,
    report_date: date,
    video_id: str,
    *,
    reference_now: datetime | None = None,
) -> dict[str, Any] | None:
    report = session.get(DailyIntelligenceReport, report_date)
    if report is None:
        return None
    finding = session.scalar(
        select(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == report_date,
            DailyIntelligenceReportWinnerFinding.video_id == video_id,
        ),
    )
    if finding is None:
        return None
    appearances = list(
        session.scalars(
            select(DailyIntelligenceRunWinnerAppearance).where(
                DailyIntelligenceRunWinnerAppearance.report_date == report_date,
                DailyIntelligenceRunWinnerAppearance.video_id == video_id,
            ).order_by(DailyIntelligenceRunWinnerAppearance.source_computed_at.asc()),
        ).all(),
    )
    snapshots = _snapshots_by_video(get_snapshots_for_videos(session, [video_id])).get(video_id, [])
    ref = ensure_utc(reference_now or utc_now())
    edition_signal = ensure_utc(report.source_computed_at) if report.source_computed_at else None
    latest_at_edition = (
        get_latest_snapshots_for_videos(session, [video_id], compute_before=edition_signal).get(video_id)
        if edition_signal is not None
        else None
    )
    return _build_followup_row(
        finding=finding,
        report=report,
        appearances=appearances,
        snapshots=snapshots,
        reference_now=ref,
        edition_latest_snapshot=latest_at_edition,
    )
