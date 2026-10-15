"""Capture daily intelligence from Attention publish (Stage 1.23A)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.orm import (
    DailyIntelligenceReport,
    DailyIntelligenceReportFamilyFinding,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunFamilyAppearance,
    DailyIntelligenceRunSnapshot,
    DailyIntelligenceRunWinnerAppearance,
    KeywordDiscoveryHit,
)
from app.services.attention_engine_types import (
    AttentionEngineResult,
    pattern_family_to_dict,
    video_winner_to_dict,
)
from app.services.metrics import ensure_utc, utc_now

STATUS_PROVISIONAL = "provisional"
STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"

# Last publish more than this many hours before UTC day end → partial coverage when locking.
LAST_PUBLISH_PARTIAL_GAP_HOURS = 3


def utc_report_date(dt: datetime) -> date:
    return ensure_utc(dt).date()


def utc_day_end(report_date: date) -> datetime:
    start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
    return start + timedelta(days=1)


def utc_day_start(report_date: date) -> datetime:
    return datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)


def discovery_provenance_for_video(session: Session, video_id: str) -> dict[str, Any]:
    """Earliest usable KeywordDiscoveryHit (same basis as delayed_outcome_for_video)."""
    hits = list(
        session.scalars(
            select(KeywordDiscoveryHit)
            .where(KeywordDiscoveryHit.video_id == video_id)
            .order_by(KeywordDiscoveryHit.discovered_at.asc(), KeywordDiscoveryHit.id.asc()),
        ).all(),
    )
    usable = [h for h in hits if h.views_at_discovery is not None]
    if not usable:
        if hits:
            h = hits[0]
            return {
                "available": False,
                "reason": "no_views_at_discovery",
                "discovery_hit_id": h.id,
                "keyword_id": h.keyword_id,
                "discovered_at": ensure_utc(h.discovered_at).isoformat(),
                "discovery_run_id": h.discovery_run_id,
            }
        return {"available": False, "reason": "no_discovery_hits"}
    hit = usable[0]
    return {
        "available": True,
        "discovery_hit_id": hit.id,
        "keyword_id": hit.keyword_id,
        "discovered_at": ensure_utc(hit.discovered_at).isoformat(),
        "discovery_run_id": hit.discovery_run_id,
        "views_at_discovery": hit.views_at_discovery,
        "vph_at_discovery": hit.vph_at_discovery,
        "outcome_anchor": "discovered_at_plus_72h",
    }


def _winner_had_prior_report(session: Session, video_id: str, before_date: date) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(DailyIntelligenceReportWinnerFinding)
            .where(
                DailyIntelligenceReportWinnerFinding.video_id == video_id,
                DailyIntelligenceReportWinnerFinding.report_date < before_date,
            ),
        )
        or 0
    ) > 0


def _family_had_prior_report(session: Session, family_key: str, before_date: date) -> bool:
    return (
        session.scalar(
            select(func.count())
            .select_from(DailyIntelligenceReportFamilyFinding)
            .where(
                DailyIntelligenceReportFamilyFinding.family_key == family_key,
                DailyIntelligenceReportFamilyFinding.report_date < before_date,
            ),
        )
        or 0
    ) > 0


def _coverage_gaps_for_lock(*, report_date: date, source_computed_at: datetime | None) -> list[str]:
    gaps: list[str] = []
    if source_computed_at is None:
        gaps.append("no_attention_publish_on_utc_day")
        return gaps
    day_end = utc_day_end(report_date)
    cutoff = day_end - timedelta(hours=LAST_PUBLISH_PARTIAL_GAP_HOURS)
    if ensure_utc(source_computed_at) < cutoff:
        gaps.append(
            f"last_publish_before_cutoff: source_computed_at={ensure_utc(source_computed_at).isoformat()} "
            f"cutoff={cutoff.isoformat()}",
        )
    return gaps


def _status_for_locked_report(*, gaps: list[str], has_publish: bool) -> str:
    if not has_publish:
        return STATUS_UNAVAILABLE
    if gaps:
        return STATUS_PARTIAL
    return STATUS_COMPLETE


def capture_daily_intelligence_for_publish(
    session: Session,
    result: AttentionEngineResult,
    *,
    run_id: str,
    captured_at: datetime | None = None,
) -> None:
    """
    Persist run-level appearances and update provisional daily edition.

    Must run in the same transaction as Attention publish, before attention_* DELETE.
    Idempotent on source_run_id (safe retry).
    """
    if session.get(DailyIntelligenceRunSnapshot, run_id) is not None:
        return

    summary = result.summary
    computed_at = ensure_utc(summary.computed_at)
    report_date = utc_report_date(computed_at)
    now = ensure_utc(captured_at or utc_now())

    session.add(
        DailyIntelligenceRunSnapshot(
            source_run_id=run_id,
            report_date=report_date,
            source_computed_at=computed_at,
            captured_at=now,
            winner_count=len(result.video_winners),
            family_count=len(result.families),
        ),
    )
    session.flush()

    for rank, winner in enumerate(result.video_winners, start=1):
        prov = discovery_provenance_for_video(session, winner.video_id)
        session.add(
            DailyIntelligenceRunWinnerAppearance(
                source_run_id=run_id,
                report_date=report_date,
                source_computed_at=computed_at,
                video_id=winner.video_id,
                rank=rank,
                title=winner.title or "",
                channel_id=winner.channel_id or "",
                discovery_provenance_json=json.dumps(prov, ensure_ascii=False),
                payload_json=json.dumps(video_winner_to_dict(winner), ensure_ascii=False),
            ),
        )

    for rank, family in enumerate(result.families, start=1):
        session.add(
            DailyIntelligenceRunFamilyAppearance(
                source_run_id=run_id,
                report_date=report_date,
                source_computed_at=computed_at,
                family_key=family.family_key,
                rank=rank,
                label=family.label or "",
                video_count=family.video_count,
                channel_count=family.channel_count,
                payload_json=json.dumps(pattern_family_to_dict(family), ensure_ascii=False),
            ),
        )

    report_row = session.get(DailyIntelligenceReport, report_date)
    if report_row is None or report_row.locked_at is None:
        _refresh_provisional_daily_edition(
            session,
            result=result,
            run_id=run_id,
            report_date=report_date,
            computed_at=computed_at,
            generated_at=now,
        )
    finalize_eligible_reports(session, now=now)


def _refresh_provisional_daily_edition(
    session: Session,
    *,
    result: AttentionEngineResult,
    run_id: str,
    report_date: date,
    computed_at: datetime,
    generated_at: datetime,
) -> None:
    row = session.get(DailyIntelligenceReport, report_date)
    if row is not None and row.locked_at is not None:
        return

    summary = result.summary
    repeats_w = 0
    repeats_f = 0

    if row is None:
        row = DailyIntelligenceReport(
            report_date=report_date,
            status=STATUS_PROVISIONAL,
            generated_at=generated_at,
            publish_attempt=0,
        )
        session.add(row)

    row.source_run_id = run_id
    row.source_computed_at = computed_at
    row.source_window_start = ensure_utc(summary.window_start)
    row.source_window_end = ensure_utc(summary.window_end)
    row.source_window_hours = summary.window_hours
    row.generated_at = generated_at
    row.publish_attempt = int(row.publish_attempt or 0) + 1
    row.status = STATUS_PROVISIONAL

    session.execute(
        delete(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == report_date,
        ),
    )
    session.execute(
        delete(DailyIntelligenceReportFamilyFinding).where(
            DailyIntelligenceReportFamilyFinding.report_date == report_date,
        ),
    )

    for rank, winner in enumerate(result.video_winners, start=1):
        repeat = _winner_had_prior_report(session, winner.video_id, report_date)
        if repeat:
            repeats_w += 1
        prov = discovery_provenance_for_video(session, winner.video_id)
        session.add(
            DailyIntelligenceReportWinnerFinding(
                report_date=report_date,
                video_id=winner.video_id,
                rank=rank,
                title=winner.title or "",
                channel_id=winner.channel_id or "",
                channel_title=winner.channel_title or "",
                youtube_url=winner.youtube_url or "",
                discovery_provenance_json=json.dumps(prov, ensure_ascii=False),
                is_repeat_in_prior_reports=repeat,
                payload_json=json.dumps(video_winner_to_dict(winner), ensure_ascii=False),
            ),
        )

    for rank, family in enumerate(result.families, start=1):
        repeat = _family_had_prior_report(session, family.family_key, report_date)
        if repeat:
            repeats_f += 1
        session.add(
            DailyIntelligenceReportFamilyFinding(
                report_date=report_date,
                family_key=family.family_key,
                rank=rank,
                label=family.label or "",
                video_count=family.video_count,
                channel_count=family.channel_count,
                is_repeat_in_prior_reports=repeat,
                payload_json=json.dumps(pattern_family_to_dict(family), ensure_ascii=False),
            ),
        )

    unique_w = len(result.video_winners)
    unique_f = len(result.families)
    row.summary_json = json.dumps(
        {
            "winner_count": unique_w,
            "family_count": unique_f,
            "unique_winners": unique_w,
            "unique_families": unique_f,
            "repeat_winners_vs_prior_days": repeats_w,
            "repeat_families_vs_prior_days": repeats_f,
            "edition_policy": "latest_publish_within_utc_day",
        },
        ensure_ascii=False,
    )
    row.coverage_gaps_json = json.dumps([], ensure_ascii=False)
    session.flush()


def finalize_eligible_reports(session: Session, *, now: datetime | None = None) -> list[date]:
    """Lock UTC days strictly before today. Idempotent."""
    stamp = ensure_utc(now or utc_now())
    today = stamp.date()
    locked: list[date] = []

    earliest = session.scalar(select(func.min(DailyIntelligenceRunSnapshot.report_date)))
    if earliest is None:
        return locked

    d = earliest
    while d < today:
        _finalize_one_day(session, report_date=d, locked_at=stamp)
        locked.append(d)
        d += timedelta(days=1)
    return locked


def _finalize_one_day(session: Session, *, report_date: date, locked_at: datetime) -> None:
    row = session.get(DailyIntelligenceReport, report_date)
    if row is not None and row.locked_at is not None:
        return

    run_count = int(
        session.scalar(
            select(func.count())
            .select_from(DailyIntelligenceRunSnapshot)
            .where(DailyIntelligenceRunSnapshot.report_date == report_date),
        )
        or 0,
    )

    if run_count == 0:
        if row is None:
            session.add(
                DailyIntelligenceReport(
                    report_date=report_date,
                    status=STATUS_UNAVAILABLE,
                    generated_at=locked_at,
                    locked_at=locked_at,
                    publish_attempt=0,
                    coverage_gaps_json=json.dumps(["no_attention_publish_on_utc_day"]),
                    summary_json=json.dumps({"winner_count": 0, "family_count": 0}),
                ),
            )
        else:
            row.status = STATUS_UNAVAILABLE
            row.locked_at = locked_at
            row.coverage_gaps_json = json.dumps(["no_attention_publish_on_utc_day"])
        session.flush()
        return

    if row is None:
        last_run = session.scalar(
            select(DailyIntelligenceRunSnapshot)
            .where(DailyIntelligenceRunSnapshot.report_date == report_date)
            .order_by(
                DailyIntelligenceRunSnapshot.source_computed_at.desc(),
                DailyIntelligenceRunSnapshot.source_run_id.desc(),
            )
            .limit(1),
        )
        if last_run is None:
            return
        row = DailyIntelligenceReport(
            report_date=report_date,
            status=STATUS_PROVISIONAL,
            source_run_id=last_run.source_run_id,
            source_computed_at=last_run.source_computed_at,
            generated_at=locked_at,
            publish_attempt=0,
        )
        session.add(row)
        session.flush()

    gaps = _coverage_gaps_for_lock(report_date=report_date, source_computed_at=row.source_computed_at)
    row.coverage_gaps_json = json.dumps(gaps, ensure_ascii=False)
    row.status = _status_for_locked_report(gaps=gaps, has_publish=row.source_run_id is not None)
    row.locked_at = locked_at
    session.flush()
