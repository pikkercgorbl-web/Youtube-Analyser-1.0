"""Tests for monitoring capture outcome diagnostics."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base
from app.models.orm import MonitoringCaptureOutcome
from app.services.monitoring_capture_outcome_storage import persist_monitoring_capture_outcomes
from app.services.revisit_executor import execute_snapshot_capture_requests
from app.services.snapshot_collection_policy import SnapshotCaptureRequest

UTC = timezone.utc
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
PUB = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request(
    vid: str,
    *,
    run_id: str,
    cp: int = 24,
) -> SnapshotCaptureRequest:
    return SnapshotCaptureRequest(
        video_id=vid,
        channel_id="ch1",
        checkpoint_age_hours=cp,
        reason="due",
        requested_at=NOW,
        current_age_hours=24.0,
        source="monitoring_worker",
        run_id=run_id,
    )


def _details(vid: str) -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=vid,
        channel_id="ch1",
        title="t",
        published_at=PUB,
        views_count=100,
        likes_count=0,
        comments_count=0,
        duration_seconds=600,
    )


class _MockClient:
    def __init__(self, missing: set[str]):
        self.missing = missing

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        return [_details(vid) for vid in video_ids if vid not in self.missing]


def test_repeat_missing_same_video_two_cycles() -> None:
    session = _session()
    client = _MockClient(missing={"ghost1", "ghost2"})
    run_a = "monitoring_test_a"
    run_b = "monitoring_test_b"
    for cycle_run, prefix in ((run_a, f"{run_a}:"), (run_b, f"{run_b}:")):
        outcome = execute_snapshot_capture_requests(
            [
                _request("ghost1", run_id=f"{prefix}ghost1:cp24"),
                _request("ghost2", run_id=f"{prefix}ghost2:cp24"),
                _request("ok1", run_id=f"{prefix}ok1:cp24"),
            ],
            client,
            session,
        )
        session.commit()
        assert outcome.summary.missing_video_count == 2
        assert outcome.summary.inserted_snapshot_count == 1
        n = persist_monitoring_capture_outcomes(
            session,
            monitoring_run_id=cycle_run,
            results=outcome.results,
        )
        session.commit()
        assert n == 2

    total_rows = session.scalar(select(func.count()).select_from(MonitoringCaptureOutcome)) or 0
    distinct_videos = session.scalar(
        select(func.count(func.distinct(MonitoringCaptureOutcome.video_id))),
    ) or 0
    assert total_rows == 4
    assert distinct_videos == 2

    per_video = session.execute(
        select(MonitoringCaptureOutcome.video_id, func.count())
        .group_by(MonitoringCaptureOutcome.video_id)
        .order_by(MonitoringCaptureOutcome.video_id),
    ).all()
    assert per_video == [("ghost1", 2), ("ghost2", 2)]
    reason = session.scalars(
        select(MonitoringCaptureOutcome.reason_code).limit(1),
    ).first()
    assert reason == "yt_items_absent"


def test_many_missing_distinct_videos_one_cycle() -> None:
    session = _session()
    missing_ids = {f"m{i}" for i in range(5)}
    client = _MockClient(missing=missing_ids)
    run_id = "monitoring_many"
    requests = [
        _request(vid, run_id=f"{run_id}:{vid}:cp24") for vid in sorted(missing_ids)
    ]
    outcome = execute_snapshot_capture_requests(requests, client, session)
    session.commit()
    assert outcome.summary.missing_video_count == 5
    persist_monitoring_capture_outcomes(
        session,
        monitoring_run_id=run_id,
        results=outcome.results,
    )
    session.commit()
    distinct = session.scalar(
        select(func.count(func.distinct(MonitoringCaptureOutcome.video_id))),
    )
    total = session.scalar(select(func.count()).select_from(MonitoringCaptureOutcome))
    assert total == 5
    assert distinct == 5


def test_inserted_outcomes_not_persisted() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests(
        [_request("ok1", run_id="monitoring_x:ok1:cp24")],
        _MockClient(missing=set()),
        session,
    )
    session.commit()
    assert outcome.summary.inserted_snapshot_count == 1
    n = persist_monitoring_capture_outcomes(
        session,
        monitoring_run_id="monitoring_x",
        results=outcome.results,
    )
    assert n == 0


def main() -> None:
    test_repeat_missing_same_video_two_cycles()
    test_many_missing_distinct_videos_one_cycle()
    test_inserted_outcomes_not_persisted()
    print("OK monitoring capture outcome tests")


if __name__ == "__main__":
    main()
