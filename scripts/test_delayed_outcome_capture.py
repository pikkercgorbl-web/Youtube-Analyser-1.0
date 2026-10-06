"""Tests for delayed outcome capture scheduler (Stage 1.20E.2)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base
from app.models.orm import Channel, KeywordDiscoveryHit, TargetKeyword, Video, VideoSnapshot
from app.services.delayed_outcome_capture_config import (
    OUTCOME_CAPTURE_SOURCE,
    OutcomeCaptureBudgetPolicy,
)
from app.services.delayed_outcome_capture_cycle import run_delayed_outcome_capture_cycle
from app.services.delayed_outcome_capture_planner import (
    classify_outcome_observation,
    plan_delayed_outcome_capture,
)
from app.services.delayed_outcome_capture_types import OutcomeObservationRecord
from app.services.keyword_performance_evaluation import (
    HORIZON_SNAPSHOT_TOLERANCE_HOURS,
    match_horizon_outcome,
    KeywordVideoBaseline,
)
from app.services.monitoring_cycle import run_monitoring_cycle
from app.services.video_snapshot_storage import get_snapshots_for_videos

UTC = timezone.utc
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_video(session, video_id: str = "v1", published: datetime | None = None) -> None:
    pub = published or NOW - timedelta(days=5)
    if session.get(Channel, "ch") is None:
        session.add(Channel(id="ch", title="C", subscribers_count=1, created_at=NOW))
        session.flush()
    if session.get(Video, video_id) is None:
        session.add(
            Video(
                id=video_id,
                channel_id="ch",
                title="T",
                published_at=pub,
            ),
        )
        session.flush()


class _MockClient:
    def __init__(self, mapping: dict[str, YouTubeVideoDetails] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls: list[list[str]] = []

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        self.calls.append(list(video_ids))
        return [self.mapping[vid] for vid in video_ids if vid in self.mapping]


def _record(
    *,
    kid: int = 1,
    vid: str = "v1",
    discovered_at: datetime,
    views: int = 10,
) -> OutcomeObservationRecord:
    return OutcomeObservationRecord(
        keyword_id=kid,
        video_id=vid,
        channel_id="ch",
        discovered_at=discovered_at,
        views_at_discovery=views,
    )


def test_pending_before_window() -> None:
    disc = NOW - timedelta(hours=24)
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={},
    )
    assert row.state == "pending"


def test_due_inside_window_before_target() -> None:
    disc = NOW - timedelta(hours=70)
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={},
    )
    assert row.state == "capture_due"


def test_overdue_inside_window_after_target() -> None:
    disc = NOW - timedelta(hours=74)
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={},
    )
    assert row.state == "capture_overdue"


def test_expired_after_window() -> None:
    disc = NOW - timedelta(hours=100)
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={},
    )
    assert row.state == "expired"


def test_existing_in_window_satisfies() -> None:
    disc = NOW - timedelta(days=5)
    target = disc + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=target,
        published_at=disc,
        age_hours=72.0,
        views=100,
        source="monitoring_worker",
        run_id="r",
    )
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={"v1": [snap]},
    )
    assert row.state == "satisfied"


def test_outside_window_does_not_satisfy() -> None:
    disc = NOW - timedelta(days=5)
    target = disc + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=target + timedelta(hours=30),
        published_at=disc,
        age_hours=102.0,
        views=100,
        source="monitoring_worker",
        run_id="r",
    )
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={"v1": [snap]},
    )
    assert row.state == "expired"


def test_multiple_keywords_one_video_one_fetch() -> None:
    session = _session()
    _seed_video(session, "v1")
    for label in ("a", "b"):
        kw = TargetKeyword(keyword=label, lifecycle_status="active", source_type="seed")
        session.add(kw)
        session.flush()
        disc = NOW - timedelta(hours=70)
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id=f"r_{label}",
                discovered_at=disc,
                views_at_discovery=1,
            ),
        )
    session.commit()
    plan = plan_delayed_outcome_capture(session, reference=NOW)
    assert plan.capture_due_count == 2
    assert plan.unique_due_video_count == 1

    details = YouTubeVideoDetails(
        video_id="v1",
        channel_id="ch",
        title="t",
        published_at=NOW - timedelta(days=5),
        duration_seconds=120,
        views_count=50,
        likes_count=0,
        comments_count=0,
    )
    client = _MockClient({"v1": details})
    with patch("app.services.revisit_executor.utc_now", return_value=NOW):
        summary = run_delayed_outcome_capture_cycle(
            session,
            youtube_client=client,
            dry_run=False,
            current_time=NOW,
            budget=OutcomeCaptureBudgetPolicy(max_videos_per_cycle=10),
        )
    assert summary.selected_video_count == 1
    assert len(client.calls) == 1
    assert client.calls[0] == ["v1"]


def test_non_overlapping_windows_still_one_fetch_if_both_due_now() -> None:
    session = _session()
    _seed_video(session, "v1")
    kw = TargetKeyword(keyword="k", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    session.add_all(
        [
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id="r1",
                discovered_at=NOW - timedelta(hours=70),
                views_at_discovery=1,
            ),
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id="v1",
                discovery_run_id="r2",
                discovered_at=NOW - timedelta(hours=71),
                views_at_discovery=1,
            ),
        ],
    )
    session.commit()
    plan = plan_delayed_outcome_capture(session, reference=NOW)
    assert plan.unique_due_video_count == 1


def test_failed_fetch_not_satisfied() -> None:
    session = _session()
    _seed_video(session)
    kw = TargetKeyword(keyword="k", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(hours=70),
            views_at_discovery=1,
        ),
    )
    session.commit()

    class _FailClient:
        def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
            raise RuntimeError("boom")

    with patch("app.services.revisit_executor.utc_now", return_value=NOW):
        run_delayed_outcome_capture_cycle(
            session,
            youtube_client=_FailClient(),
            dry_run=False,
            current_time=NOW,
        )
    plan = plan_delayed_outcome_capture(session, reference=NOW)
    assert plan.capture_due_count >= 1


def test_budget_defers_without_expiring() -> None:
    session = _session()
    for idx in range(3):
        vid = f"v{idx}"
        _seed_video(session, vid)
        kw = TargetKeyword(keyword=f"k{idx}", lifecycle_status="active", source_type="seed")
        session.add(kw)
        session.flush()
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=vid,
                discovery_run_id="r",
                discovered_at=NOW - timedelta(hours=70),
                views_at_discovery=1,
            ),
        )
    session.commit()
    summary = run_delayed_outcome_capture_cycle(
        session,
        youtube_client=_MockClient(),
        dry_run=True,
        current_time=NOW,
        budget=OutcomeCaptureBudgetPolicy(max_videos_per_cycle=1),
    )
    assert summary.deferred_video_count >= 2


def test_outcome_snapshot_source_and_metadata() -> None:
    session = _session()
    _seed_video(session)
    kw = TargetKeyword(keyword="k", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(hours=70),
            views_at_discovery=5,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="v1",
        channel_id="ch",
        title="t",
        published_at=NOW - timedelta(days=5),
        duration_seconds=120,
        views_count=50,
        likes_count=0,
        comments_count=0,
    )
    with patch("app.services.revisit_executor.utc_now", return_value=NOW):
        run_delayed_outcome_capture_cycle(
            session,
            youtube_client=_MockClient({"v1": details}),
            dry_run=False,
            current_time=NOW,
        )
    snap = session.scalars(
        select(VideoSnapshot).where(VideoSnapshot.source == OUTCOME_CAPTURE_SOURCE),
    ).first()
    assert snap is not None
    assert snap.raw_metadata is not None
    assert snap.raw_metadata.get("capture_purpose") == "keyword_delayed_outcome"


def test_evaluator_accepts_outcome_source_snapshot() -> None:
    disc = NOW - timedelta(days=5)
    target = disc + timedelta(hours=72)
    snap = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=target,
        published_at=disc,
        age_hours=72.0,
        views=200,
        source=OUTCOME_CAPTURE_SOURCE,
        run_id="x",
    )
    baseline = KeywordVideoBaseline(
        keyword_id=1,
        video_id="v1",
        discovery_at=disc,
        views_at_discovery=10,
        vph_at_discovery=1.0,
    )
    assert match_horizon_outcome(baseline, {"v1": [snap]}) is not None


def test_historical_expired_not_backfilled_by_current_snapshot() -> None:
    disc = NOW - timedelta(days=10)
    snap_now = VideoSnapshot(
        video_id="v1",
        channel_id="ch",
        captured_at=NOW,
        published_at=disc,
        age_hours=240.0,
        views=999,
        source=OUTCOME_CAPTURE_SOURCE,
        run_id="late",
    )
    row = classify_outcome_observation(
        _record(discovered_at=disc),
        reference=NOW,
        snapshots_by_video={"v1": [snap_now]},
    )
    assert row.state == "expired"


def test_batch_size_at_most_50() -> None:
    session = _session()
    mapping: dict[str, YouTubeVideoDetails] = {}
    for idx in range(55):
        vid = f"v{idx}"
        _seed_video(session, vid)
        kw = TargetKeyword(keyword=f"kw{idx}", lifecycle_status="active", source_type="seed")
        session.add(kw)
        session.flush()
        session.add(
            KeywordDiscoveryHit(
                keyword_id=kw.id,
                video_id=vid,
                discovery_run_id="r",
                discovered_at=NOW - timedelta(hours=70),
                views_at_discovery=1,
            ),
        )
        mapping[vid] = YouTubeVideoDetails(
            video_id=vid,
            channel_id="ch",
            title="t",
            published_at=NOW - timedelta(days=5),
            duration_seconds=120,
            views_count=1,
            likes_count=0,
            comments_count=0,
        )
    session.commit()
    client = _MockClient(mapping)
    with patch("app.services.revisit_executor.utc_now", return_value=NOW):
        run_delayed_outcome_capture_cycle(
            session,
            youtube_client=client,
            dry_run=False,
            current_time=NOW,
            budget=OutcomeCaptureBudgetPolicy(max_videos_per_cycle=55, batch_size=50),
        )
    assert all(len(batch) <= 50 for batch in client.calls)


def test_no_n_plus_one_snapshot_load() -> None:
    session = _session()
    _seed_video(session, "v1")
    kw = TargetKeyword(keyword="k", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(hours=70),
            views_at_discovery=1,
        ),
    )
    session.commit()
    with patch(
        "app.services.delayed_outcome_capture_planner.get_snapshots_for_videos",
        wraps=get_snapshots_for_videos,
    ) as mocked:
        plan_delayed_outcome_capture(session, reference=NOW)
        assert mocked.call_count == 1


def test_repeated_cycle_idempotent() -> None:
    session = _session()
    _seed_video(session)
    kw = TargetKeyword(keyword="k", lifecycle_status="active", source_type="seed")
    session.add(kw)
    session.flush()
    session.add(
        KeywordDiscoveryHit(
            keyword_id=kw.id,
            video_id="v1",
            discovery_run_id="r",
            discovered_at=NOW - timedelta(hours=70),
            views_at_discovery=1,
        ),
    )
    session.commit()
    details = YouTubeVideoDetails(
        video_id="v1",
        channel_id="ch",
        title="t",
        published_at=NOW - timedelta(days=5),
        duration_seconds=120,
        views_count=50,
        likes_count=0,
        comments_count=0,
    )
    client = _MockClient({"v1": details})
    with patch("app.services.revisit_executor.utc_now", return_value=NOW):
        first = run_delayed_outcome_capture_cycle(
            session,
            youtube_client=client,
            dry_run=False,
            current_time=NOW,
            run_id="cycle_a",
        )
    later = NOW + timedelta(minutes=5)
    with patch("app.services.revisit_executor.utc_now", return_value=later):
        second = run_delayed_outcome_capture_cycle(
            session,
            youtube_client=client,
            dry_run=False,
            current_time=later,
            run_id="cycle_b",
        )
    assert first.inserted_snapshot_count == 1
    assert second.inserted_snapshot_count == 0
    assert second.selected_video_count == 0
    plan = plan_delayed_outcome_capture(session, reference=later)
    assert plan.satisfied_count >= 1


def test_monitoring_cycle_unchanged_dry_run() -> None:
    session = _session()
    _seed_video(session)
    summary = run_monitoring_cycle(session, youtube_client=_MockClient(), dry_run=True)
    assert summary.cycle_status == "dry_run"


def main() -> None:
    tests = [
        test_pending_before_window,
        test_due_inside_window_before_target,
        test_overdue_inside_window_after_target,
        test_expired_after_window,
        test_existing_in_window_satisfies,
        test_outside_window_does_not_satisfy,
        test_multiple_keywords_one_video_one_fetch,
        test_non_overlapping_windows_still_one_fetch_if_both_due_now,
        test_failed_fetch_not_satisfied,
        test_budget_defers_without_expiring,
        test_outcome_snapshot_source_and_metadata,
        test_evaluator_accepts_outcome_source_snapshot,
        test_historical_expired_not_backfilled_by_current_snapshot,
        test_batch_size_at_most_50,
        test_no_n_plus_one_snapshot_load,
        test_repeated_cycle_idempotent,
        test_monitoring_cycle_unchanged_dry_run,
    ]
    for fn in tests:
        fn()
        print(f"OK {fn.__name__}")
    print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
