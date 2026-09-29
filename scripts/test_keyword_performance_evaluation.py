"""Tests for batched keyword performance evaluation (Stage 1.18B)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    KeywordScanRun,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoSnapshot,
)
from app.services.keyword_performance_evaluation import (
    _first_discovery_owner,
    _first_hit_per_keyword_video,
    match_horizon_outcome,
    KeywordVideoBaseline,
)
from app.services.metrics import ensure_utc
from app.services.keyword_performance_service import list_keyword_performance

UTC = timezone.utc
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine())()


def _seed_video(session: Session, video_id: str, *, channel_id: str = "ch1") -> None:
    if session.get(Channel, channel_id) is None:
        session.add(
            Channel(id=channel_id, title="C", subscribers_count=1, created_at=NOW),
        )
    session.add(
        Video(
            id=video_id,
            title="V",
            views_count=1000,
            likes_count=0,
            comments_count=0,
            published_at=NOW - timedelta(hours=10),
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id=channel_id,
        ),
    )


def test_all_hits_dedupes_rescan_baseline() -> None:
    session = _session()
    kw = TargetKeyword(keyword="k")
    session.add(kw)
    session.flush()
    early = NOW - timedelta(days=5)
    late = NOW - timedelta(days=1)
    for run_id, at in (("r1", early), ("r2", late)):
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id=run_id,
                discovered_at=at,
                views_at_discovery=100,
                content_format="regular",
                qualification_state="rejected",
            ),
        )
    session.commit()
    hits = list(session.scalars(select(KeywordDiscoveryHit)).all())
    baselines = _first_hit_per_keyword_video(hits)
    assert ensure_utc(baselines[(kw.id, "v1")].discovered_at) == ensure_utc(early)


def test_first_discovery_tie_lowest_keyword_id() -> None:
    hits = [
        KeywordDiscoveryHit(
            keyword_id=2,
            video_id="v",
            discovery_run_id="r",
            discovered_at=NOW,
            content_format="regular",
            qualification_state="rejected",
        ),
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="v",
            discovery_run_id="r2",
            discovered_at=NOW,
            content_format="regular",
            qualification_state="rejected",
        ),
    ]
    owner = _first_discovery_owner(hits)
    assert owner["v"] == 1


def test_horizon_snapshot_inside_tolerance() -> None:
    discovery = NOW
    target = discovery + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch1",
        captured_at=target + timedelta(hours=2),
        published_at=discovery,
        age_hours=74.0,
        views=500,
        source="t",
        run_id="r",
    )
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=discovery,
        views_at_discovery=100,
        vph_at_discovery=10.0,
    )
    outcome = match_horizon_outcome(baseline, {"v1": [snap]})
    assert outcome is not None
    assert outcome.absolute_view_growth == 400


def test_horizon_outside_tolerance_missing() -> None:
    discovery = NOW
    target = discovery + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch1",
        captured_at=target + timedelta(hours=20),
        published_at=discovery,
        age_hours=92.0,
        views=500,
        source="t",
        run_id="r",
    )
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=discovery,
        views_at_discovery=100,
        vph_at_discovery=10.0,
    )
    assert match_horizon_outcome(baseline, {"v1": [snap]}) is None


def test_null_views_at_discovery_missing() -> None:
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=NOW,
        views_at_discovery=None,
        vph_at_discovery=1.0,
    )
    assert match_horizon_outcome(baseline, {}) is None


def test_negative_growth_preserved() -> None:
    discovery = NOW
    target = discovery + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch1",
        captured_at=target,
        published_at=discovery,
        age_hours=72.0,
        views=50,
        source="t",
        run_id="r",
    )
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=discovery,
        views_at_discovery=100,
        vph_at_discovery=1.0,
    )
    outcome = match_horizon_outcome(baseline, {"v1": [snap]})
    assert outcome is not None
    assert outcome.absolute_view_growth == -50


def test_breakout_pass_once_for_list() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="a"))
    session.commit()
    calls = {"n": 0}
    from app.services.keyword_performance_evaluation import build_global_breakout_bundle

    original = build_global_breakout_bundle

    def counting(session, **kwargs):
        calls["n"] += 1
        return original(session, **kwargs)

    with patch(
        "app.services.keyword_performance_service.build_global_breakout_bundle",
        side_effect=counting,
    ):
        list_keyword_performance(session, limit=5)
    assert calls["n"] == 1


def test_list_query_count_bounded() -> None:
    session = _session()
    for idx in range(3):
        session.add(TargetKeyword(keyword=f"k{idx}"))
    session.commit()
    query_count = 0
    engine = session.get_bind()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        list_keyword_performance(session, limit=3)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert query_count <= 25


def test_first_discovery_mode_assigns_video() -> None:
    session = _session()
    k1 = TargetKeyword(keyword="first")
    k2 = TargetKeyword(keyword="second")
    session.add_all([k1, k2])
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=k1.id,
            video_id="v",
            discovery_run_id="r1",
            discovered_at=NOW - timedelta(hours=1),
            views_at_discovery=10,
            content_format="regular",
            qualification_state="rejected",
        ),
    )
    session.add(
        KeywordDiscoveryHit(
            keyword_id=k2.id,
            video_id="v",
            discovery_run_id="r2",
            discovered_at=NOW,
            views_at_discovery=10,
            content_format="regular",
            qualification_state="rejected",
        ),
    )
    session.commit()
    r_all = list_keyword_performance(session, limit=10, attribution_mode="all_hits")
    r_first = list_keyword_performance(session, limit=10, attribution_mode="first_discovery")
    by_id_all = {i.keyword_id: i.attributed_video_count for i in r_all.items}
    by_id_first = {i.keyword_id: i.attributed_video_count for i in r_first.items}
    assert by_id_all[k1.id] == 1 and by_id_all[k2.id] == 1
    assert by_id_first[k1.id] == 1 and by_id_first[k2.id] == 0


def test_api_context_fields_on_list() -> None:
    session = _session()
    session.add(TargetKeyword(keyword="x"))
    session.commit()
    result = list_keyword_performance(session, limit=1)
    assert result.context.global_eligible_video_count is not None
    assert result.items[0].ranking_version == "breakout_v1"
    assert result.items[0].evaluated_at is not None


def main() -> None:
    tests = [
        test_all_hits_dedupes_rescan_baseline,
        test_first_discovery_tie_lowest_keyword_id,
        test_horizon_snapshot_inside_tolerance,
        test_horizon_outside_tolerance_missing,
        test_null_views_at_discovery_missing,
        test_negative_growth_preserved,
        test_breakout_pass_once_for_list,
        test_list_query_count_bounded,
        test_first_discovery_mode_assigns_video,
        test_api_context_fields_on_list,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print("All keyword performance evaluation tests passed.")


if __name__ == "__main__":
    main()
