"""Tests for keyword evidence read-model (Stage 1.20B)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    KeywordLifecycleEvent,
    KeywordScanRun,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.keyword_evidence_service import get_keyword_evidence, list_keyword_evidence
from app.services.keyword_lifecycle_service import set_keyword_lifecycle
from app.services.metrics import utc_now

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine())()


def _add_scan(
    session: Session,
    kw: TargetKeyword,
    *,
    status: str = "ok",
    run_suffix: str = "1",
    raw: int = 10,
    unique: int = 5,
    persisted: int = 2,
) -> None:
    started = NOW - timedelta(hours=1)
    session.add(
        KeywordScanRun(
            keyword_id=kw.id,
            discovery_run_id=f"run_{run_suffix}",
            started_at=started,
            finished_at=NOW,
            status=status,
            raw_candidates=raw,
            unique_candidates=unique,
            persisted_videos=persisted,
        ),
    )


def test_three_successful_scans() -> None:
    session = _session()
    kw = TargetKeyword(keyword="prob", lifecycle_status="probation", source_type="seed")
    session.add(kw)
    session.flush()
    for i in range(3):
        _add_scan(session, kw, run_suffix=str(i))
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.scan.successful_scan_count == 3
    assert ev.scan.failed_scan_count == 0
    assert ev.scheduling.scheduling_hint == "probation_ready_for_review"


def test_failed_scans_separate() -> None:
    session = _session()
    kw = TargetKeyword(keyword="fail", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _add_scan(session, kw, status="ok", run_suffix="ok")
    _add_scan(session, kw, status="failed", run_suffix="bad", raw=0, unique=0, persisted=0)
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.scan.successful_scan_count == 1
    assert ev.scan.failed_scan_count == 1


def test_zero_result_successful_scan() -> None:
    session = _session()
    kw = TargetKeyword(keyword="empty", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _add_scan(session, kw, raw=0, unique=0, persisted=0)
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.scan.successful_scan_count == 1
    assert ev.discovery.unique_discovered_video_count == 0
    assert ev.discovery.meta.availability == "available"


def test_duplicate_heavy_keyword() -> None:
    session = _session()
    kw = TargetKeyword(keyword="dup", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _add_scan(session, kw)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=NOW,
            was_within_keyword_duplicate=True,
            was_cross_keyword_duplicate=True,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.redundancy.duplicate_hit_count >= 2
    assert ev.redundancy.duplicate_rate is not None


def test_no_discovery_vph() -> None:
    session = _session()
    kw = TargetKeyword(keyword="novph", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _add_scan(session, kw)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=NOW,
            vph_at_discovery=None,
            views_at_discovery=100,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.discovery_vph.observation_count == 0
    assert ev.discovery_vph.median_discovery_vph is None
    assert ev.discovery_vph.meta.availability == "insufficient"


def test_breakout_eligible_zero_rate_unavailable() -> None:
    session = _session()
    kw = TargetKeyword(keyword="nobreak", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    _add_scan(session, kw)
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=True, include_delayed=False)
    assert ev is not None
    assert ev.breakout.breakout_eligible_count == 0
    assert ev.breakout.top_decile_breakout_rate is None
    assert ev.breakout.meta.availability in ("insufficient", "unavailable")


def test_valid_72h_outcome() -> None:
    session = _session()
    ch = Channel(id="ch1", title="C", subscribers_count=1, created_at=NOW)
    session.add(ch)
    kw = TargetKeyword(keyword="grow", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    discovery = NOW - timedelta(days=5)
    session.add(
        Video(
            id="v1",
            title="V",
            views_count=1000,
            likes_count=0,
            comments_count=0,
            published_at=discovery - timedelta(hours=10),
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    _add_scan(session, kw, run_suffix="1")
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=discovery,
            views_at_discovery=100,
            vph_at_discovery=10.0,
            content_format="regular",
            qualification_state="passed",
            persisted_for_monitoring=True,
        ),
    )
    target = discovery + timedelta(hours=72)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=target,
            published_at=discovery,
            age_hours=72.0,
            views=500,
            source="t",
            run_id="r",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(
        session,
        kw.id,
        include_breakout=False,
        include_delayed=True,
        evaluated_at=NOW,
    )
    assert ev is not None
    assert ev.delayed_outcome.valid_72h_outcome_count == 1
    assert ev.delayed_outcome.median_72h_growth == 400.0
    assert ev.delayed_outcome.median_72h_growth is not None


def test_matured_missing_72h_snapshot() -> None:
    session = _session()
    kw = TargetKeyword(keyword="miss", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    discovery = NOW - timedelta(days=5)
    _add_scan(session, kw)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="run_1",
            discovered_at=discovery,
            views_at_discovery=100,
            vph_at_discovery=1.0,
            content_format="regular",
            qualification_state="passed",
        ),
    )
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=True, evaluated_at=NOW)
    assert ev is not None
    assert ev.delayed_outcome.matured_72h_count >= 1
    assert ev.delayed_outcome.valid_72h_outcome_count == 0
    assert ev.delayed_outcome.median_72h_growth is None
    assert ev.delayed_outcome.missing_72h_outcome_count >= 1


def test_first_discovery_attribution() -> None:
    session = _session()
    kw1 = TargetKeyword(keyword="first", lifecycle_status="active", source_type="seed")
    kw2 = TargetKeyword(keyword="second", lifecycle_status="active", source_type="seed")
    session.add_all([kw1, kw2])
    session.flush()
    for kw in (kw1, kw2):
        _add_scan(session, kw, run_suffix=str(kw.id))
    session.add_all(
        [
            KeywordDiscoveryHit(
                keyword_id=kw2.id,
                video_id="shared",
                discovery_run_id="r2",
                discovered_at=NOW,
                content_format="regular",
                qualification_state="passed",
            ),
            KeywordDiscoveryHit(
                keyword_id=kw1.id,
                video_id="shared",
                discovery_run_id="r1",
                discovered_at=NOW - timedelta(hours=1),
                content_format="regular",
                qualification_state="passed",
            ),
        ],
    )
    session.commit()
    all_hits = get_keyword_evidence(session, kw2.id, attribution_mode="all_hits", include_breakout=False, include_delayed=False)
    first = get_keyword_evidence(session, kw2.id, attribution_mode="first_discovery", include_breakout=False, include_delayed=False)
    assert all_hits is not None and first is not None
    assert all_hits.discovery.attributed_observation_count == 1
    assert first.discovery.attributed_observation_count == 0


def test_no_division_by_zero_rates() -> None:
    session = _session()
    kw = TargetKeyword(keyword="zero", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.discovery.unique_candidate_rate is None
    assert ev.discovery.new_video_rate is None
    assert ev.redundancy.duplicate_rate is None


def test_unavailable_delayed_when_disabled() -> None:
    session = _session()
    kw = TargetKeyword(keyword="nd", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_delayed=False)
    assert ev.delayed_outcome.meta.availability == "unavailable"
    assert ev.delayed_outcome.median_72h_growth is None


def test_manual_lifecycle_context() -> None:
    session = _session()
    kw = TargetKeyword(keyword="manual", lifecycle_status="active", source_type="manual")
    session.add(kw)
    session.flush()
    set_keyword_lifecycle(session, kw.id, "weak", "manual review", actor_source="api")
    session.commit()
    ev = get_keyword_evidence(session, kw.id, include_breakout=False, include_delayed=False)
    assert ev is not None
    assert ev.lifecycle_context.last_manual_change_at is not None
    assert ev.lifecycle_context.latest_lifecycle_actor_source == "api"


def test_batch_list_no_per_keyword_scan_query_explosion() -> None:
    session = _session()
    keywords = []
    for i in range(5):
        kw = TargetKeyword(keyword=f"k{i}", lifecycle_status="active", source_type="seed")
        session.add(kw)
        keywords.append(kw)
    session.flush()
    for kw in keywords:
        _add_scan(session, kw, run_suffix=str(kw.id))
    session.commit()

    engine = session.get_bind()
    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_args, **_kwargs) -> None:
        counter["n"] += 1

    try:
        result = list_keyword_evidence(
            session,
            limit=5,
            include_breakout=False,
            include_delayed=False,
        )
        assert len(result.items) == 5
        assert counter["n"] < 40, f"too many SQL round-trips: {counter['n']}"
    finally:
        event.remove(engine, "before_cursor_execute", _count)


def main() -> None:
    test_three_successful_scans()
    test_failed_scans_separate()
    test_zero_result_successful_scan()
    test_duplicate_heavy_keyword()
    test_no_discovery_vph()
    test_breakout_eligible_zero_rate_unavailable()
    test_valid_72h_outcome()
    test_matured_missing_72h_snapshot()
    test_first_discovery_attribution()
    test_no_division_by_zero_rates()
    test_unavailable_delayed_when_disabled()
    test_manual_lifecycle_context()
    test_batch_list_no_per_keyword_scan_query_explosion()
    print("All keyword evidence tests passed.")


if __name__ == "__main__":
    main()
