"""Stage 1.23A — daily intelligence capture, finalize, API tests."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import daily_intelligence as daily_intelligence_routes
from app.models.db import Base, get_db
from app.models.orm import (
    DailyIntelligenceReport,
    DailyIntelligenceReportWinnerFinding,
    DailyIntelligenceRunSnapshot,
    DailyIntelligenceRunWinnerAppearance,
    KeywordDiscoveryHit,
    TargetKeyword,
)
from app.services.attention_engine_types import (
    AttentionEngineConfig,
    AttentionEngineResult,
    AttentionSummary,
    PatternFamily,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_read_model import persist_attention_result
from app.services.daily_intelligence_capture import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    STATUS_PROVISIONAL,
    STATUS_UNAVAILABLE,
    capture_daily_intelligence_for_publish,
    finalize_eligible_reports,
    utc_report_date,
)
UTC = timezone.utc
T0 = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _summary(*, run_id: str, computed_at: datetime) -> AttentionSummary:
    cfg = AttentionEngineConfig()
    ws = computed_at - timedelta(hours=cfg.window_hours)
    return AttentionSummary(
        run_id=run_id,
        computed_at=computed_at,
        timezone_name="UTC",
        window_hours=cfg.window_hours,
        window_start=ws,
        window_end=computed_at,
        source="snapshot",
        candidate_video_count=2,
        winner_count=1,
        pattern_count=0,
        channel_momentum_count=0,
        video_limit=50,
        pattern_limit=20,
        channel_limit=20,
        notes={},
    )


def _winner(video_id: str = "vid-a", *, vph: float = 100.0) -> VideoWinner:
    return VideoWinner(
        video_id=video_id,
        title=f"Title {video_id}",
        channel_id="ch-a",
        channel_title="Channel",
        youtube_url=youtube_watch_url(video_id),
        published_at=T0 - timedelta(hours=12),
        age_hours=12.0,
        views=1000,
        vph=vph,
        subscribers=500,
        breakout_rank=1,
        breakout_eligible=True,
        channel_relative_signal=None,
        acceleration_state="stable",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("breakout_high_rank",),
        human_reasons=("rank 1",),
        keyword_ids=(1,),
    )


def _family(key: str = "family:test:one") -> PatternFamily:
    return PatternFamily(
        family_key=key,
        label="Test family",
        family_kind="title_phrase",
        member_pattern_keys=("phrase:x",),
        member_labels=("x",),
        video_ids=("vid-a",),
        channel_ids=("ch-a",),
        keyword_ids=(1,),
        video_count=1,
        channel_count=1,
        keyword_count=1,
        breakout_eligible_count=1,
        videos_last_24h=1,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        grouping_reasons=("shared_video_membership",),
        quality_flags=(),
        support_sources=("phrase_supported",),
        first_seen_at=T0,
        latest_seen_at=T0,
    )


def _result(*, run_id: str, computed_at: datetime, winners: tuple[VideoWinner, ...]) -> AttentionEngineResult:
    return AttentionEngineResult(
        summary=_summary(run_id=run_id, computed_at=computed_at),
        video_winners=winners,
        patterns=(),
        families=(_family(),),
        channels=(),
    )


def _capture_publish(session, result: AttentionEngineResult, *, run_id: str) -> None:
    """Use publish-time clock so finalize does not lock historical UTC days under real wall clock."""
    capture_daily_intelligence_for_publish(
        session,
        result,
        run_id=run_id,
        captured_at=result.summary.computed_at,
    )


def _seed_keyword_hit(session, *, video_id: str = "vid-a", keyword_id: int = 1) -> None:
    if session.get(TargetKeyword, keyword_id) is None:
        session.add(
            TargetKeyword(
                id=keyword_id,
                keyword=f"test kw {keyword_id}",
                created_at=T0,
            ),
        )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=keyword_id,
            video_id=video_id,
            discovery_run_id=f"discovery_test_{video_id}",
            discovered_at=T0 - timedelta(hours=48),
            views_at_discovery=900,
            vph_at_discovery=90.0,
            content_format="long",
            qualification_state="qualified",
        ),
    )
    session.commit()


def test_multiple_publishes_same_utc_day_last_edition_wins() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    day = date(2026, 10, 10)

    r1 = _result(run_id="run_1", computed_at=datetime(2026, 10, 10, 8, 0, tzinfo=UTC), winners=(_winner("vid-a"),))
    r2 = _result(
        run_id="run_2",
        computed_at=datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
        winners=(_winner("vid-b"),),
    )
    _capture_publish(db, r1, run_id="run_1")
    _capture_publish(db, r2, run_id="run_2")
    db.commit()

    report = db.get(DailyIntelligenceReport, day)
    assert report is not None
    assert report.source_run_id == "run_2", (
        f"expected last intraday publish run_2, got {report.source_run_id!r} "
        f"(status={report.status!r}, locked_at={report.locked_at!r})"
    )
    assert report.status == STATUS_PROVISIONAL
    winners = list(db.scalars(select(DailyIntelligenceReportWinnerFinding).where(
        DailyIntelligenceReportWinnerFinding.report_date == day,
    )).all())
    assert len(winners) == 1
    assert winners[0].video_id == "vid-b"
    assert db.scalar(select(func.count()).select_from(DailyIntelligenceRunSnapshot)) == 2
    db.close()


def test_intraday_appearance_absent_from_final_top_n() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    _seed_keyword_hit(db, video_id="vid-b", keyword_id=2)
    day = date(2026, 10, 10)

    r1 = _result(
        run_id="run_1",
        computed_at=datetime(2026, 10, 10, 9, 0, tzinfo=UTC),
        winners=(_winner("vid-a"),),
    )
    r2 = _result(
        run_id="run_2",
        computed_at=datetime(2026, 10, 10, 20, 0, tzinfo=UTC),
        winners=(_winner("vid-b"),),
    )
    _capture_publish(db, r1, run_id="run_1")
    _capture_publish(db, r2, run_id="run_2")
    db.commit()

    final = db.scalar(
        select(DailyIntelligenceReportWinnerFinding.video_id).where(
            DailyIntelligenceReportWinnerFinding.report_date == day,
        ),
    )
    assert final == "vid-b"
    apps = list(
        db.scalars(
            select(DailyIntelligenceRunWinnerAppearance.video_id).where(
                DailyIntelligenceRunWinnerAppearance.report_date == day,
            ),
        ).all(),
    )
    assert set(apps) == {"vid-a", "vid-b"}
    db.close()


def test_finalize_locks_and_freezes_edition() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    day = date(2026, 10, 9)
    r1 = _result(
        run_id="run_1",
        computed_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
        winners=(_winner("vid-a"),),
    )
    _capture_publish(db, r1, run_id="run_1")
    db.commit()
    payload_before = db.get(DailyIntelligenceReportWinnerFinding, db.scalars(
        select(DailyIntelligenceReportWinnerFinding.id).limit(1),
    ).first()).payload_json

    finalize_eligible_reports(db, now=datetime(2026, 10, 10, 6, 0, tzinfo=UTC))
    db.commit()
    report = db.get(DailyIntelligenceReport, day)
    assert report.locked_at is not None
    assert report.status in (STATUS_COMPLETE, STATUS_PARTIAL)

    r_old = _result(
        run_id="run_old_day",
        computed_at=datetime(2026, 10, 9, 23, 0, tzinfo=UTC),
        winners=(_winner("vid-b"),),
    )
    _capture_publish(db, r_old, run_id="run_old_day")
    db.commit()
    report2 = db.get(DailyIntelligenceReport, day)
    assert report2.source_run_id == "run_1"
    winner = db.scalar(
        select(DailyIntelligenceReportWinnerFinding.video_id).where(
            DailyIntelligenceReportWinnerFinding.report_date == day,
        ),
    )
    assert winner == "vid-a"
    row = db.get(DailyIntelligenceReportWinnerFinding, db.scalars(
        select(DailyIntelligenceReportWinnerFinding.id).limit(1),
    ).first())
    assert row.payload_json == payload_before
    db.close()


def test_unavailable_day_without_publish() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    r1 = _result(
        run_id="run_1",
        computed_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        winners=(_winner(),),
    )
    _capture_publish(db, r1, run_id="run_1")
    db.commit()
    finalize_eligible_reports(db, now=datetime(2026, 10, 10, 6, 0, tzinfo=UTC))
    db.commit()
    gap = db.get(DailyIntelligenceReport, date(2026, 10, 9))
    assert gap is not None
    assert gap.status == STATUS_UNAVAILABLE
    db.close()


def test_idempotent_run_capture() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    r = _result(run_id="run_1", computed_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC), winners=(_winner(),))
    _capture_publish(db, r, run_id="run_1")
    _capture_publish(db, r, run_id="run_1")
    db.commit()
    assert db.scalar(select(func.count()).select_from(DailyIntelligenceRunSnapshot)) == 1
    db.close()


def test_publish_rollback_no_daily_rows() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    r = _result(run_id="run_1", computed_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC), winners=(_winner(),))
    try:
        _capture_publish(db, r, run_id="run_1")
        raise RuntimeError("simulated failure")
    except RuntimeError:
        db.rollback()
    db.commit()
    assert db.scalar(select(func.count()).select_from(DailyIntelligenceRunSnapshot)) == 0
    db.close()


def test_persist_attention_integration() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    r = _result(run_id="attention_test", computed_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC), winners=(_winner(),))
    persist_attention_result(db, r, run_id="attention_test")
    db.commit()
    assert db.scalar(select(func.count()).select_from(DailyIntelligenceRunSnapshot)) == 1
    db.close()


def test_cross_midnight_report_dates() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    ra = _result(
        run_id="run_a",
        computed_at=datetime(2026, 10, 10, 23, 30, tzinfo=UTC),
        winners=(_winner("vid-a"),),
    )
    rb = _result(
        run_id="run_b",
        computed_at=datetime(2026, 10, 11, 0, 30, tzinfo=UTC),
        winners=(_winner("vid-b"),),
    )
    _capture_publish(db, ra, run_id="run_a")
    _capture_publish(db, rb, run_id="run_b")
    db.commit()
    assert utc_report_date(datetime(2026, 10, 10, 23, 30, tzinfo=UTC)) == date(2026, 10, 10)
    assert db.get(DailyIntelligenceReport, date(2026, 10, 10)).source_run_id == "run_a"
    assert db.get(DailyIntelligenceReport, date(2026, 10, 11)).source_run_id == "run_b"
    db.close()


def test_discovery_provenance_and_missing() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    r1 = _result(
        run_id="run_1",
        computed_at=datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        winners=(_winner("vid-x"),),
    )
    _capture_publish(db, r1, run_id="run_1")
    db.commit()
    row = db.scalar(
        select(DailyIntelligenceRunWinnerAppearance).where(
            DailyIntelligenceRunWinnerAppearance.video_id == "vid-x",
        ),
    )
    prov = json.loads(row.discovery_provenance_json)
    assert prov.get("available") is False
    db.close()


def test_api_pagination() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    for i in range(3):
        ri = _result(
            run_id=f"run_{i}",
            computed_at=datetime(2026, 10, 10, 10 + i, 0, tzinfo=UTC),
            winners=(_winner(f"vid-{i}"),),
        )
        _capture_publish(db, ri, run_id=f"run_{i}")
    db.commit()
    db.close()

    def override_db():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(daily_intelligence_routes.router, prefix="/api/daily-intelligence")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    dates = client.get("/api/daily-intelligence/dates").json()
    assert dates["total"] >= 1
    day = "2026-10-10"
    winners = client.get(f"/api/daily-intelligence/reports/{day}/winners", params={"limit": 1, "offset": 0}).json()
    assert winners["total"] == 1
    assert winners["items"][0]["reason_summary"]
    assert "breakout" not in winners["items"][0]["reason_summary"].lower()
    apps = client.get("/api/daily-intelligence/videos/vid-0/appearances").json()
    assert apps["total"] >= 1


def test_partial_coverage_early_last_publish() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    _seed_keyword_hit(db)
    r1 = _result(
        run_id="run_1",
        computed_at=datetime(2026, 10, 9, 2, 0, tzinfo=UTC),
        winners=(_winner(),),
    )
    _capture_publish(db, r1, run_id="run_1")
    db.commit()
    finalize_eligible_reports(db, now=datetime(2026, 10, 10, 1, 0, tzinfo=UTC))
    db.commit()
    report = db.get(DailyIntelligenceReport, date(2026, 10, 9))
    assert report.status == STATUS_PARTIAL
    db.close()


def main() -> None:
    test_multiple_publishes_same_utc_day_last_edition_wins()
    test_intraday_appearance_absent_from_final_top_n()
    test_finalize_locks_and_freezes_edition()
    test_unavailable_day_without_publish()
    test_idempotent_run_capture()
    test_publish_rollback_no_daily_rows()
    test_persist_attention_integration()
    test_cross_midnight_report_dates()
    test_discovery_provenance_and_missing()
    test_api_pagination()
    test_partial_coverage_early_last_publish()
    print("OK daily intelligence 1.23A tests")


if __name__ == "__main__":
    main()
