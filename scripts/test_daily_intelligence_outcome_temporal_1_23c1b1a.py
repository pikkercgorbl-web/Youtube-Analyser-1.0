"""Stage 1.23C.1B.1A — temporal evidence edge cases (isolated SQLite)."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models.orm  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

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
from app.services.daily_intelligence_outcome_followup import get_winner_outcome_followup
from app.services.delayed_outcome_capture_config import OUTCOME_CAPTURE_SOURCE
from app.services.keyword_performance_evaluation import HORIZON_HOURS

UTC = timezone.utc
REPORT_A = date(2026, 10, 10)
REPORT_B = date(2026, 10, 11)
DISCOVERY = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
EDITION_A = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)
FIRST_PRIOR_DAY = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)
EDITION_B = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_base(session, *, report_date: date, edition_signal: datetime, run_id: str) -> None:
    session.add(
        DailyIntelligenceReport(
            report_date=report_date,
            status="complete",
            source_run_id=run_id,
            source_computed_at=edition_signal,
            generated_at=edition_signal,
            locked_at=edition_signal + timedelta(hours=1),
            publish_attempt=1,
            summary_json="{}",
        ),
    )
    session.add(Channel(id="ch1", title="C", subscribers_count=1, created_at=DISCOVERY))
    session.add(Video(id="v1", channel_id="ch1", title="T", published_at=DISCOVERY))
    session.add(TargetKeyword(id=1, keyword="kw", created_at=DISCOVERY))
    session.commit()


def _seed_winner(
    session,
    *,
    report_date: date,
    edition_signal: datetime,
    run_id: str,
    payload: dict,
    appearances: list[tuple[str, datetime]],
) -> None:
    _seed_base(session, report_date=report_date, edition_signal=edition_signal, run_id=run_id)
    prov = {
        "available": True,
        "discovered_at": DISCOVERY.isoformat(),
        "keyword_id": 1,
        "views_at_discovery": 1000,
    }
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=report_date,
            video_id="v1",
            rank=1,
            title="V",
            channel_id="ch1",
            discovery_provenance_json=json.dumps(prov),
            payload_json=json.dumps(payload),
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v1",
            channel_id="ch1",
            discovered_at=DISCOVERY,
            views_at_discovery=1000,
            discovery_run_id="d1",
        ),
    )
    for rid, comp_at in appearances:
        session.add(
            DailyIntelligenceRunSnapshot(
                source_run_id=rid,
                report_date=report_date,
                source_computed_at=comp_at,
                captured_at=comp_at,
                winner_count=1,
                family_count=0,
            ),
        )
        session.add(
            DailyIntelligenceRunWinnerAppearance(
                source_run_id=rid,
                report_date=report_date,
                source_computed_at=comp_at,
                video_id="v1",
                rank=1,
                title="V",
                channel_id="ch1",
                discovery_provenance_json="{}",
                payload_json="{}",
            ),
        )
    session.commit()


def test_frozen_views_semantics_not_edition_timestamp_in_payload() -> None:
    """payload.views has no embedded timestamp; follow-up uses edition_signal separately."""
    session = _session()
    _seed_winner(
        session,
        report_date=REPORT_A,
        edition_signal=EDITION_A,
        run_id="run_a",
        payload={"video_id": "v1", "views": 5000},
        appearances=[("run_a", EDITION_A)],
    )
    row = get_winner_outcome_followup(session, REPORT_A, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["signal_timestamps"]["edition_signal_source_computed_at"] == EDITION_A.isoformat()
    assert "views" not in row["comparison_metrics"] or row["comparison_metrics"]["views_at_attention"] == 5000
    assert row["reference_evaluated_at"] != EDITION_A.isoformat()


def test_post_signal_delta_uses_frozen_not_live_snapshot() -> None:
    session = _session()
    _seed_winner(
        session,
        report_date=REPORT_A,
        edition_signal=EDITION_A,
        run_id="run_a",
        payload={"video_id": "v1", "views": 5000},
        appearances=[("run_a", EDITION_A)],
    )
    outcome_at = DISCOVERY + timedelta(hours=HORIZON_HOURS, minutes=30)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=outcome_at,
            views=9000,
            source=OUTCOME_CAPTURE_SOURCE,
            run_id="o1",
            fetch_status="ok",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=EDITION_A + timedelta(hours=1),
            views=7000,
            source="monitoring",
            run_id="m1",
            fetch_status="ok",
        ),
    )
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_A, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["coverage_category"] == "MEASURED_POST_SIGNAL"
    m = row["comparison_metrics"]
    assert m["delta_views_descriptive"] == 4000
    assert m["descriptive_growth_ratio"] == pytest.approx(1.8)
    assert m["verified_post_signal_growth"] is None


def test_first_attention_on_prior_utc_day_preserves_first_signal() -> None:
    session = _session()
    _seed_winner(
        session,
        report_date=REPORT_A,
        edition_signal=EDITION_A,
        run_id="run_late",
        payload={"video_id": "v1", "views": 4000},
        appearances=[("run_early", FIRST_PRIOR_DAY), ("run_late", EDITION_A)],
    )
    row = get_winner_outcome_followup(session, REPORT_A, "v1", reference_now=DISCOVERY + timedelta(days=30))
    sig = row["signal_timestamps"]
    assert sig["first_signal_source_computed_at"] == FIRST_PRIOR_DAY.isoformat()
    assert sig["edition_signal_source_computed_at"] == EDITION_A.isoformat()
    assert sig["appearance_count_on_report_date"] == 2


def test_same_video_two_reports_independent_pre_post() -> None:
    session = _session()
    early_discovery = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    _seed_winner(
        session,
        report_date=REPORT_A,
        edition_signal=EDITION_A,
        run_id="run_a",
        payload={"video_id": "v1", "views": 3000},
        appearances=[("run_a", EDITION_A)],
    )
    finding = session.scalar(
        select(DailyIntelligenceReportWinnerFinding).where(
            DailyIntelligenceReportWinnerFinding.report_date == REPORT_A,
        ),
    )
    assert finding is not None
    finding.discovery_provenance_json = json.dumps(
        {
            "available": True,
            "discovered_at": early_discovery.isoformat(),
            "keyword_id": 1,
            "views_at_discovery": 1000,
        },
    )
    session.commit()
    outcome_pre = early_discovery + timedelta(hours=HORIZON_HOURS)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=outcome_pre,
            views=6000,
            source=OUTCOME_CAPTURE_SOURCE,
            run_id="o1",
            fetch_status="ok",
        ),
    )
    session.commit()
    row_a = get_winner_outcome_followup(session, REPORT_A, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row_a["coverage_category"] == "MEASURED_PRE_SIGNAL"

    session.add(
        DailyIntelligenceReport(
            report_date=REPORT_B,
            status="complete",
            source_run_id="run_b",
            source_computed_at=EDITION_B,
            generated_at=EDITION_B,
            locked_at=EDITION_B + timedelta(hours=1),
            publish_attempt=1,
            summary_json="{}",
        ),
    )
    prov = {
        "available": True,
        "discovered_at": DISCOVERY.isoformat(),
        "keyword_id": 1,
        "views_at_discovery": 1000,
    }
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_B,
            video_id="v1",
            rank=1,
            title="V",
            channel_id="ch1",
            discovery_provenance_json=json.dumps(prov),
            payload_json=json.dumps({"video_id": "v1", "views": 8000}),
        ),
    )
    session.add(
        DailyIntelligenceRunSnapshot(
            source_run_id="run_b",
            report_date=REPORT_B,
            source_computed_at=EDITION_B,
            captured_at=EDITION_B,
            winner_count=1,
            family_count=0,
        ),
    )
    session.add(
        DailyIntelligenceRunWinnerAppearance(
            source_run_id="run_b",
            report_date=REPORT_B,
            source_computed_at=EDITION_B,
            video_id="v1",
            rank=1,
            title="V",
            channel_id="ch1",
            discovery_provenance_json="{}",
            payload_json="{}",
        ),
    )
    outcome_post = EDITION_B + timedelta(hours=1)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=outcome_post,
            views=12000,
            source=OUTCOME_CAPTURE_SOURCE,
            run_id="o2",
            fetch_status="ok",
        ),
    )
    session.commit()
    row_b = get_winner_outcome_followup(session, REPORT_B, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row_b["coverage_category"] == "MEASURED_POST_SIGNAL"
    assert row_b["comparison_metrics"]["delta_views_descriptive"] == 4000
    assert row_b["comparison_metrics"]["verified_post_signal_growth"] is None


def test_reference_evaluated_at_is_recompute_moment_not_measurement() -> None:
    session = _session()
    _seed_winner(
        session,
        report_date=REPORT_A,
        edition_signal=EDITION_A,
        run_id="run_a",
        payload={"video_id": "v1", "views": 1000},
        appearances=[("run_a", EDITION_A)],
    )
    ref = datetime(2026, 12, 1, 0, 0, tzinfo=UTC)
    row = get_winner_outcome_followup(session, REPORT_A, "v1", reference_now=ref)
    assert row["reference_evaluated_at"] == ref.isoformat()
    assert row["reference_evaluated_at"] != row["signal_timestamps"]["edition_signal_source_computed_at"]
