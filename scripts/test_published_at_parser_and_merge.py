"""Regression tests for published_at parser and merge policy."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import YouTubeVideoDetails
from app.models.db import Base
from app.models.orm import Video, VideoFormat
from app.services.discovered_video_persistence import persist_discovered_video
from app.integrations.youtube.client import VideoSearchModel
from app.services.video_filter_service import parse_relative_published_date
from app.services.video_format_persistence import apply_api_details_to_video_content_format
from app.services.metrics import ensure_utc
from app.services.video_published_at import (
    PUBLISHED_AT_SOURCE_API,
    PUBLISHED_AT_SOURCE_INNERTUBE,
)

UTC = timezone.utc
REF = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)


def test_hours_ago_not_collapsed_to_now() -> None:
    parsed = parse_relative_published_date("3 hours ago", reference=REF)
    assert parsed == REF - timedelta(hours=3)


def test_minutes_ago_parsed() -> None:
    parsed = parse_relative_published_date("45 minutes ago", reference=REF)
    assert parsed == REF - timedelta(minutes=45)


def test_api_published_at_not_overwritten_by_innertube_rediscovery() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    api_time = datetime(2026, 10, 1, 8, 30, 0, tzinfo=UTC)
    innertube_time = datetime(2026, 10, 6, 11, 59, 0, tzinfo=UTC)
    row = Video(
        id="vid1",
        title="t",
        views_count=1,
        published_at=api_time,
        published_at_source=PUBLISHED_AT_SOURCE_API,
        duration_seconds=100,
        content_format=VideoFormat.MEDIUM,
        channel_id="ch1",
    )
    session.add(row)
    session.commit()
    video = VideoSearchModel(
        video_id="vid1",
        channel_id="ch1",
        channel_title="Ch",
        title="t",
        views_count=2,
        published_text="just now",
        duration_text="10:00",
        subscribers_count=0,
    )
    persist_discovered_video(session, video, discovery_keyword="kw")
    session.flush()
    session.refresh(row)
    assert ensure_utc(row.published_at) == api_time
    assert row.published_at_source == PUBLISHED_AT_SOURCE_API


def test_format_enrichment_sets_api_published_at() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    approx = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)
    api_time = datetime(2026, 10, 5, 14, 22, 33, tzinfo=UTC)
    row = Video(
        id="vid2",
        title="t",
        views_count=1,
        published_at=approx,
        published_at_source=PUBLISHED_AT_SOURCE_INNERTUBE,
        duration_seconds=100,
        content_format=VideoFormat.UNKNOWN,
        channel_id="ch1",
    )
    session.add(row)
    details = YouTubeVideoDetails(
        video_id="vid2",
        channel_id="ch1",
        title="t",
        published_at=api_time,
        views_count=10,
        likes_count=0,
        comments_count=0,
        duration_seconds=600,
    )
    apply_api_details_to_video_content_format(row, details)
    assert ensure_utc(row.published_at) == api_time
    assert row.published_at_source == PUBLISHED_AT_SOURCE_API


def main() -> None:
    tests = [
        test_hours_ago_not_collapsed_to_now,
        test_minutes_ago_parsed,
        test_api_published_at_not_overwritten_by_innertube_rediscovery,
        test_format_enrichment_sets_api_published_at,
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
    print("All published_at tests passed.")


if __name__ == "__main__":
    main()
