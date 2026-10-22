"""Stage 1.23B.3 integration acceptance (isolated DB; not production restore-check)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import daily_intelligence as di_routes
from app.api.routes import saved_research as sr_routes
from app.models.db import Base, get_db
from app.models.orm import (
    Channel,
    DailyIntelligenceReport,
    DailyIntelligenceReportFamilyFinding,
    DailyIntelligenceReportWinnerFinding,
    SavedFamily,
    SavedFamilyObservation,
    SavedVideo,
    SavedVideoObservation,
    Video,
)
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    PatternFamily,
    VideoWinner,
    pattern_family_to_dict,
    video_winner_to_dict,
    youtube_watch_url,
)
from app.services.metrics import ensure_utc
from app.services.saved_research import (
    append_saved_research_observations_for_result,
    archive_video,
    export_frozen_video,
    restore_video,
)
from app.services.saved_research_daily_intelligence import (
    DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND,
    save_family_from_daily_intelligence,
    save_video_from_daily_intelligence,
)
from app.services.saved_research_feedback import append_analyst_feedback
from app.services.saved_research_validation import (
    compute_video_validation,
    observation_is_daily_intelligence_anchor,
)

UTC = timezone.utc
REPORT_DATE = date(2026, 10, 10)
RUN_A = "attention_20261010T140809Z"
RUN_B = "attention_20261011T120000Z"
COMPUTED_A = datetime(2026, 10, 10, 14, 8, 9, tzinfo=UTC)
COMPUTED_B = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)

RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str) -> None:
    RESULTS.append((name, status, detail))


def _sqlite_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _resolve_postgres_url() -> str | None:
    url = os.environ.get("DI_SAVE_POSTGRES_TEST_URL", "").strip()
    if not url:
        url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url:
        return None
    low = url.lower()
    if "restore_check" in low:
        raise SystemExit("Refusing restore_check database URL")
    prod = os.environ.get("DATABASE_URL", "").strip()
    if prod and url.split("@")[-1] == prod.split("@")[-1]:
        raise SystemExit("Test URL must not equal DATABASE_URL")
    if "_test" not in low and "test_" not in low and "saved_topics_test" not in low:
        raise SystemExit(f"Refusing non-test PostgreSQL URL: {url}")
    return url


def _winner(vid: str = "acc-vid-1") -> VideoWinner:
    return VideoWinner(
        video_id=vid,
        title="Acc Title",
        channel_id="ch-acc",
        channel_title="Acc Channel",
        youtube_url=youtube_watch_url(vid),
        published_at=COMPUTED_A,
        age_hours=8.0,
        views=9000,
        vph=800.0,
        subscribers=5000,
        breakout_rank=3,
        breakout_eligible=True,
        channel_relative_signal=None,
        acceleration_state="stable",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("high_current_vph",),
        human_reasons=("acc",),
        keyword_ids=(1,),
    )


def _seed(session: Session) -> None:
    session.add(Channel(id="ch-acc", title="Acc Channel", subscribers_count=5000, created_at=COMPUTED_A))
    session.add(
        Video(
            id="acc-vid-1",
            channel_id="ch-acc",
            title="Acc Title",
            views_count=9000,
            published_at=COMPUTED_A,
        ),
    )
    session.add(
        DailyIntelligenceReport(
            report_date=REPORT_DATE,
            status="provisional",
            source_run_id=RUN_A,
            source_computed_at=COMPUTED_A,
            generated_at=COMPUTED_A,
            publish_attempt=1,
        ),
    )
    w = _winner()
    session.add(
        DailyIntelligenceReportWinnerFinding(
            report_date=REPORT_DATE,
            video_id=w.video_id,
            rank=1,
            title=w.title,
            channel_id=w.channel_id,
            channel_title=w.channel_title,
            youtube_url=w.youtube_url,
            discovery_provenance_json="{}",
            payload_json=json.dumps(video_winner_to_dict(w)),
        ),
    )
    f = pattern_family_to_dict(
        PatternFamily(
            family_key="family:acc:1",
            label="Acc Fam",
            family_kind="title_phrase",
            member_pattern_keys=(),
            member_labels=(),
            video_ids=("acc-vid-1",),
            channel_ids=("ch-acc",),
            keyword_ids=(),
            video_count=2,
            channel_count=2,
            keyword_count=0,
            breakout_eligible_count=1,
            videos_last_24h=1,
            videos_previous_24h=0,
            videos_previous_48_24h=0,
            grouping_reasons=(),
            quality_flags=(),
            support_sources=(),
            first_seen_at=COMPUTED_A,
            latest_seen_at=COMPUTED_A,
        ),
    )
    session.add(
        DailyIntelligenceReportFamilyFinding(
            report_date=REPORT_DATE,
            family_key="family:acc:1",
            rank=1,
            label="Acc Fam",
            video_count=2,
            channel_count=2,
            payload_json=json.dumps(f),
        ),
    )
    session.commit()


def _attention_result(*, run_id: str, computed_at: datetime, video_id: str) -> AttentionEngineResult:
    w = _winner(video_id)
    summary = AttentionSummary(
        run_id=run_id,
        computed_at=computed_at,
        timezone_name="UTC",
        window_hours=24,
        window_start=computed_at,
        window_end=computed_at,
        source="test",
        candidate_video_count=1,
        winner_count=1,
        pattern_count=0,
        channel_momentum_count=0,
        video_limit=50,
        pattern_limit=20,
        channel_limit=20,
        notes={},
    )
    return AttentionEngineResult(summary=summary, video_winners=(w,), patterns=(), channels=(), families=())


def check_no_live_snapshot() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    with patch("app.services.saved_research._load_attention_snapshot") as mock_live:
        mock_live.side_effect = AssertionError("live Attention must not load on DI save")
        save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
        session.commit()
    record("1. No live Attention on DI save", "PASS", "patch raised if _load_attention_snapshot called")
    session.close()


def check_frozen_contract() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    frozen = export_frozen_video(r.item)
    assert frozen.get("identity", {}).get("video_id") == "acc-vid-1"
    assert frozen.get("evidence", {}).get("views") == 9000
    ds = frozen.get("context", {}).get("decision_source", {})
    assert ds.get("kind") == "daily_intelligence"
    assert ds.get("source_run_id") == RUN_A
    record(
        "2. frozen_payload_json contract",
        "PASS",
        f"identity+evidence+decision_source keys present; views={frozen['evidence']['views']}",
    )
    session.close()


def check_anchor_ui_absence_api() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    detail = sr_routes._video_detail(session, r.item)
    assert detail.attention_absence_message is None
    live = detail.live_observation
    assert live is not None
    assert live.payload.get("observation_kind") == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
    record(
        "3. Anchor not shown as live Attention absence",
        "PASS",
        "attention_absence_message=None for DI anchor latest obs",
    )
    session.close()


def check_unique_run_observations() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    frozen_before = r.item.frozen_payload_json
    result_b = _attention_result(run_id=RUN_B, computed_at=COMPUTED_B, video_id="acc-vid-1")
    append_saved_research_observations_for_result(session, run_id=RUN_B, result=result_b)
    session.commit()
    session.refresh(r.item)
    assert r.item.frozen_payload_json == frozen_before
    obs = session.scalars(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    ).all()
    run_ids = {o.attention_run_id for o in obs}
    assert RUN_A in run_ids and RUN_B in run_ids
    assert len(obs) == 2
    dup = session.scalar(
        select(func.count())
        .select_from(SavedVideoObservation)
        .where(
            SavedVideoObservation.saved_video_id == r.item.id,
            SavedVideoObservation.attention_run_id == RUN_A,
        ),
    )
    assert dup == 1
    append_saved_research_observations_for_result(session, run_id=RUN_B, result=result_b)
    session.commit()
    obs2 = session.scalars(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    ).all()
    assert len(obs2) == 2
    record(
        "4. Unique (saved_video_id, attention_run_id)",
        "PASS",
        f"runs={sorted(run_ids)}; append skip on duplicate run",
    )
    session.close()


def check_idempotent() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    first = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    frozen1 = first.item.frozen_payload_json
    second = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    n_v = session.scalar(select(func.count()).select_from(SavedVideo))
    n_o = session.scalar(
        select(func.count()).select_from(SavedVideoObservation).where(
            SavedVideoObservation.saved_video_id == first.item.id,
        ),
    )
    assert second.idempotent and not second.created
    assert first.item.frozen_payload_json == frozen1 == second.item.frozen_payload_json
    assert n_v == 1 and n_o == 1
    record("5. Idempotent POST", "PASS", f"saved_videos={n_v} observations={n_o}")
    session.close()


def check_archived_restore() -> None:
    from app.services.saved_research import SavedResearchArchivedError

    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    row = session.scalar(select(SavedVideo).where(SavedVideo.video_id == "acc-vid-1"))
    archive_video(session, row.id)
    session.commit()
    try:
        save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
        raise AssertionError("expected SavedResearchArchivedError")
    except SavedResearchArchivedError:
        pass
    with patch("app.services.saved_research._load_attention_snapshot", return_value=None):
        restore_video(session, row.id)
    session.commit()
    assert row.archived_at is None
    record("6. Archived 409 + restore", "PASS", f"409 then restore archived_at cleared")
    session.close()


def check_no_false_72h() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    obs = session.scalar(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    )
    assert obs.delayed_outcome_state is None
    val = compute_video_validation(
        frozen=export_frozen_video(r.item),
        live=obs,
        saved_at=r.item.saved_at,
        observation_count=1,
    )
    assert val["delayed_72h_state"] is None
    record("7. No false 72h outcome", "PASS", "obs.delayed_outcome_state NULL; validation delayed_72h_state None")
    session.close()


def check_concurrency() -> None:
    engine = _sqlite_engine()
    SessionLocal = sessionmaker(bind=engine)
    s0 = SessionLocal()
    _seed(s0)
    s0.close()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker():
        session = SessionLocal()
        barrier.wait()
        try:
            save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
            session.commit()
            outcomes.append("ok")
        except IntegrityError:
            session.rollback()
            outcomes.append("conflict")
        finally:
            session.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    session = SessionLocal()
    n_v = session.scalar(select(func.count()).select_from(SavedVideo))
    n_o = session.scalar(select(func.count()).select_from(SavedVideoObservation))
    session.close()
    ok = n_v == 1 and n_o == 1 and len(outcomes) == 2
    record(
        "8. Concurrent save",
        "PASS" if ok else "FAIL",
        f"outcomes={outcomes} saved_videos={n_v} observations={n_o}",
    )


def check_feedback_validation() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    fb = append_analyst_feedback(
        session,
        entity_kind="video",
        entity_id=r.item.id,
        verdict="USEFUL",
        reason="acc test",
    )
    session.commit()
    obs = session.scalar(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    )
    assert observation_is_daily_intelligence_anchor(obs)
    val = compute_video_validation(
        frozen=export_frozen_video(r.item),
        live=obs,
        saved_at=r.item.saved_at,
        observation_count=1,
    )
    assert val["latest_measurement_source"] == "daily_intelligence_anchor"
    assert fb is not None and fb.verdict == "USEFUL"
    record("10. Feedback + Validation", "PASS", f"verdict={fb.verdict} source={val['latest_measurement_source']}")
    session.close()


def check_frozen_after_refresh() -> None:
    SessionLocal = sessionmaker(bind=_sqlite_engine())
    session = SessionLocal()
    _seed(session)
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    snap = r.item.frozen_payload_json
    for _ in range(2):
        append_saved_research_observations_for_result(
            session,
            run_id=RUN_B,
            result=_attention_result(run_id=RUN_B, computed_at=COMPUTED_B, video_id="acc-vid-1"),
        )
        session.commit()
    session.refresh(r.item)
    assert r.item.frozen_payload_json == snap
    record("9. Frozen after Attention append", "PASS", "frozen_payload_json unchanged after 2 append calls")
    session.close()


def _postgres_engine(url: str):
    from app.db.migrations import run_startup_migrations

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    run_startup_migrations(engine)
    return engine


def _postgres_reset(session: Session) -> None:
    """Reset only DI save acceptance tables + fixture corpus rows."""
    session.execute(text("DELETE FROM videos WHERE id IN ('acc-vid-1')"))
    session.execute(text("DELETE FROM channels WHERE id IN ('ch-acc')"))
    session.execute(
        text(
            "TRUNCATE saved_research_feedback, saved_research_events, "
            "saved_video_observations, saved_family_observations, "
            "saved_videos, saved_families, "
            "daily_intelligence_report_winner_findings, daily_intelligence_report_family_findings, "
            "daily_intelligence_reports RESTART IDENTITY CASCADE",
        ),
    )
    session.commit()


def _postgres_db_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?")[0]


def run_postgres_full_acceptance() -> None:
    url = _resolve_postgres_url()
    if not url:
        record("PG suite", "NOT RUN", "Set DI_SAVE_POSTGRES_TEST_URL")
        return

    db_name = _postgres_db_name(url)
    record("PG safety", "PASS", f"target_db={db_name}; restore_check refused by guard")

    engine = _postgres_engine(url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def fresh_session() -> Session:
        s = SessionLocal()
        _postgres_reset(s)
        _seed(s)
        return s

    # 1–2 winner + family without live Attention
    session = fresh_session()
    with patch("app.services.saved_research._load_attention_snapshot") as mock_live:
        mock_live.side_effect = AssertionError("live Attention must not load on DI save")
        vr = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
        fr = save_family_from_daily_intelligence(session, report_date=REPORT_DATE, family_key="family:acc:1")
        session.commit()
    frozen = export_frozen_video(vr.item)
    assert frozen["context"]["decision_source"]["kind"] == "daily_intelligence"
    record(
        "PG-1/2 Historical save (no live Attention)",
        "PASS",
        f"saved_video_id={vr.item.id} saved_family_id={fr.item.id} views={frozen['evidence']['views']}",
    )
    session.close()

    # 3 idempotent
    session = fresh_session()
    first = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    snap = first.item.frozen_payload_json
    second = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    n_v = session.scalar(select(func.count()).select_from(SavedVideo))
    n_o = session.scalar(select(func.count()).select_from(SavedVideoObservation))
    ok = second.idempotent and n_v == 1 and n_o == 1 and second.item.frozen_payload_json == snap
    record("PG-3 Idempotent save", "PASS" if ok else "FAIL", f"saved_videos={n_v} obs={n_o} idempotent={second.idempotent}")
    session.close()

    # 4 archived 409 via HTTP
    session = fresh_session()
    save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    row = session.scalar(select(SavedVideo).where(SavedVideo.video_id == "acc-vid-1"))
    archive_video(session, row.id)
    session.commit()
    session.close()

    app = FastAPI()
    app.include_router(di_routes.router, prefix="/api/daily-intelligence")

    def _db_dep():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db_dep
    client = TestClient(app)
    res409 = client.post(
        f"/api/daily-intelligence/reports/{REPORT_DATE.isoformat()}/winners/acc-vid-1/save-to-research",
    )
    record("PG-4 Archived 409", "PASS" if res409.status_code == 409 else "FAIL", f"status={res409.status_code}")

    # 5 anchor semantics
    session = fresh_session()
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    detail = sr_routes._video_detail(session, r.item)
    obs = session.scalar(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    )
    anchor_ok = (
        detail.attention_absence_message is None
        and obs is not None
        and json.loads(obs.payload_json).get("observation_kind") == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
        and obs.delayed_outcome_state is None
    )
    fr = save_family_from_daily_intelligence(session, report_date=REPORT_DATE, family_key="family:acc:1")
    session.commit()
    fd = sr_routes._family_detail(session, fr.item)
    fobs = session.scalar(
        select(SavedFamilyObservation).where(SavedFamilyObservation.saved_family_id == fr.item.id),
    )
    family_anchor_ok = (
        fd.absence_message is None
        and fobs is not None
        and json.loads(fobs.payload_json).get("observation_kind") == DAILY_INTELLIGENCE_SAVE_ANCHOR_KIND
        and fobs.family_present is False
    )
    record(
        "PG-5 Anchor semantics",
        "PASS" if anchor_ok and family_anchor_ok else "FAIL",
        f"video absence={detail.attention_absence_message!r} family absence={fd.absence_message!r}",
    )
    session.close()

    # 6–7 append + frozen immutable
    session = fresh_session()
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    before = r.item.frozen_payload_json
    append_saved_research_observations_for_result(
        session,
        run_id=RUN_B,
        result=_attention_result(run_id=RUN_B, computed_at=COMPUTED_B, video_id="acc-vid-1"),
    )
    session.commit()
    session.refresh(r.item)
    obs_count = session.scalar(
        select(func.count()).select_from(SavedVideoObservation).where(
            SavedVideoObservation.saved_video_id == r.item.id,
        ),
    )
    immut = r.item.frozen_payload_json == before and obs_count == 2
    record(
        "PG-6/7 Append + frozen immutable",
        "PASS" if immut else "FAIL",
        f"observations={obs_count} frozen_unchanged={r.item.frozen_payload_json == before}",
    )
    session.close()

    # 8 feedback + validation
    session = fresh_session()
    r = save_video_from_daily_intelligence(session, report_date=REPORT_DATE, video_id="acc-vid-1")
    session.commit()
    fb = append_analyst_feedback(
        session,
        entity_kind="video",
        entity_id=r.item.id,
        verdict="USEFUL",
        reason="pg acc",
    )
    session.commit()
    obs = session.scalar(
        select(SavedVideoObservation).where(SavedVideoObservation.saved_video_id == r.item.id),
    )
    val = compute_video_validation(
        frozen=export_frozen_video(r.item),
        live=obs,
        saved_at=r.item.saved_at,
        observation_count=1,
    )
    fb_ok = fb is not None and val["delayed_72h_state"] is None and val["latest_measurement_source"] == "daily_intelligence_anchor"
    record(
        "PG-8 Validation/Feedback + no false 72h",
        "PASS" if fb_ok else "FAIL",
        f"verdict={fb.verdict if fb else None} delayed_72h={val['delayed_72h_state']}",
    )
    session.close()

    # 9 concurrent service transactions
    session = fresh_session()
    session.close()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def pg_worker():
        db = SessionLocal()
        barrier.wait()
        try:
            save_video_from_daily_intelligence(db, report_date=REPORT_DATE, video_id="acc-vid-1")
            db.commit()
            outcomes.append("ok")
        except IntegrityError:
            db.rollback()
            outcomes.append("conflict")
        finally:
            db.close()

    t1 = threading.Thread(target=pg_worker)
    t2 = threading.Thread(target=pg_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    session = SessionLocal()
    n_v = session.scalar(select(func.count()).select_from(SavedVideo))
    n_o = session.scalar(select(func.count()).select_from(SavedVideoObservation))
    session.close()
    record(
        "PG-9 Concurrent DB save",
        "PASS" if n_v == 1 and n_o == 1 and len(outcomes) == 2 else "FAIL",
        f"outcomes={outcomes} saved_videos={n_v} observations={n_o}",
    )

    # 10 concurrent HTTP POST
    session = fresh_session()
    session.close()
    http_status: list[int] = []
    http_created: list[bool] = []
    barrier2 = threading.Barrier(2)

    def http_worker():
        c = TestClient(app)
        barrier2.wait()
        resp = c.post(
            f"/api/daily-intelligence/reports/{REPORT_DATE.isoformat()}/winners/acc-vid-1/save-to-research",
        )
        http_status.append(resp.status_code)
        if resp.status_code == 200:
            http_created.append(bool(resp.json().get("created")))

    session = SessionLocal()
    _postgres_reset(session)
    _seed(session)
    session.close()

    h1 = threading.Thread(target=http_worker)
    h2 = threading.Thread(target=http_worker)
    h1.start()
    h2.start()
    h1.join()
    h2.join()
    session = SessionLocal()
    n_v = session.scalar(select(func.count()).select_from(SavedVideo))
    n_o = session.scalar(select(func.count()).select_from(SavedVideoObservation))
    row = session.scalar(select(SavedVideo).where(SavedVideo.video_id == "acc-vid-1"))
    frozen_final = row.frozen_payload_json if row else None
    session.close()
    http_ok = (
        n_v == 1
        and n_o == 1
        and all(s == 200 for s in http_status)
        and sum(1 for c in http_created if c) == 1
        and sum(1 for c in http_created if not c) >= 1
    )
    record(
        "PG-10 Concurrent HTTP POST",
        "PASS" if http_ok else "FAIL",
        f"statuses={http_status} created_flags={http_created} saved_videos={n_v} obs={n_o}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postgres-only",
        action="store_true",
        help="Run only PostgreSQL acceptance (requires DI_SAVE_POSTGRES_TEST_URL)",
    )
    args = parser.parse_args()

    if args.postgres_only:
        run_postgres_full_acceptance()
    else:
        check_no_live_snapshot()
        check_frozen_contract()
        check_anchor_ui_absence_api()
        check_unique_run_observations()
        check_idempotent()
        check_archived_restore()
        check_no_false_72h()
        check_concurrency()
        check_frozen_after_refresh()
        check_feedback_validation()
        run_postgres_full_acceptance()

    print("\n=== Stage 1.23B.3 Acceptance ===")
    for name, status, detail in RESULTS:
        print(f"[{status}] {name}\n    {detail}")
    fails = [r for r in RESULTS if r[1] == "FAIL"]
    if fails:
        raise SystemExit(1)
    print("\nAll executed checks passed (NOT RUN excluded).")


if __name__ == "__main__":
    main()
