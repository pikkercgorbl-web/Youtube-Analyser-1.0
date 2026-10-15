"""Read models for daily intelligence API (Stage 1.23A)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import (
    DailyIntelligenceReport,
    DailyIntelligenceReportFamilyFinding,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunFamilyAppearance,
    DailyIntelligenceRunWinnerAppearance,
    DailyIntelligenceRunSnapshot,
)


def _json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except json.JSONDecodeError:
        return default


def list_report_dates(
    session: Session,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    total = int(session.scalar(select(func.count()).select_from(DailyIntelligenceReport)) or 0)
    rows = list(
        session.scalars(
            select(DailyIntelligenceReport)
            .order_by(DailyIntelligenceReport.report_date.desc())
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    items = [_report_summary_row(r) for r in rows]
    return items, total


def get_report_summary(session: Session, report_date: date) -> dict[str, Any] | None:
    row = session.get(DailyIntelligenceReport, report_date)
    if row is None:
        return None
    out = _report_summary_row(row)
    out["coverage_gaps"] = _json_loads(row.coverage_gaps_json, [])
    out["summary"] = _json_loads(row.summary_json, {})
    return out


def _report_summary_row(row: DailyIntelligenceReport) -> dict[str, Any]:
    summary = _json_loads(row.summary_json, {})
    return {
        "report_date": row.report_date.isoformat(),
        "status": row.status,
        "source_run_id": row.source_run_id,
        "source_computed_at": row.source_computed_at.isoformat() if row.source_computed_at else None,
        "source_window_start": row.source_window_start.isoformat() if row.source_window_start else None,
        "source_window_end": row.source_window_end.isoformat() if row.source_window_end else None,
        "source_window_hours": row.source_window_hours,
        "generated_at": row.generated_at.isoformat(),
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
        "publish_attempt": row.publish_attempt,
        "winner_count": summary.get("winner_count"),
        "family_count": summary.get("family_count"),
    }


def list_report_winners(
    session: Session,
    report_date: date,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = (DailyIntelligenceReportWinnerFinding.report_date == report_date,)
    total = int(
        session.scalar(select(func.count()).select_from(DailyIntelligenceReportWinnerFinding).where(*filters)) or 0,
    )
    rows = list(
        session.scalars(
            select(DailyIntelligenceReportWinnerFinding)
            .where(*filters)
            .order_by(DailyIntelligenceReportWinnerFinding.rank.asc())
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    return [_winner_list_item(r) for r in rows], total


def get_report_winner(
    session: Session,
    report_date: date,
    video_id: str,
) -> dict[str, Any] | None:
    row = session.scalar(
        select(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == report_date,
            DailyIntelligenceReportWinnerFinding.video_id == video_id,
        ),
    )
    if row is None:
        return None
    return _winner_detail(row)


def list_report_families(
    session: Session,
    report_date: date,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = (DailyIntelligenceReportFamilyFinding.report_date == report_date,)
    total = int(
        session.scalar(select(func.count()).select_from(DailyIntelligenceReportFamilyFinding).where(*filters)) or 0,
    )
    rows = list(
        session.scalars(
            select(DailyIntelligenceReportFamilyFinding)
            .where(*filters)
            .order_by(DailyIntelligenceReportFamilyFinding.rank.asc())
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    return [_family_list_item(r) for r in rows], total


def get_report_family(
    session: Session,
    report_date: date,
    family_key: str,
) -> dict[str, Any] | None:
    row = session.scalar(
        select(DailyIntelligenceReportFamilyFinding).where(
            DailyIntelligenceReportFamilyFinding.report_date == report_date,
            DailyIntelligenceReportFamilyFinding.family_key == family_key,
        ),
    )
    if row is None:
        return None
    return _family_detail(row)


def list_video_appearances(
    session: Session,
    video_id: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = (DailyIntelligenceRunWinnerAppearance.video_id == video_id,)
    total = int(
        session.scalar(select(func.count()).select_from(DailyIntelligenceRunWinnerAppearance).where(*filters)) or 0,
    )
    rows = list(
        session.scalars(
            select(DailyIntelligenceRunWinnerAppearance)
            .where(*filters)
            .order_by(
                DailyIntelligenceRunWinnerAppearance.source_computed_at.desc(),
                DailyIntelligenceRunWinnerAppearance.id.desc(),
            )
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    return [_appearance_list_item(r) for r in rows], total


def _winner_list_item(row: DailyIntelligenceReportWinnerFinding) -> dict[str, Any]:
    return {
        "video_id": row.video_id,
        "rank": row.rank,
        "title": row.title,
        "channel_id": row.channel_id,
        "channel_title": row.channel_title,
        "youtube_url": row.youtube_url,
        "is_repeat_in_prior_reports": row.is_repeat_in_prior_reports,
        "discovery_provenance_available": _json_loads(row.discovery_provenance_json, {}).get("available"),
    }


def _winner_detail(row: DailyIntelligenceReportWinnerFinding) -> dict[str, Any]:
    out = _winner_list_item(row)
    out["discovery_provenance"] = _json_loads(row.discovery_provenance_json, {})
    out["evidence"] = _json_loads(row.payload_json, {})
    return out


def _family_list_item(row: DailyIntelligenceReportFamilyFinding) -> dict[str, Any]:
    return {
        "family_key": row.family_key,
        "rank": row.rank,
        "label": row.label,
        "video_count": row.video_count,
        "channel_count": row.channel_count,
        "is_repeat_in_prior_reports": row.is_repeat_in_prior_reports,
    }


def _family_detail(row: DailyIntelligenceReportFamilyFinding) -> dict[str, Any]:
    out = _family_list_item(row)
    out["evidence"] = _json_loads(row.payload_json, {})
    return out


def _appearance_list_item(row: DailyIntelligenceRunWinnerAppearance) -> dict[str, Any]:
    return {
        "source_run_id": row.source_run_id,
        "report_date": row.report_date.isoformat(),
        "source_computed_at": row.source_computed_at.isoformat(),
        "rank": row.rank,
        "video_id": row.video_id,
        "title": row.title,
        "discovery_provenance": _json_loads(row.discovery_provenance_json, {}),
    }


def list_run_snapshots(
    session: Session,
    report_date: date,
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = (DailyIntelligenceRunSnapshot.report_date == report_date,)
    total = int(session.scalar(select(func.count()).select_from(DailyIntelligenceRunSnapshot).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(DailyIntelligenceRunSnapshot)
            .where(*filters)
            .order_by(DailyIntelligenceRunSnapshot.source_computed_at.asc())
            .offset(offset)
            .limit(limit),
        ).all(),
    )
    return [
        {
            "source_run_id": r.source_run_id,
            "source_computed_at": r.source_computed_at.isoformat(),
            "captured_at": r.captured_at.isoformat(),
            "winner_count": r.winner_count,
            "family_count": r.family_count,
        }
        for r in rows
    ], total
