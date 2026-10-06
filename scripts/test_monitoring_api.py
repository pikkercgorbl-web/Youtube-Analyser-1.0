"""Tests for monitoring REST API (Stage 1.14A)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import monitoring
from app.models.db import Base, get_db
from app.models.orm import Channel, MonitoringCycleRun, MonitoringWorkerState, Video, VideoFormat, VideoSnapshot
from app.services.monitoring_api_service import build_active_monitoring_enriched
from app.services.monitoring_cycle_run_storage import persist_monitoring_cycle_run
from app.services.monitoring_cycle import MonitoringCycleSummary
from app.services.monitoring_queue_persist import replace_monitoring_video_queue
from app.services.monitoring_worker_lock import acquire_monitoring_worker_lock

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _make_client() -> tuple[TestClient, sessionmaker]:
    engine = _engine()
    factory = sessionmaker(bind=engine)
    api = FastAPI()
    api.include_router(monitoring.router, prefix="/api/monitoring")

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    api.dependency_overrides[get_db] = override_get_db
    return TestClient(api), factory


def _seed_monitoring_queue(
    session: Session,
    *,
    run_id: str = "monitoring_test_queue_run",
    reference: datetime = NOW,
) -> None:
    """Persist queue read model + cycle row so default list path is bounded."""
    with patch("app.services.monitoring_api_service.utc_now", return_value=reference):
        enriched, _, _ = build_active_monitoring_enriched(session)
        replace_monitoring_video_queue(session, run_id, enriched)
    summary = MonitoringCycleSummary(
        run_id=run_id,
        started_at=reference - timedelta(minutes=5),
        finished_at=reference,
        runtime_seconds=1.0,
        cycle_status="ok",
        loaded_video_count=len(enriched),
        eligible_video_count=len(enriched),
        tier_counts={"A": sum(1 for r in enriched if r.decision.tier.value == "A"), "B": 0, "C": 0},
    )
    persist_monitoring_cycle_run(session, summary)
    session.commit()


def _seed_video(
    session: Session,
    video_id: str,
    *,
    published_at: datetime,
    views: int = 5000,
    title: str = "Test video",
) -> None:
    if session.get(Channel, "ch1") is None:
        session.add(
            Channel(
                id="ch1",
                title="Channel One",
                subscribers_count=1000,
                created_at=published_at,
            ),
        )
    session.add(
        Video(
            id=video_id,
            title=title,
            views_count=views,
            likes_count=0,
            comments_count=0,
            published_at=published_at,
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch1",
        ),
    )
    session.commit()


def test_status_endpoint_valid() -> None:
    client, factory = _make_client()
    response = client.get("/api/monitoring/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("running", "stopped", "stale", "unknown")
    assert body["worker_interval_seconds"] == 900


def test_overview_no_worker_state() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    response = client.get("/api/monitoring/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_cycle"] is None
    assert "active_monitored_count" in body


def test_overview_with_latest_cycle() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    summary = MonitoringCycleSummary(
        run_id="monitoring_test_run",
        started_at=NOW - timedelta(minutes=5),
        finished_at=NOW,
        runtime_seconds=1.0,
        cycle_status="ok",
        loaded_video_count=1,
        eligible_video_count=1,
        tier_counts={"A": 1},
    )
    persist_monitoring_cycle_run(session, summary)
    session.commit()
    response = client.get("/api/monitoring/overview")
    assert response.status_code == 200
    assert response.json()["latest_cycle"]["run_id"] == "monitoring_test_run"


def test_video_list_pagination() -> None:
    client, factory = _make_client()
    session = factory()
    for i in range(5):
        _seed_video(session, f"v{i}", published_at=NOW - timedelta(hours=10 + i), views=1000 + i * 100)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        response = client.get("/api/monitoring/videos?limit=2&offset=1")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2
    assert body["total"] >= 2


def test_tier_filter() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=20), views=9000)
    _seed_monitoring_queue(session)
    response = client.get("/api/monitoring/videos?tier=A")
    assert response.status_code == 200
    assert all(item["tier"] == "A" for item in response.json()["items"])


def test_status_filter_due() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=24), views=5000)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        response = client.get("/api/monitoring/videos?status=due")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert items[0]["due_checkpoint_hours"]


def test_default_sort_deterministic() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v2", published_at=NOW - timedelta(hours=30), views=100)
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=30), views=100)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        r1 = client.get("/api/monitoring/videos").json()["items"]
        r2 = client.get("/api/monitoring/videos").json()["items"]
    assert [x["video_id"] for x in r1] == [x["video_id"] for x in r2]


def test_list_uses_latest_snapshot_metrics() -> None:
    client, factory = _make_client()
    session = factory()
    pub = NOW - timedelta(hours=24)
    _seed_video(session, "v1", published_at=pub, views=100)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=NOW,
            published_at=pub,
            age_hours=24.0,
            views=9999,
            vph=400.0,
            source="test",
            run_id="snap1",
        ),
    )
    session.commit()
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        item = client.get("/api/monitoring/videos").json()["items"][0]
    assert item["current_views"] == 9999
    assert item["current_vph"] == 400.0


def test_missing_snapshot_fallback() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=321)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        item = client.get("/api/monitoring/videos").json()["items"][0]
    assert item["current_views"] == 321


def test_detail_endpoint() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=24), views=5000)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        response = client.get("/api/monitoring/videos/v1")
    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == "v1"
    assert body["checkpoints"]


def test_unknown_video_404() -> None:
    client, _factory = _make_client()
    assert client.get("/api/monitoring/videos/missing").status_code == 404


def test_checkpoint_planner_on_detail() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=24), views=5000)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        cps = client.get("/api/monitoring/videos/v1").json()["checkpoints"]
    cp24 = next(c for c in cps if c["target_age_hours"] == 24)
    assert cp24["status"] in ("due", "overdue", "completed", "pending", "expired")


def test_snapshot_history_chronological() -> None:
    client, factory = _make_client()
    session = factory()
    pub = NOW - timedelta(hours=48)
    _seed_video(session, "v1", published_at=pub, views=100)
    for hour in (10, 20, 30):
        session.add(
            VideoSnapshot(
                video_id="v1",
                channel_id="ch1",
                captured_at=pub + timedelta(hours=hour),
                published_at=pub,
                age_hours=float(hour),
                views=hour * 10,
                source="test",
                run_id=f"r{hour}",
            ),
        )
    session.commit()
    rows = client.get("/api/monitoring/videos/v1/snapshots").json()
    times = [row["captured_at"] for row in rows]
    assert times == sorted(times)


def test_cycle_history_newest_first() -> None:
    client, factory = _make_client()
    session = factory()
    for idx, offset in enumerate((2, 1, 0)):
        persist_monitoring_cycle_run(
            session,
            MonitoringCycleSummary(
                run_id=f"run_{idx}",
                started_at=NOW - timedelta(hours=offset),
                finished_at=NOW,
                cycle_status="ok",
            ),
        )
    session.commit()
    runs = client.get("/api/monitoring/cycles?limit=3").json()["items"]
    assert runs[0]["run_id"] == "run_2"


def test_nullable_subscribers_on_snapshots() -> None:
    client, factory = _make_client()
    session = factory()
    pub = NOW - timedelta(hours=10)
    _seed_video(session, "v1", published_at=pub, views=100)
    session.add(
        VideoSnapshot(
            video_id="v1",
            channel_id="ch1",
            captured_at=NOW,
            published_at=pub,
            age_hours=10.0,
            views=100,
            subscribers=None,
            source="test",
            run_id="r1",
        ),
    )
    session.commit()
    snap = client.get("/api/monitoring/videos/v1/snapshots").json()[0]
    assert snap["subscribers"] is None


def test_baseline_on_detail_explicit() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=24), views=5000)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        with patch(
            "app.services.monitoring_api_service.compute_channel_velocity_baseline",
            return_value=type(
                "R",
                (),
                {
                    "baseline_status": "insufficient_history",
                    "comparable_video_count": 0,
                    "median_vph": None,
                    "p75_vph": None,
                    "p90_vph": None,
                    "vph_vs_channel_median": None,
                    "vph_vs_channel_p75": None,
                },
            )(),
        ):
            baseline = client.get("/api/monitoring/videos/v1").json()["channel_baseline"]
    assert baseline["baseline_status"] == "insufficient_history"


def test_list_no_baseline_computation() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.compute_channel_velocity_baseline") as mock_bl:
        with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
            client.get("/api/monitoring/videos")
    mock_bl.assert_not_called()


def test_list_unavailable_without_queue() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    body = client.get("/api/monitoring/videos").json()
    assert body["items"] == []
    assert body["queue_source"] == "unavailable"


def test_list_live_planner_diagnostic() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        body = client.get("/api/monitoring/videos?live_planner=true").json()
    assert body["queue_source"] == "live_planner"
    assert len(body["items"]) >= 1


def test_frozen_stage110_not_referenced() -> None:
    paths = [
        ROOT / "app" / "services" / "monitoring_api_service.py",
        ROOT / "app" / "api" / "routes" / "monitoring.py",
    ]
    for path in paths:
        assert "stage110" not in path.read_text(encoding="utf-8").lower()


def test_bad_sort_400() -> None:
    client, _ = _make_client()
    assert client.get("/api/monitoring/videos?sort=invalid").status_code == 400


def test_breakout_v1_sort_metadata() -> None:
    client, factory = _make_client()
    session = factory()
    pub = NOW - timedelta(hours=12)
    _seed_video(session, "bv2", published_at=pub, views=2000, title="Lower VPH")
    _seed_video(session, "bv1", published_at=pub, views=5000, title="Higher VPH")
    session.add(
        VideoSnapshot(
            video_id="bv1",
            channel_id="ch1",
            captured_at=NOW,
            published_at=pub,
            age_hours=12.0,
            views=5000,
            vph=120.0,
            source="test",
            run_id="b1",
        ),
    )
    session.add(
        VideoSnapshot(
            video_id="bv2",
            channel_id="ch1",
            captured_at=NOW,
            published_at=pub,
            age_hours=12.0,
            views=2000,
            vph=80.0,
            source="test",
            run_id="b2",
        ),
    )
    session.commit()
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        body = client.get("/api/monitoring/videos?sort=breakout_v1").json()
    assert body["items"]
    top = body["items"][0]
    assert top["video_id"] == "bv1"
    assert top["breakout_rank"] == 1
    assert top["breakout_rank_version"] == "breakout_v1"
    assert top["breakout_ranking_signal"] == "vph"
    assert top["breakout_ranking_value"] == 120.0
    assert top["in_active_capture_pool"] is True


def test_priority_sort_no_breakout_fields() -> None:
    client, factory = _make_client()
    session = factory()
    _seed_video(session, "v1", published_at=NOW - timedelta(hours=10), views=100)
    _seed_monitoring_queue(session)
    with patch("app.services.monitoring_api_service.utc_now", return_value=NOW):
        item = client.get("/api/monitoring/videos?sort=priority").json()["items"][0]
    assert item.get("breakout_rank") is None
    assert item.get("breakout_rank_version") is None


def test_worker_status_running() -> None:
    client, factory = _make_client()
    session = factory()
    acquire_monitoring_worker_lock(session, holder="test-host")
    session.commit()
    response = client.get("/api/monitoring/status")
    assert response.json()["status"] == "running"


def _run_script(name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(f"{name}: {result.stderr or result.stdout}")


def test_regressions() -> None:
    _run_script("test_monitoring_worker.py")
    _run_script("test_video_snapshot_storage.py")
    _run_script("test_breakout_ranking.py")
    _run_script("test_monitoring_sql_pagination.py")


def main() -> None:
    tests = [
        test_status_endpoint_valid,
        test_overview_no_worker_state,
        test_overview_with_latest_cycle,
        test_video_list_pagination,
        test_tier_filter,
        test_status_filter_due,
        test_default_sort_deterministic,
        test_list_uses_latest_snapshot_metrics,
        test_missing_snapshot_fallback,
        test_detail_endpoint,
        test_unknown_video_404,
        test_checkpoint_planner_on_detail,
        test_snapshot_history_chronological,
        test_cycle_history_newest_first,
        test_nullable_subscribers_on_snapshots,
        test_baseline_on_detail_explicit,
        test_list_no_baseline_computation,
        test_list_unavailable_without_queue,
        test_list_live_planner_diagnostic,
        test_frozen_stage110_not_referenced,
        test_bad_sort_400,
        test_breakout_v1_sort_metadata,
        test_priority_sort_no_breakout_fields,
        test_worker_status_running,
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
    print("All monitoring API tests passed.")


if __name__ == "__main__":
    main()
