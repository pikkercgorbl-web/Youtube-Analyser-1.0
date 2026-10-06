"""Tests for discovery cycle profiling (Stage 1.20E.5)."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import TargetKeyword
from app.services.discovery_cycle import DiscoveryCycleConfig, run_discovery_cycle_async
from app.services.discovery_cycle_profiling import DiscoveryProfiler
from app.services.discovery_keyword_scan import KeywordDiscoveryScanResult

UTC = timezone.utc


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _video(vid: str) -> VideoSearchModel:
    return VideoSearchModel(
        video_id=vid,
        channel_id="ch1",
        channel_title="C",
        title=f"T {vid}",
        views_count=50_000,
        published_text="1 day ago",
        duration_text="10:00",
    )


def _scan(keyword: str, kid: int, videos: list[VideoSearchModel], **kwargs) -> KeywordDiscoveryScanResult:
    return KeywordDiscoveryScanResult(
        keyword=keyword,
        keyword_id=kid,
        raw_candidate_count=kwargs.get("raw_candidate_count", len(videos)),
        unique_videos=videos,
        qualification_passed_count=kwargs.get("qualification_passed_count", 0),
        qualification_rejected_count=kwargs.get("qualification_rejected_count", len(videos)),
        profile_phase_seconds=kwargs.get(
            "profile_phase_seconds",
            {"fetch": 0.1, "parse": 0.01, "qualification": 0.2, "channel_enrichment": 0.0, "database": 0.0},
        ),
        innertube_metrics_summary={"request_count": 2, "max_duration_ms": 100.0},
        filter_metrics_summary={"html_fallback_count": 0, "discovered_videos": 10, "format_skips": 0, "unique_channels": 1},
    )


async def _run_cycle(session, *, profile: bool, side_effect) -> tuple:
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        TargetKeyword(
            keyword="kw-a",
            lifecycle_status="active",
            next_scan_at=now - timedelta(hours=1),
        ),
    )
    session.commit()
    with patch(
        "app.services.discovery_cycle.scan_keyword_for_discovery",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ):
        buf = io.StringIO()
        with redirect_stdout(buf):
            outcome = await run_discovery_cycle_async(
                session,
                config=DiscoveryCycleConfig(keyword_batch_size=5, profile=profile),
                dry_run=True,
            )
        return outcome, buf.getvalue()


def test_profile_disabled_no_summary() -> None:
    import asyncio

    session = sessionmaker(bind=_engine())()

    async def _one(*_a, **_k):
        return _scan("kw-a", 1, [_video("v1")])

    outcome, out = asyncio.run(_run_cycle(session, profile=False, side_effect=_one))
    assert outcome.summary.cycle_status == "dry_run"
    assert "DISCOVERY PROFILE" not in out


def test_profile_records_keywords_and_sql() -> None:
    import asyncio

    session = sessionmaker(bind=_engine())()

    async def _one(*_a, **_k):
        return _scan("kw-a", 1, [_video("v1"), _video("v2")], qualification_rejected_count=3)

    outcome, out = asyncio.run(_run_cycle(session, profile=True, side_effect=_one))
    assert outcome.summary.unique_video_count == 2
    assert outcome.summary.qualification_rejected_count == 3
    assert "DISCOVERY PROFILE" in out
    assert "kw-a" in out
    assert "SQL:" in out


def test_profile_dry_run_same_counts_as_without() -> None:
    import asyncio

    session = sessionmaker(bind=_engine())()

    async def _one(*_a, **_k):
        return _scan(
            "kw-a",
            1,
            [_video("v1")],
            qualification_passed_count=1,
            qualification_rejected_count=2,
        )

    off, _ = asyncio.run(_run_cycle(sessionmaker(bind=_engine())(), profile=False, side_effect=_one))
    on, _ = asyncio.run(_run_cycle(sessionmaker(bind=_engine())(), profile=True, side_effect=_one))
    assert off.summary.unique_video_count == on.summary.unique_video_count
    assert off.summary.qualification_rejected_count == on.summary.qualification_rejected_count


def test_failed_keyword_still_prints_summary() -> None:
    import asyncio

    session = sessionmaker(bind=_engine())()
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    session.add(
        TargetKeyword(keyword="fail-kw", lifecycle_status="active", next_scan_at=now - timedelta(hours=1)),
    )
    session.commit()

    async def _boom(*_a, **_k):
        raise RuntimeError("fetch failed")

    buf = io.StringIO()
    with patch(
        "app.services.discovery_cycle.scan_keyword_for_discovery",
        new_callable=AsyncMock,
        side_effect=_boom,
    ):
        with redirect_stdout(buf):
            outcome = asyncio.run(
                run_discovery_cycle_async(
                    session,
                    config=DiscoveryCycleConfig(profile=True),
                    dry_run=True,
                ),
            )
    assert outcome.summary.failed_keyword_count == 1
    assert "DISCOVERY PROFILE" in buf.getvalue()


def test_sql_truncation_no_huge_params() -> None:
    profiler = DiscoveryProfiler()
    long_sql = "SELECT * FROM videos WHERE id IN (" + ",".join(["?"] * 5000) + ")"
    from app.services.discovery_cycle_profiling import _truncate_sql

    truncated = _truncate_sql(long_sql)
    assert len(truncated) <= 240
    assert not truncated.endswith("?" * 500)


def test_rejected_gt_unique_semantics_documented_in_scan() -> None:
    """Candidates list counts per appearance; unique_videos dedupes by id."""
    session = sessionmaker(bind=_engine())()
    # Simulate two candidates same video_id (two pages)
    v = _video("dup")
    result = KeywordDiscoveryScanResult(
        keyword="k",
        raw_candidate_count=2,
        unique_videos=[v],
        candidates=[],
        qualification_rejected_count=2,
        qualification_passed_count=0,
    )
    from app.services.radar_candidate import QUALIFICATION_REJECTED, RadarCandidate

    result.candidates = [
        RadarCandidate.from_video_search(v, keyword="k", discovery_source="innertube"),
        RadarCandidate.from_video_search(v, keyword="k", discovery_source="innertube"),
    ]
    for c in result.candidates:
        c.qualification_state = QUALIFICATION_REJECTED
    assert len(result.unique_videos) == 1
    assert result.qualification_rejected_count == 2


def main() -> None:
    tests = [
        test_profile_disabled_no_summary,
        test_profile_records_keywords_and_sql,
        test_profile_dry_run_same_counts_as_without,
        test_failed_keyword_still_prints_summary,
        test_sql_truncation_no_huge_params,
        test_rejected_gt_unique_semantics_documented_in_scan,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")


if __name__ == "__main__":
    main()
