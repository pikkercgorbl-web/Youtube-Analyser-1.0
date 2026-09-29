"""Tests for revisit executor (Stage 1.13B)."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base
from app.services.revisit_executor import (
    RevisitExecutorConfig,
    deduplicate_capture_requests,
    execute_snapshot_capture_requests,
)
from app.services.snapshot_collection_policy import SnapshotCaptureRequest
from app.services.video_snapshot_storage import get_snapshots_for_video

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
PUB = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _request(vid: str, *, run_id: str = "run1", cp: int = 24) -> SnapshotCaptureRequest:
    return SnapshotCaptureRequest(
        video_id=vid,
        channel_id="ch1",
        checkpoint_age_hours=cp,
        reason="due",
        requested_at=NOW,
        current_age_hours=24.0,
        source="revisit_test",
        run_id=run_id,
    )


def _details(vid: str, *, views: int = 2400, channel_id: str = "ch1") -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=vid,
        channel_id=channel_id,
        title="t",
        published_at=PUB,
        views_count=views,
        likes_count=10,
        comments_count=2,
        duration_seconds=600,
    )


class _MockClient:
    def __init__(self, *, missing: set[str] | None = None, fail_batches: set[int] | None = None):
        self.missing = missing or set()
        self.fail_batches = fail_batches or set()
        self.calls: list[list[str]] = []
        self._batch_index = 0

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        self.calls.append(list(video_ids))
        if self._batch_index in self.fail_batches:
            self._batch_index += 1
            raise RuntimeError("batch failed")
        self._batch_index += 1
        return [_details(vid) for vid in video_ids if vid not in self.missing]


def test_one_request_inserts() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests([_request("v1")], _MockClient(), session)
    session.commit()
    assert outcome.summary.inserted_snapshot_count == 1
    assert len(get_snapshots_for_video(session, "v1")) == 1


def test_fifty_requests_one_batch() -> None:
    session = _session()
    client = _MockClient()
    requests = [_request(f"v{i}", run_id=f"r{i}") for i in range(50)]
    execute_snapshot_capture_requests(requests, client, session)
    assert len(client.calls) == 1
    assert len(client.calls[0]) == 50


def test_fifty_one_requests_two_batches() -> None:
    session = _session()
    client = _MockClient()
    requests = [_request(f"v{i}", run_id=f"r{i}") for i in range(51)]
    outcome = execute_snapshot_capture_requests(requests, client, session)
    assert outcome.summary.batch_count == 2
    assert len(client.calls) == 2


def test_duplicate_requests_deduplicated() -> None:
    req = _request("v1")
    unique, input_count, dup = deduplicate_capture_requests([req, req])
    assert input_count == 2
    assert dup == 1
    assert len(unique) == 1


def test_missing_video_not_fatal() -> None:
    session = _session()
    client = _MockClient(missing={"v2"})
    outcome = execute_snapshot_capture_requests(
        [_request("v1"), _request("v2", run_id="r2")],
        client,
        session,
    )
    assert outcome.summary.inserted_snapshot_count == 1
    assert outcome.summary.missing_video_count == 1


def test_missing_no_fake_snapshot() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests(
        [_request("v-missing", run_id="r")],
        _MockClient(missing={"v-missing"}),
        session,
    )
    session.commit()
    assert get_snapshots_for_video(session, "v-missing") == []


def test_batch_failure_continues() -> None:
    session = _session()
    requests = [_request(f"v{i}", run_id=f"r{i}") for i in range(51)]
    client = _MockClient(fail_batches={0})
    outcome = execute_snapshot_capture_requests(requests, client, session, config=RevisitExecutorConfig(batch_size=50))
    assert outcome.summary.failed_batch_count == 1
    assert outcome.summary.successful_batch_count == 1
    assert outcome.summary.inserted_snapshot_count >= 1


def test_captured_at_is_execution_time() -> None:
    session = _session()
    fixed = datetime(2026, 9, 15, 15, 30, tzinfo=UTC)
    with patch("app.services.revisit_executor.utc_now", return_value=fixed):
        outcome = execute_snapshot_capture_requests([_request("v1")], _MockClient(), session)
    assert outcome.results[0].captured_at == fixed
    assert outcome.results[0].captured_at != NOW


def test_vph_derived() -> None:
    session = _session()
    captured = PUB + timedelta(hours=24)
    with patch("app.services.revisit_executor.utc_now", return_value=captured):
        outcome = execute_snapshot_capture_requests([_request("v1")], _MockClient(), session)
    assert outcome.results[0].vph == 100.0


def test_zero_subscriber_ratio_null() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests(
        [_request("v1")],
        _MockClient(),
        session,
        subscribers_by_channel_id={"ch1": 0},
    )
    row = get_snapshots_for_video(session, "v1")[0]
    assert row.views_per_subscriber is None


def test_missing_subscriber_still_inserts() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests([_request("v1")], _MockClient(), session)
    assert outcome.summary.inserted_snapshot_count == 1
    assert get_snapshots_for_video(session, "v1")[0].subscribers is None


def test_duplicate_db_snapshot() -> None:
    session = _session()
    req = _request("v1")
    fixed = datetime(2026, 9, 15, 15, 30, tzinfo=UTC)
    with patch("app.services.revisit_executor.utc_now", return_value=fixed):
        execute_snapshot_capture_requests([req], _MockClient(), session)
        session.commit()
        outcome = execute_snapshot_capture_requests([req], _MockClient(), session)
    assert outcome.results[0].status == "duplicate"
    assert len(get_snapshots_for_video(session, "v1")) == 1


def test_validation_failed_missing_channel() -> None:
    session = _session()

    class _Client:
        def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
            return [
                YouTubeVideoDetails(
                    video_id="v1",
                    channel_id="",
                    title="t",
                    published_at=PUB,
                    views_count=100,
                    likes_count=0,
                    comments_count=0,
                    duration_seconds=600,
                ),
            ]

    bad_req = SnapshotCaptureRequest(
        video_id="v1",
        channel_id=None,
        checkpoint_age_hours=24,
        reason="due",
        requested_at=NOW,
        current_age_hours=24.0,
        source="revisit_test",
        run_id="r",
    )
    outcome = execute_snapshot_capture_requests([bad_req], _Client(), session)
    assert outcome.summary.validation_failed_count == 1


def test_persistence_error_isolated() -> None:
    session = _session()
    with patch(
        "app.services.revisit_executor.persist_video_snapshot",
        side_effect=RuntimeError("db down"),
    ):
        outcome = execute_snapshot_capture_requests([_request("v1")], _MockClient(), session)
    assert outcome.summary.persistence_failed_count == 1


def test_aggregate_counts() -> None:
    session = _session()
    outcome = execute_snapshot_capture_requests(
        [_request("v1"), _request("v2", run_id="r2")],
        _MockClient(missing={"v2"}),
        session,
    )
    assert outcome.summary.input_request_count == 2
    assert outcome.summary.missing_video_count == 1
    assert outcome.summary.inserted_snapshot_count == 1


def test_deterministic_ordering() -> None:
    session = _session()
    requests = [_request("b"), _request("a", run_id="r2")]
    outcome = execute_snapshot_capture_requests(requests, _MockClient(), session)
    assert [r.video_id for r in outcome.results] == sorted([r.video_id for r in outcome.results])


def test_executor_no_tier_import() -> None:
    import app.services.revisit_executor as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "assign_monitoring_tiers" not in source
    assert "monitoring_tier_budget_policy" not in source


def test_no_channel_api_per_video() -> None:
    client = _MockClient()
    session = _session()
    execute_snapshot_capture_requests([_request("v1")], client, session)
    assert hasattr(client, "get_videos")
    assert not hasattr(client, "get_channel")


def _run(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)


def test_regressions() -> None:
    _run("test_video_snapshot_storage.py")
    _run("test_snapshot_collection_policy.py")
    _run("test_monitoring_tier_budget_policy.py")


def main() -> None:
    tests = [
        test_one_request_inserts,
        test_fifty_requests_one_batch,
        test_fifty_one_requests_two_batches,
        test_duplicate_requests_deduplicated,
        test_missing_video_not_fatal,
        test_missing_no_fake_snapshot,
        test_batch_failure_continues,
        test_captured_at_is_execution_time,
        test_vph_derived,
        test_zero_subscriber_ratio_null,
        test_missing_subscriber_still_inserts,
        test_duplicate_db_snapshot,
        test_validation_failed_missing_channel,
        test_persistence_error_isolated,
        test_aggregate_counts,
        test_deterministic_ordering,
        test_executor_no_tier_import,
        test_no_channel_api_per_video,
        test_regressions,
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
    print("All revisit executor tests passed.")


if __name__ == "__main__":
    main()
