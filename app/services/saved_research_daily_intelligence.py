"""Save-to-research from Daily Intelligence frozen findings (Stage 1.23B.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import (
    DailyIntelligenceReport,
    DailyIntelligenceReportFamilyFinding,
    DailyIntelligenceReportWinnerFinding,
    SavedFamily,
    SavedFamilyObservation,
    SavedResearchStatus,
    SavedVideo,
    SavedVideoObservation,
    Video,
)
from app.services.metrics import ensure_utc, utc_now
from app.services.saved_research import (
    SavedFamilySaveResult,
    SavedResearchArchivedError,
    SavedVideoNotFoundError,
    SavedVideoSaveResult,
    _apply_family_observation_row,
    _apply_video_observation_row,
    get_saved_family_by_family_key,
    get_saved_video_by_video_id,
)
from app.services.saved_research_decisions import record_family_saved, record_video_saved

DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND = "daily_intelligence_save_anchor"


class DailyIntelligenceFindingNotFoundError(Exception):
    pass


class DailyIntelligenceReportNotFoundError(Exception):
    pass


def _json_loads(text: str, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except json.JSONDecodeError:
        return default


def build_decision_source(
    *,
    report: DailyIntelligenceReport,
    rank: int,
    entity_key: str,
    entity_kind: str,
    selected_at: datetime,
) -> dict[str, Any]:
    computed = report.source_computed_at
    out: dict[str, Any] = {
        "kind": "daily_intelligence",
        "report_date": report.report_date.isoformat(),
        "source_run_id": report.source_run_id,
        "source_computed_at": ensure_utc(computed).isoformat() if computed else None,
        "report_status_at_save": report.status,
        "rank_at_save": rank,
        "selected_at": ensure_utc(selected_at).isoformat(),
    }
    if entity_kind == "video":
        out["video_id"] = entity_key
    else:
        out["family_key"] = entity_key
    return out


def winner_finding_to_frozen_payload(
    *,
    report: DailyIntelligenceReport,
    finding: DailyIntelligenceReportWinnerFinding,
    discovery_provenance: dict[str, Any],
    evidence: dict[str, Any],
    selected_at: datetime,
) -> dict[str, Any]:
    source_run = report.source_run_id
    computed = report.source_computed_at
    decision_source = build_decision_source(
        report=report,
        rank=finding.rank,
        entity_key=finding.video_id,
        entity_kind="video",
        selected_at=selected_at,
    )
    identity = {
        "video_id": finding.video_id,
        "title": finding.title or evidence.get("title") or "",
        "channel_id": finding.channel_id or evidence.get("channel_id") or "",
        "channel_title": finding.channel_title or evidence.get("channel_title") or "",
        "youtube_url": finding.youtube_url or evidence.get("youtube_url") or "",
    }
    return {
        "identity": identity,
        "evidence": evidence,
        "context": {
            "discovery_provenance": discovery_provenance,
            "keyword_ids": list(evidence.get("keyword_ids") or []),
            "pattern_memberships": [],
            "family_memberships": [],
            "decision_source": decision_source,
            "provenance_note": (
                "Frozen evidence from Daily Intelligence daily edition at save time; "
                "not refreshed from live Attention."
            ),
        },
        "attention_run_id": source_run,
        "attention_computed_at": ensure_utc(computed).isoformat() if computed else None,
    }


def family_finding_to_frozen_payload(
    *,
    report: DailyIntelligenceReport,
    finding: DailyIntelligenceReportFamilyFinding,
    evidence: dict[str, Any],
    selected_at: datetime,
) -> dict[str, Any]:
    source_run = report.source_run_id
    computed = report.source_computed_at
    decision_source = build_decision_source(
        report=report,
        rank=finding.rank,
        entity_key=finding.family_key,
        entity_kind="family",
        selected_at=selected_at,
    )
    family_dict = dict(evidence)
    if "label" not in family_dict and finding.label:
        family_dict["label"] = finding.label
    if "family_key" not in family_dict:
        family_dict["family_key"] = finding.family_key
    return {
        "attention_run_id": source_run,
        "attention_computed_at": ensure_utc(computed).isoformat() if computed else None,
        "family": family_dict,
        "member_patterns": [],
        "video_ids": list(family_dict.get("video_ids") or []),
        "keyword_ids": list(family_dict.get("keyword_ids") or []),
        "breakout_video_evidence": [],
        "member_pattern_breakout": {},
        "context": {
            "decision_source": decision_source,
            "provenance_note": (
                "Frozen family payload from Daily Intelligence daily edition at save time."
            ),
        },
    }


def build_video_anchor_observation_payload(
    *,
    report: DailyIntelligenceReport,
    evidence: dict[str, Any],
    decision_source: dict[str, Any],
) -> dict[str, Any]:
    source_run = report.source_run_id or ""
    computed = report.source_computed_at
    return {
        "observation_kind": DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
        "present_in_snapshot": False,
        "present_in_daily_intelligence_edition": True,
        "video_present_in_attention": False,
        "absence_message": None,
        "monitoring_snapshot_available": False,
        "attention_run_id": source_run,
        "attention_computed_at": ensure_utc(computed).isoformat() if computed else None,
        "decision_source": decision_source,
        "family_memberships": [],
        "winner": evidence,
        "views": evidence.get("views"),
        "vph": evidence.get("vph"),
        "subscriber_count": evidence.get("subscribers"),
        "breakout_rank": evidence.get("breakout_rank"),
        "acceleration_state": evidence.get("acceleration_state"),
        "reason_codes": list(evidence.get("reason_codes") or []),
        "historical_delayed_outcome_state_at_save": evidence.get("delayed_outcome_state"),
        "note": "Historical anchor from Daily Intelligence; not a live Attention measurement.",
    }


def build_family_anchor_observation_payload(
    *,
    report: DailyIntelligenceReport,
    family_dict: dict[str, Any],
    decision_source: dict[str, Any],
) -> dict[str, Any]:
    source_run = report.source_run_id or ""
    computed = report.source_computed_at
    return {
        "observation_kind": DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
        "present_in_snapshot": False,
        "present_in_daily_intelligence_edition": True,
        "absence_message": None,
        "attention_run_id": source_run,
        "attention_computed_at": ensure_utc(computed).isoformat() if computed else None,
        "decision_source": decision_source,
        "counts": {
            "video_count": family_dict.get("video_count"),
            "channel_count": family_dict.get("channel_count"),
            "keyword_count": family_dict.get("keyword_count"),
            "breakout_eligible_count": family_dict.get("breakout_eligible_count"),
            "videos_last_24h": family_dict.get("videos_last_24h"),
            "videos_previous_24h": family_dict.get("videos_previous_24h"),
            "videos_previous_48_24h": family_dict.get("videos_previous_48_24h"),
        },
        "family": family_dict,
        "note": "Historical anchor from Daily Intelligence; not a live Attention snapshot.",
    }


def _load_winner_finding(
    session: Session,
    report_date: date,
    video_id: str,
) -> tuple[DailyIntelligenceReport, DailyIntelligenceReportWinnerFinding]:
    report = session.get(DailyIntelligenceReport, report_date)
    if report is None:
        raise DailyIntelligenceReportNotFoundError(f"Report {report_date.isoformat()} not found")
    finding = session.scalar(
        select(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == report_date,
            DailyIntelligenceReportWinnerFinding.video_id == video_id,
        ),
    )
    if finding is None:
        raise DailyIntelligenceFindingNotFoundError(
            f"Winner {video_id!r} not found in report {report_date.isoformat()}",
        )
    return report, finding


def _load_family_finding(
    session: Session,
    report_date: date,
    family_key: str,
) -> tuple[DailyIntelligenceReport, DailyIntelligenceReportFamilyFinding]:
    report = session.get(DailyIntelligenceReport, report_date)
    if report is None:
        raise DailyIntelligenceReportNotFoundError(f"Report {report_date.isoformat()} not found")
    finding = session.scalar(
        select(DailyIntelligenceReportFamilyFinding).where(
            DailyIntelligenceReportFamilyFinding.report_date == report_date,
            DailyIntelligenceReportFamilyFinding.family_key == family_key,
        ),
    )
    if finding is None:
        raise DailyIntelligenceFindingNotFoundError(
            f"Family {family_key!r} not found in report {report_date.isoformat()}",
        )
    return report, finding


def _anchor_observed_at(report: DailyIntelligenceReport) -> datetime:
    if report.source_computed_at is not None:
        return ensure_utc(report.source_computed_at)
    return ensure_utc(report.generated_at)


def save_video_from_daily_intelligence(
    session: Session,
    *,
    report_date: date,
    video_id: str,
) -> SavedVideoSaveResult:
    video = session.get(Video, video_id)
    if video is None:
        raise SavedVideoNotFoundError(f"Video {video_id!r} not found in canonical corpus")

    existing = get_saved_video_by_video_id(session, video_id)
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved video {video_id!r} is archived; restore before saving again",
            )
        return SavedVideoSaveResult(item=existing, created=False, idempotent=True)

    report, finding = _load_winner_finding(session, report_date, video_id)
    evidence = _json_loads(finding.payload_json, {})
    discovery_provenance = _json_loads(finding.discovery_provenance_json, {})
    now = utc_now()
    frozen_payload = winner_finding_to_frozen_payload(
        report=report,
        finding=finding,
        discovery_provenance=discovery_provenance,
        evidence=evidence,
        selected_at=now,
    )
    identity = frozen_payload["identity"]
    source_run = report.source_run_id
    row = SavedVideo(
        video_id=video_id,
        saved_at=now,
        status=SavedResearchStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        created_from_attention_run_id=source_run,
        frozen_title=str(identity["title"]),
        frozen_channel_id=str(identity["channel_id"]),
        frozen_channel_title=str(identity["channel_title"]),
        frozen_payload_json=json.dumps(frozen_payload, ensure_ascii=False),
        latest_observed_at=_anchor_observed_at(report),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = get_saved_video_by_video_id(session, video_id)
        if existing is None:
            raise
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved video {video_id!r} is archived; restore before saving again",
            )
        return SavedVideoSaveResult(item=existing, created=False, idempotent=True)

    decision_source = frozen_payload["context"]["decision_source"]
    anchor_payload = build_video_anchor_observation_payload(
        report=report,
        evidence=evidence,
        decision_source=decision_source,
    )
    obs = _apply_video_observation_row(
        saved_video_id=row.id,
        run_id=source_run or f"di:{report.report_date.isoformat()}",
        observed_at=_anchor_observed_at(report),
        payload=anchor_payload,
    )
    session.add(obs)
    row.latest_observed_at = obs.observed_at
    record_video_saved(session, row)
    session.flush()
    return SavedVideoSaveResult(item=row, created=True, idempotent=False)


def save_family_from_daily_intelligence(
    session: Session,
    *,
    report_date: date,
    family_key: str,
) -> SavedFamilySaveResult:
    existing = get_saved_family_by_family_key(session, family_key)
    if existing is not None:
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved family {family_key!r} is archived; restore before saving again",
            )
        return SavedFamilySaveResult(item=existing, created=False, idempotent=True)

    report, finding = _load_family_finding(session, report_date, family_key)
    evidence = _json_loads(finding.payload_json, {})
    now = utc_now()
    frozen_payload = family_finding_to_frozen_payload(
        report=report,
        finding=finding,
        evidence=evidence,
        selected_at=now,
    )
    family_dict = frozen_payload["family"]
    source_run = report.source_run_id
    row = SavedFamily(
        family_key=family_key,
        saved_at=now,
        status=SavedResearchStatus.WATCHING.value,
        notes="",
        tags_json="[]",
        created_from_attention_run_id=source_run,
        frozen_label=str(finding.label or family_dict.get("label") or family_key),
        frozen_kind=str(family_dict.get("family_kind") or ""),
        frozen_payload_json=json.dumps(frozen_payload, ensure_ascii=False),
        latest_observed_at=_anchor_observed_at(report),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        session.rollback()
        existing = get_saved_family_by_family_key(session, family_key)
        if existing is None:
            raise
        if existing.archived_at is not None:
            raise SavedResearchArchivedError(
                f"Saved family {family_key!r} is archived; restore before saving again",
            )
        return SavedFamilySaveResult(item=existing, created=False, idempotent=True)

    decision_source = frozen_payload["context"]["decision_source"]
    anchor_payload = build_family_anchor_observation_payload(
        report=report,
        family_dict=family_dict,
        decision_source=decision_source,
    )
    obs = _apply_family_observation_row(
        saved_family_id=row.id,
        run_id=source_run or f"di:{report.report_date.isoformat()}",
        observed_at=_anchor_observed_at(report),
        payload=anchor_payload,
    )
    session.add(obs)
    row.latest_observed_at = obs.observed_at
    record_family_saved(session, row)
    session.flush()
    return SavedFamilySaveResult(item=row, created=True, idempotent=False)
