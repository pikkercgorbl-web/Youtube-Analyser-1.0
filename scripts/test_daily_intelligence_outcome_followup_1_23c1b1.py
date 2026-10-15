"""Stage 1.23C.1B.1 — historical DI outcome follow-up (isolated SQLite)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    Channel,
    DailyIntelligenceReport,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunSnapshot,
    DailyIntelligenceRunWinnerAppearance,
    KeywordDiscoveryHit,
    TargetKeyword,
    Video,
    VideoSnapshot,
)
from app.services.daily_intelligence_outcome_followup import (
    get_report_outcome_coverage,
    get_winner_outcome_followup,
)
from app.services.delayed_outcome_capture_config import OUTCOME_CAPTURE_SOURCE
from app.services.keyword_performance_evaluation import HORIZON_HOURS, HORIZON_SNAPSHOT_TOLERANCE_HOURS

UTC = timezone.utc
REPORT_DATE = date(2026, 10, 10)
DISCOVERY_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
EDITION_SIGNAL = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)
FIRST_SIGNAL = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
RUN_ID = "att_run_1"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_report(session, *, source_computed_at: datetime = EDITION_SIGNAL) -> None:
    session.add(
        DailyIntelligenceReport(
            report_date=REPORT_DATE,
            status="complete",
            source_run_id=RUN_ID,
            source_computed_at=source_computed_at,
            generated_at=source_computed_at,
            locked_at=source_computed_at + timedelta(hours=1),
            publish_attempt=1,
            summary_json='{"winner_count":1}',
        ),
    )
    session.add(
        DailyIntelligenceRunSnapshot(
            source_run_id=RUN_ID,
            report_date=REPORT_DATE,
            source_computed_at=FIRST_SIGNAL,
            captured_at=FIRST_SIGNAL,
            winner_count=1,
            family_count=0,
        ),
    )
    session.add(
        DailyIntelligenceRunSnapshot(
            source_run_id=f"{RUN_ID}_late",
            report_date=REPORT_DATE,
            source_computed_at=EDITION_SIGNAL,
            captured_at=EDITION_SIGNAL,
            winner_count=1,
            family_count=0,
        ),
    )
    session.flush()


def _seed_video_graph(session) -> None:
    session.add(Channel(id="ch1", title="C", subscribers_count=100, created_at=DISCOVERY_AT))
    session.add(Video(id="v1", channel_id="ch1", title="T", published_at=DISCOVERY_AT))
    session.add(TargetKeyword(id=1, keyword="kw", created_at=DISCOVERY_AT))
    session.flush()


def _seed_finding(
    session,
    *,
    provenance: dict,
    payload: dict,
) -> None:
    _seed_report(session)
    _seed_video_graph(session)
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_DATE,
            video_id="v1",
            rank=1,
            title="Video",
            channel_id="ch1",
            discovery_provenance_json=json.dumps(provenance),
            payload_json=json.dumps(payload),
        ),
    )
    session.add(
        DailyIntelligenceRunWinnerAppearance(
            source_run_id=RUN_ID,
            report_date=REPORT_DATE,
            source_computed_at=FIRST_SIGNAL,
            video_id="v1",
            rank=1,
            title="Video",
            channel_id="ch1",
            discovery_provenance_json="{}",
            payload_json="{}",
        ),
    )
    session.add(
        DailyIntelligenceRunWinnerAppearance(
            source_run_id=f"{RUN_ID}_late",
            report_date=REPORT_DATE,
            source_computed_at=EDITION_SIGNAL,
            video_id="v1",
            rank=1,
            title="Video",
            channel_id="ch1",
            discovery_provenance_json="{}",
            payload_json="{}",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="ch1",
            discovered_at=DISCOVERY_AT,
            views_at_discovery=1000,
            vph_at_discovery=10.0,
            discovery_run_id="dr1",
        ),
    )
    session.commit()


def _good_provenance() -> dict:
    return {
        "available": True,
        "discovered_at": DISCOVERY_AT.isoformat(),
        "keyword_id": 1,
        "views_at_discovery": 1000,
        "vph_at_discovery": 10.0,
    }


def _good_payload(*, views: int = 5000, delayed_state: str = "pending", growth: int | None = None) -> dict:
    return {
        "video_id": "v1",
        "views": views,
        "delayed_outcome_state": delayed_state,
        "delayed_outcome_growth": growth,
    }


def _add_snapshot(session, *, captured_at: datetime, views: int, source: str = OUTCOME_CAPTURE_SOURCE) -> None:
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=captured_at,
            views=views,
            source=source,
            run_id="snap_run",
            fetch_status="ok",
        ),
    )
    session.commit()


def test_not_matured_before_outcome_window() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    ref = DISCOVERY_AT + timedelta(hours=HORIZON_HOURS - 24)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row is not None
    assert row["coverage_category"] == "NOT_MATURED"
    assert row["outcome_window_phase"] == "not_yet_open"


def test_open_window_awaiting_measurement() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    ref = DISCOVERY_AT + timedelta(hours=HORIZON_HOURS + 2)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row["coverage_category"] == "NOT_MATURED"
    assert row["outcome_window_phase"] == "open_awaiting_measurement"


def test_measured_post_signal_with_metrics() -> None:
    session = _session()
    late_discovery = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    prov = _good_provenance()
    prov["discovered_at"] = late_discovery.isoformat()
    _seed_finding(session, provenance=prov, payload=_good_payload(views=5000))
    session.execute(
        __import__("sqlalchemy").update(KeywordDiscoveryHit)
        .where(KeywordDiscoveryHit.video_id == "v1")
        .values(discovered_at=late_discovery),
    )
    session.commit()
    outcome_capture_at = late_discovery + timedelta(hours=HORIZON_HOURS, minutes=60)
    _add_snapshot(session, captured_at=outcome_capture_at, views=8000)
    ref = late_discovery + timedelta(days=30)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row["coverage_category"] == "MEASURED_POST_SIGNAL"
    m = row["comparison_metrics"]
    assert m["views_at_attention_frozen"] == 5000
    assert m["views_at_outcome_horizon"] == 8000
    assert m["delta_views_descriptive"] == 3000
    assert m["descriptive_growth_ratio"] == pytest.approx(1.6)
    assert m["verified_post_signal_growth"] is None
    assert row["metrics_interpretation"] == "verified_post_signal_growth_unavailable"
    assert m["elapsed_hours_edition_signal_to_outcome"] == pytest.approx(19.0)


def test_measured_pre_signal() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    target = DISCOVERY_AT + timedelta(hours=HORIZON_HOURS)
    _add_snapshot(session, captured_at=target, views=7000)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=target + timedelta(days=10))
    assert row["coverage_category"] == "MEASURED_PRE_SIGNAL"
    assert row["comparison_metrics"]["metrics_reason"] == "outcome_snapshot_before_edition_signal"


def test_matured_missing_after_window_end() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    ref = DISCOVERY_AT + timedelta(hours=HORIZON_HOURS + HORIZON_SNAPSHOT_TOLERANCE_HOURS + 1)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row["coverage_category"] == "MATURED_MISSING"


def test_invalid_timeline_discovery_after_signal() -> None:
    session = _session()
    prov = _good_provenance()
    prov["discovered_at"] = (EDITION_SIGNAL + timedelta(hours=1)).isoformat()
    _seed_finding(session, provenance=prov, payload=_good_payload())
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=EDITION_SIGNAL + timedelta(days=20))
    assert row["coverage_category"] == "INVALID_TIMELINE"


def test_insufficient_evidence_no_provenance() -> None:
    session = _session()
    _seed_finding(
        session,
        provenance={"available": False, "reason": "no_discovery_hits"},
        payload=_good_payload(),
    )
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY_AT + timedelta(days=30))
    assert row["coverage_category"] == "INSUFFICIENT_EVIDENCE"


def test_missing_attention_baseline_blocks_growth_ratio() -> None:
    session = _session()
    late_discovery = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    prov = _good_provenance()
    prov["discovered_at"] = late_discovery.isoformat()
    _seed_finding(session, provenance=prov, payload={"video_id": "v1", "views": None})
    _add_snapshot(
        session,
        captured_at=late_discovery + timedelta(hours=HORIZON_HOURS, minutes=30),
        views=9000,
    )
    row = get_winner_outcome_followup(
        session,
        REPORT_DATE,
        "v1",
        reference_now=late_discovery + timedelta(days=30),
    )
    assert row["coverage_category"] == "MEASURED_POST_SIGNAL"
    assert row["comparison_metrics"]["metrics_reason"] == "missing_frozen_attention_views"


def test_repeated_run_appearances_exposed() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY_AT + timedelta(days=30))
    sig = row["signal_timestamps"]
    assert sig["appearance_count_on_report_date"] == 2
    assert len(sig["appearance_source_computed_at"]) == 2
    assert sig["first_signal_source_computed_at"] == FIRST_SIGNAL.isoformat()
    assert sig["edition_signal_source_computed_at"] == EDITION_SIGNAL.isoformat()


def test_coverage_aggregate_batch() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    cov = get_report_outcome_coverage(session, REPORT_DATE, reference_now=DISCOVERY_AT + timedelta(days=30))
    assert cov is not None
    assert cov["winner_count"] == 1
    assert "MATURED_MISSING" in cov["coverage_counts"]


def test_frozen_payload_unchanged_and_no_writes() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload(delayed_state="pending", growth=None))
    before = session.scalar(
        select(DailyIntelligenceReportWinnerFinding.payload_json).where(
            DailyIntelligenceReportWinnerFinding.video_id == "v1",
        ),
    )
    counts_before = {
        "findings": session.scalar(select(func.count()).select_from(DailyIntelligenceReportWinnerFinding)),
        "snapshots": session.scalar(select(func.count()).select_from(VideoSnapshot)),
    }
    _ = get_report_outcome_coverage(session, REPORT_DATE, reference_now=DISCOVERY_AT + timedelta(days=30))
    _ = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY_AT + timedelta(days=30))
    after = session.scalar(
        select(DailyIntelligenceReportWinnerFinding.payload_json).where(
            DailyIntelligenceReportWinnerFinding.video_id == "v1",
        ),
    )
    counts_after = {
        "findings": session.scalar(select(func.count()).select_from(DailyIntelligenceReportWinnerFinding)),
        "snapshots": session.scalar(select(func.count()).select_from(VideoSnapshot)),
    }
    assert before == after
    assert counts_before == counts_after
    payload = json.loads(after or "{}")
    assert payload["delayed_outcome_state"] == "pending"


def test_missing_snapshot_not_zero_growth() -> None:
    session = _session()
    _seed_finding(session, provenance=_good_provenance(), payload=_good_payload())
    ref = DISCOVERY_AT + timedelta(hours=HORIZON_HOURS + HORIZON_SNAPSHOT_TOLERANCE_HOURS + 5)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row["coverage_category"] == "MATURED_MISSING"
    assert row["comparison_metrics"]["delta_views_descriptive"] is None
    assert row["outcome_measurement"]["absolute_view_growth_from_discovery"] is None
