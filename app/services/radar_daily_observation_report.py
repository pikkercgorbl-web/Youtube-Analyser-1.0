"""Read-only UTC-day Radar observation report (two-week monitoring)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.models.orm import (
    AttentionRun,
    KeywordDiscoveryHit,
    KeywordExpansionEvent,
    KeywordLifecycleEvent,
    KeywordPerformanceGlobalSnapshot,
    KeywordScanRun,
    MonitoringCycleRun,
    OutcomeCaptureCycleRun,
    RadarApiBudgetDay,
    TopicExplorationPass,
    TopicExplorationPhrasePassStat,
    TopicExplorationVideoObservation,
    VideoSnapshot,
)
from app.services.attention_read_model import get_latest_attention_run
from app.services.delayed_outcome_capture_config import OUTCOME_CAPTURE_SOURCE
from app.services.discovery_worker_runtime import DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS
from app.services.keyword_performance_read_model import (
    count_keyword_performance_snapshots,
    get_latest_global_snapshot,
)
from app.services.keyword_scheduling_policy import LIFECYCLE_PROBATION
from app.services.metrics import ensure_utc
from app.services.monitoring_cycle import DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS
from app.services.operations_overview_service import _sanitize_error
from app.services.radar_api_budget import BUDGET_KIND_CHANNELS_LIST, BUDGET_KIND_VIDEOS_LIST
from app.services.radar_enrichment_config import radar_enrichment_settings
from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings
from app.services.worker_activity_policy import stale_activity_threshold_seconds

REPORT_VERSION = 2

T_EVENT = "event_in_utc_day"
T_DAY_END = "state_at_utc_day_end"
T_NOW = "current_at_generation"

TEMPORAL_LEGEND = {
    T_EVENT: "Count or sum of rows/events with timestamp in [window_start, window_end).",
    T_DAY_END: "Persisted state for the UTC calendar day or last publish strictly before window_end.",
    T_NOW: "Snapshot at generated_at_utc; not an end-of-day historical total.",
}

# Read-model freshness: same cadence as Task Scheduler defaults (setup_read_model_scheduled_tasks.ps1).
ATTENTION_EXPECTED_INTERVAL_SECONDS = 3600
KEYWORD_PERFORMANCE_EXPECTED_INTERVAL_SECONDS = 86400

OPTIONAL_TABLES = (
    "outcome_capture_cycle_runs",
    "keyword_expansion_events",
    "topic_exploration_passes",
    "topic_exploration_video_observations",
    "topic_exploration_phrase_pass_stats",
    "keyword_lifecycle_events",
)


class RadarDailyReportError(Exception):
    """Mandatory data source unavailable."""


def metric(value: Any, temporal_semantics: str) -> dict[str, Any]:
    return {"value": value, "temporal_semantics": temporal_semantics}


def metric_value(payload: Any) -> Any:
    if isinstance(payload, dict) and "temporal_semantics" in payload and "value" in payload:
        return payload["value"]
    return payload


def _attention_run_before(session: Session, before: datetime) -> AttentionRun | None:
    return session.scalar(
        select(AttentionRun)
        .where(AttentionRun.computed_at < before)
        .order_by(AttentionRun.computed_at.desc(), AttentionRun.run_id.desc())
        .limit(1),
    )


def _kp_global_before(session: Session, before: datetime) -> KeywordPerformanceGlobalSnapshot | None:
    return session.scalar(
        select(KeywordPerformanceGlobalSnapshot)
        .where(KeywordPerformanceGlobalSnapshot.evaluated_at < before)
        .order_by(
            KeywordPerformanceGlobalSnapshot.evaluated_at.desc(),
            KeywordPerformanceGlobalSnapshot.id.desc(),
        )
        .limit(1),
    )


def _attention_publish_payload(run: AttentionRun, *, temporal: str, age_hours: float | None) -> dict[str, Any]:
    return {
        "temporal_semantics": temporal,
        "run_id": run.run_id,
        "computed_at_utc": ensure_utc(run.computed_at).isoformat(),
        "age_hours_relative_to_report_generation": age_hours,
        "winner_count": run.winner_count,
        "pattern_count": run.pattern_count,
        "channel_momentum_count": run.channel_momentum_count,
    }


def _kp_publish_payload(
    session: Session,
    run: KeywordPerformanceGlobalSnapshot,
    *,
    temporal: str,
    age_hours: float | None,
) -> dict[str, Any]:
    rows = count_keyword_performance_snapshots(session, attribution_mode="first_discovery")
    return {
        "temporal_semantics": temporal,
        "run_id": run.run_id,
        "evaluated_at_utc": ensure_utc(run.evaluated_at).isoformat(),
        "age_hours_relative_to_report_generation": age_hours,
        "published_keyword_rows_first_discovery": rows,
        "global_eligible_video_count": run.global_eligible_video_count,
    }


@dataclass(frozen=True, slots=True)
class UtcDayWindow:
    utc_day: date
    window_start: datetime
    window_end: datetime
    day_complete: bool


def utc_day_window(
    utc_day: date,
    *,
    reference_now: datetime | None = None,
) -> UtcDayWindow:
    start = datetime(utc_day.year, utc_day.month, utc_day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    now = ensure_utc(reference_now or datetime.now(timezone.utc))
    complete = now >= end
    return UtcDayWindow(utc_day=utc_day, window_start=start, window_end=end, day_complete=complete)


def _table_exists(session: Session, name: str) -> bool:
    return name in inspect(session.get_bind()).get_table_names()


def _infer_discovery_cycle_status(rows: list[KeywordScanRun]) -> str:
    if not rows:
        return "unknown"
    failures = sum(1 for r in rows if r.status != "ok")
    selected = len(rows)
    if selected == 0:
        return "ok"
    if failures >= selected:
        return "failed"
    if failures > 0:
        return "partial"
    return "ok"


def _discovery_cycles_in_window(session: Session, window: UtcDayWindow) -> list[tuple[str, datetime, str]]:
    """Returns (discovery_run_id, cycle_finished_at, inferred_status)."""
    sub = (
        select(
            KeywordScanRun.discovery_run_id,
            func.max(KeywordScanRun.finished_at).label("cycle_end"),
        )
        .group_by(KeywordScanRun.discovery_run_id)
        .having(
            func.max(KeywordScanRun.finished_at) >= window.window_start,
            func.max(KeywordScanRun.finished_at) < window.window_end,
        )
    )
    cycle_rows = session.execute(sub).all()
    if not cycle_rows:
        return []
    run_ids = [r[0] for r in cycle_rows]
    scans = list(
        session.scalars(select(KeywordScanRun).where(KeywordScanRun.discovery_run_id.in_(run_ids))).all(),
    )
    by_run: dict[str, list[KeywordScanRun]] = {}
    for row in scans:
        by_run.setdefault(row.discovery_run_id, []).append(row)
    out: list[tuple[str, datetime, str]] = []
    for run_id, cycle_end in cycle_rows:
        status = _infer_discovery_cycle_status(by_run.get(run_id, []))
        out.append((run_id, ensure_utc(cycle_end), status))
    out.sort(key=lambda x: x[1])
    return out


def _budget_block(session: Session, *, utc_day: date) -> dict[str, Any]:
    limits = {
        "channels_list_id_units_daily_limit": radar_enrichment_settings.channel_subscriber_enrichment_daily_limit,
        "videos_list_id_units_daily_limit": unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit,
    }
    blocks: dict[str, Any] = {}
    for kind, limit_key in (
        (BUDGET_KIND_CHANNELS_LIST, "channels_list_id_units_daily_limit"),
        (BUDGET_KIND_VIDEOS_LIST, "videos_list_id_units_daily_limit"),
    ):
        row = session.get(RadarApiBudgetDay, {"budget_kind": kind, "utc_day": utc_day})
        reserved = int(row.id_units_reserved) if row else 0
        http_batches = int(row.http_requests) if row else 0
        limit = int(limits[limit_key])
        blocks[kind] = {
            "id_units_reserved": reserved,
            "http_batches": http_batches,
            "daily_id_units_limit": limit,
            "id_units_remaining": max(0, limit - reserved),
            "note": "Ledger counts reserved ID units and batch HTTP calls (get_channels/get_videos), not YouTube quota units.",
        }
    return blocks


def _section_availability(session: Session) -> dict[str, str]:
    avail: dict[str, str] = {}
    for name in OPTIONAL_TABLES:
        avail[name] = "available" if _table_exists(session, name) else "missing"
    return avail


def _require_tables(session: Session, names: tuple[str, ...]) -> None:
    missing = [n for n in names if not _table_exists(session, n)]
    if missing:
        raise RadarDailyReportError(f"Required tables missing: {', '.join(missing)}")


def build_radar_daily_observation_report(
    session: Session,
    *,
    utc_day: date,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate read-only metrics for one UTC calendar day."""
    _require_tables(
        session,
        (
            "keyword_scan_runs",
            "keyword_discovery_hits",
            "monitoring_cycle_runs",
            "video_snapshots",
            "radar_api_budget_daily",
            "attention_runs",
            "keyword_performance_global_snapshots",
        ),
    )

    now = ensure_utc(generated_at or datetime.now(timezone.utc))
    window = utc_day_window(utc_day, reference_now=now)
    availability = _section_availability(session)

    cycles = _discovery_cycles_in_window(session, window)
    status_counts: dict[str, int] = {}
    for _, _, st in cycles:
        status_counts[st] = status_counts.get(st, 0) + 1

    keywords_scanned = session.scalar(
        select(func.count())
        .select_from(KeywordScanRun)
        .where(
            KeywordScanRun.finished_at >= window.window_start,
            KeywordScanRun.finished_at < window.window_end,
        ),
    ) or 0

    hits_row = session.execute(
        select(
            func.count(KeywordDiscoveryHit.id),
            func.count(func.distinct(KeywordDiscoveryHit.video_id)),
        ).where(
            KeywordDiscoveryHit.discovered_at >= window.window_start,
            KeywordDiscoveryHit.discovered_at < window.window_end,
        ),
    ).one()
    hit_count = int(hits_row[0] or 0)
    hit_unique_videos = int(hits_row[1] or 0)

    last_all_scans_ok = next(((rid, fin) for rid, fin, st in reversed(cycles) if st == "ok"), None)
    last_error_cycle = next(
        ((rid, fin, st) for rid, fin, st in reversed(cycles) if st in ("failed", "partial")),
        None,
    )

    discovery_block: dict[str, Any] = {
        "section_temporal_semantics": T_EVENT,
        "distinct_discovery_run_ids_completed_in_window": metric(len(cycles), T_EVENT),
        "inferred_cycle_status_counts": metric(status_counts, T_EVENT),
        "keyword_scan_runs_finished_in_window": metric(int(keywords_scanned), T_EVENT),
        "discovery_hits_in_window": metric(hit_count, T_EVENT),
        "unique_video_id_from_hits_in_window": metric(hit_unique_videos, T_EVENT),
        "cycle_completion_rule": (
            "COUNT DISTINCT discovery_run_id WHERE max(keyword_scan_runs.finished_at) "
            "in [window_start, window_end)."
        ),
        "status_inference_note": (
            "Cycle status inferred from keyword_scan_runs in that discovery_run_id only: "
            "ok = every scan row status ok (not proof of full worker keyword batch)."
        ),
        "last_all_keyword_scans_ok_cycle_in_window": (
            {
                "temporal_semantics": T_EVENT,
                "discovery_run_id": last_all_scans_ok[0],
                "finished_at_utc": last_all_scans_ok[1].isoformat(),
            }
            if last_all_scans_ok
            else None
        ),
        "last_failed_or_partial_cycle_in_window": (
            {
                "temporal_semantics": T_EVENT,
                "discovery_run_id": last_error_cycle[0],
                "finished_at_utc": last_error_cycle[1].isoformat(),
                "inferred_status": last_error_cycle[2],
            }
            if last_error_cycle
            else None
        ),
        "units_note": "hits != unique videos; scan-runs != cycles (748 scans vs 187 discovery_run_id).",
    }

    mon_rows = list(
        session.scalars(
            select(MonitoringCycleRun)
            .where(
                MonitoringCycleRun.finished_at.is_not(None),
                MonitoringCycleRun.finished_at >= window.window_start,
                MonitoringCycleRun.finished_at < window.window_end,
            )
            .order_by(MonitoringCycleRun.finished_at.asc()),
        ).all(),
    )
    mon_by_status: dict[str, int] = {}
    for row in mon_rows:
        mon_by_status[row.cycle_status] = mon_by_status.get(row.cycle_status, 0) + 1

    def _sum(field: str) -> int:
        return sum(int(getattr(r, field) or 0) for r in mon_rows)

    snap_by_source = session.execute(
        select(VideoSnapshot.source, func.count(), func.count(func.distinct(VideoSnapshot.video_id)))
        .where(
            VideoSnapshot.captured_at >= window.window_start,
            VideoSnapshot.captured_at < window.window_end,
        )
        .group_by(VideoSnapshot.source)
        .order_by(VideoSnapshot.source),
    ).all()

    sel_sum = _sum("selected_request_count")
    ins_sum = _sum("inserted_snapshot_count")
    dup_sum = _sum("duplicate_snapshot_count")
    miss_sum = _sum("missing_count")
    fetch_sum = _sum("fetch_failed_count")
    val_sum = _sum("validation_failed_count")
    pers_sum = _sum("persistence_failed_count")
    outcome_request_sum = dup_sum + miss_sum + fetch_sum + val_sum + pers_sum + ins_sum

    monitoring_block = {
        "section_temporal_semantics": T_EVENT,
        "completed_cycles_by_status": metric(mon_by_status, T_EVENT),
        "completed_cycle_count": metric(len(mon_rows), T_EVENT),
        "aggregated_across_cycles_in_window": {
            "temporal_semantics": T_EVENT,
            "loaded_video_count": metric(_sum("loaded_video_count"), T_EVENT),
            "eligible_video_count": metric(_sum("eligible_video_count"), T_EVENT),
            "selected_request_count": metric(sel_sum, T_EVENT),
            "inserted_snapshot_count": metric(ins_sum, T_EVENT),
            "deferred_request_count": metric(_sum("deferred_request_count"), T_EVENT),
            "due_count": metric(_sum("due_count"), T_EVENT),
            "overdue_count": metric(_sum("overdue_count"), T_EVENT),
            "duplicate_snapshot_count": metric(dup_sum, T_EVENT),
            "missing_count": metric(miss_sum, T_EVENT),
            "fetch_failed_count": metric(fetch_sum, T_EVENT),
            "validation_failed_count": metric(val_sum, T_EVENT),
            "persistence_failed_count": metric(pers_sum, T_EVENT),
        },
        "selected_vs_inserted_reconciliation": {
            "temporal_semantics": T_EVENT,
            "selected_request_count_sum": sel_sum,
            "inserted_snapshot_count_sum": ins_sum,
            "outcome_counts_from_cycle_summaries": {
                "inserted_snapshot_count": ins_sum,
                "duplicate_snapshot_count": dup_sum,
                "missing_count": miss_sum,
                "fetch_failed_count": fetch_sum,
                "validation_failed_count": val_sum,
                "persistence_failed_count": pers_sum,
                "sum_of_outcome_counters": outcome_request_sum,
            },
            "gap_selected_minus_sum_of_outcome_counters": sel_sum - outcome_request_sum,
            "note": (
                "selected_request_count is budget-selected capture requests per cycle; execution deduplicates "
                "requests before fetch. Outcome counters are per unique request after dedup — their sum may "
                "be less than selected. duplicate/missing/fetch/validation/persistence explain non-insert paths; "
                "residual gap is not guaranteed zero."
            ),
        },
        "snapshots_in_window_by_source": metric(
            {
                src: {"snapshot_rows": int(cnt), "unique_video_id": int(uniq)}
                for src, cnt, uniq in snap_by_source
            },
            T_EVENT,
        ),
        "last_completed_cycle_in_window": (
            {
                "temporal_semantics": T_EVENT,
                "run_id": mon_rows[-1].run_id,
                "finished_at_utc": ensure_utc(mon_rows[-1].finished_at).isoformat(),
                "cycle_status": mon_rows[-1].cycle_status,
                "selected_request_count": mon_rows[-1].selected_request_count,
                "inserted_snapshot_count": mon_rows[-1].inserted_snapshot_count,
                "duplicate_snapshot_count": mon_rows[-1].duplicate_snapshot_count,
                "missing_count": mon_rows[-1].missing_count,
                "due_count": mon_rows[-1].due_count,
                "overdue_count": mon_rows[-1].overdue_count,
                "error_summary": _sanitize_error(mon_rows[-1].error_summary),
            }
            if mon_rows
            else None
        ),
        "units_note": "Cycles vs snapshots vs selected requests are separate units; loaded/eligible sums repeat each cycle.",
    }

    ledger = _budget_block(session, utc_day=utc_day)
    enrichment_block: dict[str, Any] = {
        "radar_enrichment_after_discovery": metric(
            radar_enrichment_settings.radar_enrichment_after_discovery,
            T_NOW,
        ),
        "utc_day_ledger": {
            "temporal_semantics": T_DAY_END,
            "utc_day": utc_day.isoformat(),
            "kinds": ledger,
        },
        "attempt_table_outcomes_in_window": {
            "channel_subscriber_enrichment_attempts": None,
            "video_format_enrichment_attempts": None,
            "explanation": (
                "Tables store last outcome per channel_id/video_id only; "
                "not a daily attempt history — daily conversion is not measured."
            ),
        },
    }

    outcome_block: dict[str, Any]
    if availability.get("outcome_capture_cycle_runs") == "available":
        oc_rows = list(
            session.scalars(
                select(OutcomeCaptureCycleRun)
                .where(
                    OutcomeCaptureCycleRun.finished_at.is_not(None),
                    OutcomeCaptureCycleRun.finished_at >= window.window_start,
                    OutcomeCaptureCycleRun.finished_at < window.window_end,
                )
                .order_by(OutcomeCaptureCycleRun.finished_at.asc()),
            ).all(),
        )
        oc_by_status: dict[str, int] = {}
        for row in oc_rows:
            oc_by_status[row.cycle_status] = oc_by_status.get(row.cycle_status, 0) + 1
        outcome_snaps = session.execute(
            select(func.count(), func.count(func.distinct(VideoSnapshot.video_id)))
            .where(
                VideoSnapshot.source == OUTCOME_CAPTURE_SOURCE,
                VideoSnapshot.captured_at >= window.window_start,
                VideoSnapshot.captured_at < window.window_end,
            ),
        ).one()
        outcome_block = {
            "section_status": "available",
            "completed_cycles_by_status": oc_by_status,
            "completed_cycle_count": len(oc_rows),
            "aggregated_across_cycles_in_window": {
                "selected_video_count": sum(int(r.selected_video_count) for r in oc_rows),
                "inserted_snapshot_count": sum(int(r.inserted_snapshot_count) for r in oc_rows),
                "fetch_failed_count": sum(int(r.fetch_failed_count) for r in oc_rows),
            },
            "snapshots_source_keyword_outcome_worker": {
                "snapshot_rows": int(outcome_snaps[0] or 0),
                "unique_video_id": int(outcome_snaps[1] or 0),
            },
            "last_completed_cycle_in_window": (
                {
                    "run_id": oc_rows[-1].run_id,
                    "finished_at_utc": ensure_utc(oc_rows[-1].finished_at).isoformat(),
                    "cycle_status": oc_rows[-1].cycle_status,
                    "error_summary": _sanitize_error(oc_rows[-1].error_summary),
                }
                if oc_rows
                else None
            ),
        }
    else:
        outcome_block = {
            "section_status": "unavailable",
            "reason": "outcome_capture_cycle_runs table missing on this database",
        }

    attention_latest = get_latest_attention_run(session)
    kp_latest = get_latest_global_snapshot(session)
    attention_day_end = _attention_run_before(session, window.window_end)
    kp_day_end = _kp_global_before(session, window.window_end)

    def _age_hours(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        return round((now - ensure_utc(ts)).total_seconds() / 3600.0, 2)

    read_models_block = {
        "retention_note": (
            "Attention and Keyword Performance use replace-on-publish; older runs are not retained. "
            "publish_as_of_utc_day_end uses the latest row with evaluated/computed_at < window_end."
        ),
        "historical_limitation": (
            "If publish_as_of_utc_day_end is null, publication history before window_end was already "
            "replaced and cannot be reconstructed from the database. "
            "latest_in_database_at_generation reflects current_at_generation only — not end-of-report-day state."
        ),
        "attention": {
            "publish_as_of_utc_day_end": (
                _attention_publish_payload(attention_day_end, temporal=T_DAY_END, age_hours=_age_hours(attention_day_end.computed_at))
                if attention_day_end
                else None
            ),
            "latest_in_database_at_generation": (
                _attention_publish_payload(attention_latest, temporal=T_NOW, age_hours=_age_hours(attention_latest.computed_at))
                if attention_latest
                else None
            ),
        },
        "keyword_performance": {
            "publish_as_of_utc_day_end": (
                _kp_publish_payload(session, kp_day_end, temporal=T_DAY_END, age_hours=_age_hours(kp_day_end.evaluated_at))
                if kp_day_end
                else None
            ),
            "latest_in_database_at_generation": (
                _kp_publish_payload(session, kp_latest, temporal=T_NOW, age_hours=_age_hours(kp_latest.evaluated_at))
                if kp_latest
                else None
            ),
        },
    }

    expansion_block: dict[str, Any] = {"llm_expansion": {"status": "not_connected", "note": "No LLM query integration in application runtime."}}
    if availability.get("keyword_expansion_events") == "available":
        exp_rows = session.execute(
            select(KeywordExpansionEvent.source_type, func.count())
            .where(
                KeywordExpansionEvent.discovered_at >= window.window_start,
                KeywordExpansionEvent.discovered_at < window.window_end,
            )
            .group_by(KeywordExpansionEvent.source_type)
            .order_by(KeywordExpansionEvent.source_type),
        ).all()
        expansion_block["expansion_events_by_source_type"] = metric(
            {src: int(n) for src, n in exp_rows},
            T_EVENT,
        )
        expansion_block["probation_keywords_created"] = None
    else:
        expansion_block["section_status"] = "unavailable"
        expansion_block["expansion_events_by_source_type"] = None
        expansion_block["reason"] = "keyword_expansion_events table missing"

    if availability.get("keyword_lifecycle_events") == "available":
        prob_count = session.scalar(
            select(func.count())
            .select_from(KeywordLifecycleEvent)
            .where(
                KeywordLifecycleEvent.to_status == LIFECYCLE_PROBATION,
                KeywordLifecycleEvent.changed_at >= window.window_start,
                KeywordLifecycleEvent.changed_at < window.window_end,
            ),
        )
        expansion_block["probation_keywords_created"] = metric(int(prob_count or 0), T_EVENT)

    exploration_block: dict[str, Any] = {}
    if availability.get("topic_exploration_passes") == "available":
        pass_rows = session.execute(
            select(TopicExplorationPass.status, func.count())
            .where(
                TopicExplorationPass.finished_at >= window.window_start,
                TopicExplorationPass.finished_at < window.window_end,
            )
            .group_by(TopicExplorationPass.status),
        ).all()
        exploration_block["section_temporal_semantics"] = T_EVENT
        exploration_block["passes_by_status"] = metric({st: int(n) for st, n in pass_rows}, T_EVENT)
        exploration_block["pass_count"] = metric(sum(int(n) for _, n in pass_rows), T_EVENT)
    else:
        exploration_block["section_status"] = "unavailable"
        exploration_block["reason"] = "topic_exploration_passes table missing"

    if (
        availability.get("topic_exploration_passes") == "available"
        and availability.get("topic_exploration_video_observations") == "available"
    ):
        vo = session.execute(
            select(
                func.count(TopicExplorationVideoObservation.id),
                func.count(func.distinct(TopicExplorationVideoObservation.video_id)),
            )
            .select_from(TopicExplorationVideoObservation)
            .join(TopicExplorationPass, TopicExplorationVideoObservation.pass_id == TopicExplorationPass.id)
            .where(
                TopicExplorationPass.finished_at >= window.window_start,
                TopicExplorationPass.finished_at < window.window_end,
            ),
        ).one()
        exploration_block["video_observations_in_window"] = metric(int(vo[0] or 0), T_EVENT)
        exploration_block["unique_video_id_observed"] = metric(int(vo[1] or 0), T_EVENT)
    else:
        exploration_block["video_observations_in_window"] = None

    if (
        availability.get("topic_exploration_passes") == "available"
        and availability.get("topic_exploration_phrase_pass_stats") == "available"
    ):
        phrase_count = session.scalar(
            select(func.count())
            .select_from(TopicExplorationPhrasePassStat)
            .join(TopicExplorationPass, TopicExplorationPhrasePassStat.pass_id == TopicExplorationPass.id)
            .where(
                TopicExplorationPass.finished_at >= window.window_start,
                TopicExplorationPass.finished_at < window.window_end,
            ),
        )
        admitted = session.scalar(
            select(func.count())
            .select_from(TopicExplorationPhrasePassStat)
            .join(TopicExplorationPass, TopicExplorationPhrasePassStat.pass_id == TopicExplorationPass.id)
            .where(
                TopicExplorationPass.finished_at >= window.window_start,
                TopicExplorationPass.finished_at < window.window_end,
                TopicExplorationPhrasePassStat.admitted_keyword_id.is_not(None),
            ),
        )
        exploration_block["phrase_rows_in_window"] = metric(int(phrase_count or 0), T_EVENT)
        exploration_block["phrases_admitted_to_keywords"] = metric(int(admitted or 0), T_EVENT)
    else:
        exploration_block["phrase_rows_in_window"] = None
        exploration_block["phrases_admitted_to_keywords"] = None

    diagnostics_for_day, diagnostics_at_generation = _build_diagnostics(
        session,
        window=window,
        now=now,
        discovery_cycles=cycles,
        monitoring_rows=mon_rows,
        enrichment=enrichment_block,
        attention_latest=attention_latest,
    )

    return {
        "report_version": REPORT_VERSION,
        "temporal_semantics_legend": TEMPORAL_LEGEND,
        "generated_at_utc": now.isoformat(),
        "utc_day": utc_day.isoformat(),
        "window_start_utc": window.window_start.isoformat(),
        "window_end_utc": window.window_end.isoformat(),
        "day_complete": window.day_complete,
        "table_availability": availability,
        "discovery": discovery_block,
        "enrichment": enrichment_block,
        "monitoring": monitoring_block,
        "outcome_capture": outcome_block,
        "read_models": read_models_block,
        "expansion_and_exploration": {**expansion_block, "exploration": exploration_block},
        "diagnostics_for_utc_day": diagnostics_for_day,
        "diagnostics_at_generation": diagnostics_at_generation,
    }


def _build_diagnostics(
    session: Session,
    *,
    window: UtcDayWindow,
    now: datetime,
    discovery_cycles: list[tuple[str, datetime, str]],
    monitoring_rows: list[MonitoringCycleRun],
    enrichment: dict[str, Any],
    attention_latest: AttentionRun | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    day_notes: list[dict[str, str]] = []
    gen_notes: list[dict[str, str]] = []

    if not discovery_cycles and window.day_complete:
        day_notes.append(
            {
                "code": "no_discovery_cycles_in_day",
                "severity": "info",
                "message": "No discovery cycles finished in this UTC day.",
            },
        )

    if not window.day_complete:
        disc_threshold = stale_activity_threshold_seconds(DEFAULT_DISCOVERY_WORKER_INTERVAL_SECONDS)
        last_disc = session.scalar(select(func.max(KeywordScanRun.finished_at)))
        if last_disc is not None:
            age = (now - ensure_utc(last_disc)).total_seconds()
            if age > disc_threshold:
                gen_notes.append(
                    {
                        "code": "discovery_cycle_stale_at_report_time",
                        "severity": "warning",
                        "message": (
                            f"No discovery cycle finished in ~{age:.0f}s "
                            f"(threshold ~{disc_threshold}s from worker activity policy)."
                        ),
                    },
                )
        mon_threshold = stale_activity_threshold_seconds(DEFAULT_MONITORING_WORKER_INTERVAL_SECONDS)
        last_mon_global = session.scalar(
            select(func.max(MonitoringCycleRun.finished_at)).where(MonitoringCycleRun.finished_at.is_not(None)),
        )
        if last_mon_global is not None:
            age_m = (now - ensure_utc(last_mon_global)).total_seconds()
            if age_m > mon_threshold:
                gen_notes.append(
                    {
                        "code": "monitoring_cycle_stale_at_report_time",
                        "severity": "warning",
                        "message": (
                            f"No monitoring cycle finished in ~{age_m:.0f}s (threshold ~{mon_threshold}s)."
                        ),
                    },
                )

    if monitoring_rows:
        quiet_cycles = 0
        for row in monitoring_rows:
            if int(row.selected_request_count) > 0 and int(row.inserted_snapshot_count) == 0:
                day_notes.append(
                    {
                        "code": "monitoring_selected_without_insert",
                        "severity": "warning",
                        "message": (
                            f"Monitoring cycle {row.run_id}: selected_request_count="
                            f"{row.selected_request_count} but inserted_snapshot_count=0."
                        ),
                    },
                )
            if (
                int(row.selected_request_count) == 0
                and int(row.due_count) == 0
                and int(row.overdue_count) == 0
            ):
                quiet_cycles += 1
        if quiet_cycles:
            day_notes.append(
                {
                    "code": "monitoring_quiet_pool",
                    "severity": "info",
                    "message": (
                        f"{quiet_cycles} monitoring cycle(s) in window with selected=0, due=0, overdue=0 "
                        "(expected quiet pool, not an error)."
                    ),
                },
            )

    ledger_kinds = enrichment["utc_day_ledger"].get("kinds", {})
    for kind in (BUDGET_KIND_CHANNELS_LIST, BUDGET_KIND_VIDEOS_LIST):
        block = ledger_kinds.get(kind, {})
        rem = int(block.get("id_units_remaining", 0))
        limit = int(block.get("daily_id_units_limit", 0))
        if limit > 0 and rem == 0:
            day_notes.append(
                {
                    "code": "enrichment_budget_exhausted",
                    "severity": "warning",
                    "message": f"UTC-day {kind} id_units_remaining=0 (limit={limit}).",
                },
            )

    if attention_latest is None:
        gen_notes.append(
            {
                "code": "attention_never_published",
                "severity": "warning",
                "message": "No Attention run in database at generation time.",
            },
        )
    else:
        att_age = (now - ensure_utc(attention_latest.computed_at)).total_seconds()
        att_threshold = stale_activity_threshold_seconds(ATTENTION_EXPECTED_INTERVAL_SECONDS)
        if att_age > att_threshold:
            gen_notes.append(
                {
                    "code": "attention_stale_at_generation",
                    "severity": "warning",
                    "message": (
                        f"Latest Attention in DB is {att_age:.0f}s old at generation "
                        f"(threshold ~{att_threshold}s; current_at_generation, not end-of-day)."
                    ),
                },
            )

    return day_notes, gen_notes


def compute_day_over_day(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    prev_day = (previous or {}).get("utc_day")
    if previous is None:
        return {
            "status": "skipped",
            "reason": "previous_utc_day_file_missing",
            "previous_utc_day": None,
            "deltas": [],
        }
    if not current.get("day_complete"):
        return {
            "status": "skipped",
            "reason": "current_utc_day_incomplete",
            "previous_utc_day": prev_day,
            "deltas": [],
        }
    if not previous.get("day_complete"):
        return {
            "status": "skipped",
            "reason": "previous_utc_day_incomplete",
            "previous_utc_day": prev_day,
            "deltas": [],
        }
    pairs: list[tuple[str, tuple[str, ...], tuple[str, ...] | None]] = [
        (
            "Discovery hits",
            ("discovery", "discovery_hits_in_window"),
            None,
        ),
        (
            "Discovery cycles (distinct discovery_run_id)",
            ("discovery", "distinct_discovery_run_ids_completed_in_window"),
            ("discovery", "completed_cycle_count"),
        ),
        (
            "Monitoring inserted snapshots",
            ("monitoring", "aggregated_across_cycles_in_window", "inserted_snapshot_count"),
            None,
        ),
        (
            "Monitoring selected requests",
            ("monitoring", "aggregated_across_cycles_in_window", "selected_request_count"),
            None,
        ),
    ]
    deltas: list[dict[str, Any]] = []
    for label, path, legacy_path in pairs:
        cur_val = metric_value(_nested_get(current, path))
        prev_val = metric_value(_nested_get(previous, path))
        if prev_val is None and legacy_path is not None:
            prev_val = metric_value(_nested_get(previous, legacy_path))
        if isinstance(cur_val, int) and isinstance(prev_val, int):
            deltas.append(
                {
                    "label": label,
                    "previous_utc_day": prev_day,
                    "previous": prev_val,
                    "current": cur_val,
                    "delta": cur_val - prev_val,
                },
            )
    return {
        "status": "compared",
        "reason": None,
        "previous_utc_day": prev_day,
        "deltas": deltas,
    }


def render_radar_daily_observation_markdown(
    report: dict[str, Any],
    *,
    previous_day_report: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    day = report["utc_day"]
    lines.append(f"# Radar daily observation — UTC {day}")
    lines.append("")
    lines.append(f"- Generated: {report['generated_at_utc']}")
    lines.append(f"- Window: [{report['window_start_utc']}, {report['window_end_utc']})")
    if not report.get("day_complete"):
        lines.append("- **UTC day still in progress** (incomplete day).")
    lines.append("")

    def _h2(title: str) -> None:
        lines.append(f"## {title}")
        lines.append("")

    _h2("Discovery (events in UTC day)")
    d = report["discovery"]
    lines.append(
        f"- Distinct discovery_run_id completed: {metric_value(d.get('distinct_discovery_run_ids_completed_in_window', 0))} "
        f"(inferred status {metric_value(d.get('inferred_cycle_status_counts', {}))})",
    )
    lines.append(f"- Keyword scan runs finished: {metric_value(d.get('keyword_scan_runs_finished_in_window', 0))}")
    lines.append(
        f"- Hits: {metric_value(d.get('discovery_hits_in_window', 0))} "
        f"(unique video_id: {metric_value(d.get('unique_video_id_from_hits_in_window', 0))})",
    )
    if d.get("last_all_keyword_scans_ok_cycle_in_window"):
        ls = d["last_all_keyword_scans_ok_cycle_in_window"]
        lines.append(f"- Last all-scans-ok cycle: `{ls['discovery_run_id']}` @ {ls['finished_at_utc']}")
    lines.append("")

    _h2("Enrichment (ledger for UTC day)")
    ledger = report["enrichment"]["utc_day_ledger"]
    for kind, block in ledger.get("kinds", {}).items():
        lines.append(
            f"- **{kind}**: id_units {block['id_units_reserved']}/{block['daily_id_units_limit']}, "
            f"http_batches {block['http_batches']}, remaining {block['id_units_remaining']}",
        )
    lines.append(f"- {report['enrichment']['attempt_table_outcomes_in_window']['explanation']}")
    lines.append("")

    _h2("Monitoring (events in UTC day)")
    m = report["monitoring"]
    agg = m.get("aggregated_across_cycles_in_window") or {}
    lines.append(
        f"- Cycles: {metric_value(m.get('completed_cycle_count', 0))} "
        f"{metric_value(m.get('completed_cycles_by_status', {}))}",
    )
    lines.append(
        f"- Totals: loaded {metric_value(agg.get('loaded_video_count', 0))}, "
        f"eligible {metric_value(agg.get('eligible_video_count', 0))}, "
        f"selected {metric_value(agg.get('selected_request_count', 0))}, "
        f"inserted {metric_value(agg.get('inserted_snapshot_count', 0))}, "
        f"due {metric_value(agg.get('due_count', 0))}, overdue {metric_value(agg.get('overdue_count', 0))}, "
        f"deferred {metric_value(agg.get('deferred_request_count', 0))}",
    )
    recon = m.get("selected_vs_inserted_reconciliation") or {}
    oc = recon.get("outcome_counts_from_cycle_summaries") or {}
    if recon:
        lines.append(
            f"- Selected→inserted reconciliation: selected {recon.get('selected_request_count_sum')}, "
            f"inserted {oc.get('inserted_snapshot_count')}, duplicate {oc.get('duplicate_snapshot_count')}, "
            f"missing {oc.get('missing_count')}, fetch_failed {oc.get('fetch_failed_count')}, "
            f"validation_failed {oc.get('validation_failed_count')}, persistence_failed {oc.get('persistence_failed_count')}, "
            f"gap(selected−Σoutcomes) {recon.get('gap_selected_minus_sum_of_outcome_counters')}",
        )
    snaps = metric_value(m.get("snapshots_in_window_by_source")) or {}
    if snaps:
        lines.append("- Snapshots by source (DB rows, captured_at in day):")
        for src, vals in sorted(snaps.items()):
            lines.append(f"  - `{src}`: rows {vals['snapshot_rows']}, unique video_id {vals['unique_video_id']}")
    lines.append("")

    _h2("Outcome capture")
    oc = report["outcome_capture"]
    if oc.get("section_status") == "unavailable":
        lines.append(f"- Unavailable: {oc.get('reason')}")
    else:
        agg_oc = oc["aggregated_across_cycles_in_window"]
        lines.append(f"- Cycles: {oc['completed_cycle_count']}")
        lines.append(
            f"- selected videos {agg_oc['selected_video_count']}, inserted {agg_oc['inserted_snapshot_count']}, "
            f"fetch_failed {agg_oc['fetch_failed_count']}",
        )
        snap = oc["snapshots_source_keyword_outcome_worker"]
        lines.append(f"- Outcome snapshots: {snap['snapshot_rows']} rows, {snap['unique_video_id']} unique video_id")
    lines.append("")

    _h2("Read models")
    rm = report["read_models"]
    att_end = rm.get("attention", {}).get("publish_as_of_utc_day_end")
    att_now = rm.get("attention", {}).get("latest_in_database_at_generation")
    if att_end:
        lines.append(
            f"- Attention as of UTC day end: `{att_end['run_id']}` @ {att_end['computed_at_utc']} "
            f"(winners {att_end['winner_count']})",
        )
    else:
        lines.append("- Attention as of UTC day end: none with computed_at < window_end (or not retained)")
    if att_now:
        lines.append(
            f"- Attention latest at generation: `{att_now['run_id']}` @ {att_now['computed_at_utc']} "
            f"(age {att_now['age_hours_relative_to_report_generation']}h)",
        )
    kp_end = rm.get("keyword_performance", {}).get("publish_as_of_utc_day_end")
    kp_now = rm.get("keyword_performance", {}).get("latest_in_database_at_generation")
    if kp_end:
        lines.append(
            f"- Keyword Performance as of UTC day end: `{kp_end['run_id']}` @ {kp_end['evaluated_at_utc']} "
            f"({kp_end['published_keyword_rows_first_discovery']} keyword rows)",
        )
    else:
        lines.append("- Keyword Performance as of UTC day end: none with evaluated_at < window_end")
    if kp_now:
        lines.append(
            f"- Keyword Performance latest at generation: `{kp_now['run_id']}` @ {kp_now['evaluated_at_utc']} "
            f"(age {kp_now['age_hours_relative_to_report_generation']}h)",
        )
    lines.append("")

    _h2("Expansion / exploration")
    ee = report["expansion_and_exploration"]
    lines.append(f"- LLM: {ee['llm_expansion']['status']} — {ee['llm_expansion']['note']}")
    if ee.get("expansion_events_by_source_type") is not None:
        lines.append(f"- Expansion events by source: {metric_value(ee['expansion_events_by_source_type'])}")
    elif ee.get("section_status") == "unavailable":
        lines.append(f"- Expansion events: unavailable ({ee.get('reason')})")
    if ee.get("probation_keywords_created") is not None:
        lines.append(f"- Probation keywords created: {metric_value(ee['probation_keywords_created'])}")
    ex = ee.get("exploration", {})
    if ex.get("section_status") == "unavailable":
        lines.append(f"- Exploration: unavailable ({ex.get('reason')})")
    else:
        lines.append(
            f"- Exploration passes: {metric_value(ex.get('pass_count', 0))} "
            f"by status {metric_value(ex.get('passes_by_status', {}))}",
        )
        if ex.get("video_observations_in_window") is not None:
            lines.append(
                f"- Video observations: {metric_value(ex['video_observations_in_window'])} "
                f"(unique video_id {metric_value(ex.get('unique_video_id_observed'))})",
            )
        if ex.get("phrase_rows_in_window") is not None:
            lines.append(
                f"- Phrase stats rows: {metric_value(ex['phrase_rows_in_window'])}, "
                f"admitted {metric_value(ex.get('phrases_admitted_to_keywords'))}",
            )
    lines.append("")

    if report.get("diagnostics_for_utc_day"):
        _h2("Diagnostics (UTC day scope)")
        for item in report["diagnostics_for_utc_day"]:
            lines.append(f"- [{item['severity']}] {item['code']}: {item['message']}")
        lines.append("")
    if report.get("diagnostics_at_generation"):
        _h2("Diagnostics (at report generation)")
        for item in report["diagnostics_at_generation"]:
            lines.append(f"- [{item['severity']}] {item['code']}: {item['message']}")
        lines.append("")

    dod = report.get("day_over_day")
    if dod:
        _h2("Day-over-day")
        if dod.get("status") != "compared":
            lines.append(f"- Skipped: {dod.get('reason')} (not zero activity).")
        else:
            for row in dod.get("deltas", []):
                lines.append(
                    f"- {row['label']} vs {row['previous_utc_day']}: "
                    f"{row['previous']} → {row['current']} (Δ {row['delta']:+d})",
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def write_radar_daily_observation_artifacts(
    report: dict[str, Any],
    *,
    output_dir: Path,
    previous_day_report: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    day = report["utc_day"]
    report = dict(report)
    report["day_over_day"] = compute_day_over_day(report, previous_day_report)

    json_path = output_dir / f"{day}.json"
    md_path = output_dir / f"{day}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(
        render_radar_daily_observation_markdown(report, previous_day_report=previous_day_report),
        encoding="utf-8",
    )
    return json_path, md_path


def load_previous_day_report(output_dir: Path, utc_day: date) -> dict[str, Any] | None:
    prev = utc_day - timedelta(days=1)
    path = output_dir / "original" / f"{prev.isoformat()}.json"
    if not path.is_file():
        legacy = output_dir / f"{prev.isoformat()}.json"
        if legacy.is_file():
            path = legacy
        else:
            return None
    return json.loads(path.read_text(encoding="utf-8"))
