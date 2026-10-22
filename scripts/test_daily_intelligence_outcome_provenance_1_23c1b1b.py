"""Stage 1.23C.1B.1B — temporal provenance hardening tests."""

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
from sqlalchemy import create_engine
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
REPORT_DATE = date(2026, 10, 10)
DISCOVERY = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
EDITION = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(
    session,
    *,
    payload: dict,
    snapshots: list[tuple[datetime, int, str]] | None = None,
) -> None:
    session.add(
        DailyIntelligenceReport(
            report_date=REPORT_DATE,
            status="complete",
            source_run_id="run1",
            source_computed_at=EDITION,
            generated_at=EDITION,
            locked_at=EDITION + timedelta(hours=1),
            publish_attempt=1,
            summary_json="{}",
        ),
    )
    session.add(Channel(id="ch1", title="C", subscribers_count=1, created_at=DISCOVERY))
    session.add(Video(id="v1", channel_id="ch1", title="T", published_at=DISCOVERY, views_count=999_999))
    session.add(TargetKeyword(id=1, keyword="kw", created_at=DISCOVERY))
    prov = {
        "available": True,
        "discovered_at": DISCOVERY.isoformat(),
        "keyword_id": 1,
        "views_at_discovery": 1000,
    }
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_DATE,
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
    session.add(
        DailyIntelligenceRunSnapshot(
            source_run_id="run1",
            report_date=REPORT_DATE,
            source_computed_at=EDITION,
            captured_at=EDITION,
            winner_count=1,
            family_count=0,
        ),
    )
    session.add(
        DailyIntelligenceRunWinnerAppearance(
            source_run_id="run1",
            report_date=REPORT_DATE,
            source_computed_at=EDITION,
            video_id="v1",
            rank=1,
            title="V",
            channel_id="ch1",
            discovery_provenance_json="{}",
            payload_json="{}",
        ),
    )
    for cap, views, source in snapshots or []:
        session.add(
            VideoSnapshot(
                video_id="v1",
                channel_id="ch1",
                captured_at=cap,
                views=views,
                source=source,
                run_id="r",
                fetch_status="ok",
            ),
        )
    session.commit()


def test_candidate_snapshot_matches_but_provenance_unverified() -> None:
    session = _session()
    baseline_at = EDITION - timedelta(hours=2)
    _seed(
        session,
        payload={"video_id": "v1", "views": 5000},
        snapshots=[(baseline_at, 5000, "monitoring")],
    )
    outcome_at = DISCOVERY + timedelta(hours=HORIZON_HOURS, minutes=30)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=outcome_at,
            views=8000,
            source=OUTCOME_CAPTURE_SOURCE,
            run_id="o1",
            fetch_status="ok",
        ),
    )
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    prov = row["attention_views_provenance"]
    assert prov["attention_views_source"] == "frozen_payload_unknown_source"
    assert prov["baseline_provenance_verified"] is False
    assert prov["candidate_baseline_snapshot_at"] == baseline_at.isoformat()
    assert row["comparison_metrics"]["verified_post_signal_growth"] is None


def test_frozen_views_differ_from_latest_snapshot() -> None:
    session = _session()
    _seed(
        session,
        payload={"video_id": "v1", "views": 5000},
        snapshots=[(EDITION - timedelta(hours=1), 7000, "monitoring")],
    )
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["attention_views_provenance"]["candidate_baseline_snapshot_at"] is None


def test_snapshot_after_edition_not_used_as_candidate() -> None:
    session = _session()
    _seed(
        session,
        payload={"video_id": "v1", "views": 5000},
        snapshots=[(EDITION + timedelta(hours=1), 5000, "monitoring")],
    )
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["attention_views_provenance"]["candidate_baseline_snapshot_at"] is None


def test_post_signal_outcome_with_unknown_baseline_time() -> None:
    session = _session()
    _seed(session, payload={"video_id": "v1", "views": 5000})
    outcome_at = DISCOVERY + timedelta(hours=HORIZON_HOURS, minutes=45)
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
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["coverage_category"] == "MEASURED_POST_SIGNAL"
    assert row["comparison_metrics"]["delta_views_descriptive"] == 4000
    assert row["comparison_metrics"]["verified_post_signal_growth"] is None


def test_fallback_unknown_without_reading_video_views_count() -> None:
    session = _session()
    _seed(session, payload={"video_id": "v1", "views": None})
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["attention_views_provenance"]["attention_views_source"] == "fallback_unknown"
    assert row["attention_views_provenance"]["frozen_attention_views"] is None


def test_verified_provenance_when_payload_carries_explicit_fields() -> None:
    session = _session()
    measured_at = EDITION - timedelta(minutes=10)
    _seed(
        session,
        payload={
            "video_id": "v1",
            "views": 5000,
            "views_source_kind": "video_snapshot",
            "views_snapshot_id": 42,
            "views_measured_at": measured_at.isoformat(),
        },
    )
    outcome_at = DISCOVERY + timedelta(hours=HORIZON_HOURS, minutes=30)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=outcome_at,
            views=7000,
            source=OUTCOME_CAPTURE_SOURCE,
            run_id="o1",
            fetch_status="ok",
        ),
    )
    session.commit()
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=DISCOVERY + timedelta(days=30))
    assert row["attention_views_provenance"]["attention_views_source"] == "verified_snapshot"
    assert row["attention_views_provenance"]["baseline_provenance_verified"] is True
    assert row["comparison_metrics"]["verified_post_signal_growth"] == 2000


def test_missing_outcome_descriptive_delta_null() -> None:
    session = _session()
    _seed(session, payload={"video_id": "v1", "views": 1000})
    ref = DISCOVERY + timedelta(hours=HORIZON_HOURS + 13)
    row = get_winner_outcome_followup(session, REPORT_DATE, "v1", reference_now=ref)
    assert row["coverage_category"] == "MATURED_MISSING"
    assert row["comparison_metrics"]["delta_views_descriptive"] is None
