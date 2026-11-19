"""Tests for append-only video snapshot storage (Stage 1.11)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import VideoSnapshot
from app.services.video_snapshot_adapters import validation_t0_row_to_observation
from app.services.video_snapshot_storage import (
    VideoSnapshotObservation,
    derive_snapshot_metrics,
    get_latest_snapshot_for_video,
    get_nearest_snapshot_by_age_hours,
    get_snapshots_for_video,
    persist_video_snapshot,
    persist_video_snapshots,
    validate_snapshot_observation,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _obs(
    *,
    video_id: str = "vid1",
    captured_at: datetime | None = None,
    views: int | None = 1000,
    run_id: str = "run-a",
    **kwargs: object,
) -> VideoSnapshotObservation:
    return VideoSnapshotObservation(
        video_id=video_id,
        channel_id="ch1",
        captured_at=captured_at or datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        source="test",
        run_id=run_id,
        views=views,
        published_at=kwargs.pop("published_at", datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)),  # type: ignore[arg-type]
        subscribers=kwargs.pop("subscribers", 100),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def test_first_snapshot_inserts() -> None:
    session = _session()
    row, err, dup = persist_video_snapshot(session, _obs())
    session.commit()
    assert err is None
    assert dup is False
    assert row is not None
    stored = get_latest_snapshot_for_video(session, "vid1")
    assert stored is not None
    assert stored.views == 1000


def test_multiple_timestamps_same_video() -> None:
    session = _session()
    t0 = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=24)
    persist_video_snapshot(session, _obs(captured_at=t0, views=5000, run_id="r1"))
    persist_video_snapshot(session, _obs(captured_at=t1, views=40000, run_id="r2"))
    session.commit()
    history = get_snapshots_for_video(session, "vid1")
    assert len(history) == 2
    assert history[0].views == 5000
    assert history[1].views == 40000


def test_duplicate_capture_idempotent() -> None:
    session = _session()
    obs = _obs()
    persist_video_snapshot(session, obs)
    session.commit()
    _, _, dup = persist_video_snapshot(session, obs)
    session.commit()
    assert dup is True
    assert len(get_snapshots_for_video(session, "vid1")) == 1


def test_different_timestamp_not_duplicate() -> None:
    session = _session()
    persist_video_snapshot(session, _obs(captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)))
    persist_video_snapshot(session, _obs(captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)))
    session.commit()
    assert len(get_snapshots_for_video(session, "vid1")) == 2


def test_null_subscribers_null_vps() -> None:
    age, vph, vps = derive_snapshot_metrics(
        views=100,
        published_at=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
        captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        subscribers=None,
    )
    assert vps is None
    assert vph == 50.0
    assert age == 2.0


def test_zero_subscribers_null_vps() -> None:
    _, _, vps = derive_snapshot_metrics(
        views=100,
        published_at=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
        captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        subscribers=0,
    )
    assert vps is None


def test_positive_age_vph() -> None:
    _, vph, _ = derive_snapshot_metrics(
        views=5000,
        published_at=datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc),
        captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        subscribers=None,
    )
    assert vph == 2500.0


def test_zero_or_negative_age_null_vph() -> None:
    same_time = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
    age, vph, _ = derive_snapshot_metrics(
        views=100,
        published_at=same_time,
        captured_at=same_time,
        subscribers=None,
    )
    assert age is None
    assert vph is None

    future = same_time + timedelta(hours=1)
    age2, vph2, _ = derive_snapshot_metrics(
        views=100,
        published_at=future,
        captured_at=same_time,
        subscribers=None,
    )
    assert age2 is None
    assert vph2 is None


def test_missing_published_at_null_age_vph() -> None:
    age, vph, _ = derive_snapshot_metrics(
        views=100,
        published_at=None,
        captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc),
        subscribers=None,
    )
    assert age is None
    assert vph is None


def test_previous_snapshot_unchanged() -> None:
    session = _session()
    persist_video_snapshot(session, _obs(views=111, run_id="a"))
    session.commit()
    first_id = get_snapshots_for_video(session, "vid1")[0].id
    persist_video_snapshot(session, _obs(views=999, run_id="b", captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)))
    session.commit()
    first = session.get(VideoSnapshot, first_id)
    assert first is not None
    assert first.views == 111


def test_latest_and_ordered_helpers() -> None:
    session = _session()
    persist_video_snapshot(session, _obs(captured_at=datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc), views=1, run_id="a"))
    persist_video_snapshot(session, _obs(captured_at=datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc), views=3, run_id="b"))
    persist_video_snapshot(session, _obs(captured_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc), views=2, run_id="c"))
    session.commit()
    latest = get_latest_snapshot_for_video(session, "vid1")
    assert latest is not None
    assert latest.views == 3
    ordered = get_snapshots_for_video(session, "vid1")
    assert [row.views for row in ordered] == [1, 2, 3]


def test_bulk_insert_counts() -> None:
    session = _session()
    obs1 = _obs(video_id="v1", run_id="r1")
    obs_dup = _obs(video_id="v1", run_id="r1")
    obs_bad = _obs(video_id="", run_id="r2")
    obs2 = _obs(video_id="v2", run_id="r3")
    result = persist_video_snapshots(session, [obs1, obs_dup, obs_bad, obs2])
    session.commit()
    assert result.attempted_count == 4
    assert result.inserted_count == 2
    assert result.duplicate_count == 1
    assert result.failed_count == 1
    assert result.failures


def test_negative_counters_rejected() -> None:
    err = validate_snapshot_observation(_obs(views=-1))
    assert err is not None


def test_nearest_snapshot_by_age_hours() -> None:
    session = _session()
    published = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    persist_video_snapshot(
        session,
        _obs(
            captured_at=published + timedelta(hours=6),
            published_at=published,
            views=1,
            run_id="6h",
        ),
    )
    persist_video_snapshot(
        session,
        _obs(
            captured_at=published + timedelta(hours=24),
            published_at=published,
            views=2,
            run_id="24h",
        ),
    )
    session.commit()
    nearest = get_nearest_snapshot_by_age_hours(session, "vid1", 23.0)
    assert nearest is not None
    assert nearest.run_id == "24h"


def test_validation_adapter_requires_fields() -> None:
    assert validation_t0_row_to_observation({}) is None
    obs = validation_t0_row_to_observation(
        {
            "video_id": "abc",
            "channel_id": "ch",
            "discovered_at": "2026-09-14T10:00:00+00:00",
            "discovery_views": 10,
        },
    )
    assert obs is not None
    assert obs.views == 10


def main() -> None:
    tests = [
        test_first_snapshot_inserts,
        test_multiple_timestamps_same_video,
        test_duplicate_capture_idempotent,
        test_different_timestamp_not_duplicate,
        test_null_subscribers_null_vps,
        test_zero_subscribers_null_vps,
        test_positive_age_vph,
        test_zero_or_negative_age_null_vph,
        test_missing_published_at_null_age_vph,
        test_previous_snapshot_unchanged,
        test_latest_and_ordered_helpers,
        test_bulk_insert_counts,
        test_negative_counters_rejected,
        test_nearest_snapshot_by_age_hours,
        test_validation_adapter_requires_fields,
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
        raise SystemExit(f"{failed} test(s) failed")
    print("All video snapshot storage tests passed.")


if __name__ == "__main__":
    main()
