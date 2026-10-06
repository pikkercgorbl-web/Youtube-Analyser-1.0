"""Regression tests for format enrichment candidate selection (Stage 2.5)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.integrations.youtube.client import YouTubeChannelDetails, YouTubeVideoDetails
from app.models.orm import Base, Channel, Video, VideoFormat, VideoFormatEnrichmentAttempt
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN, SUBSCRIBERS_API_MISSING
from app.services.radar_enrichment_config import RadarEnrichmentSettings
from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
from app.services.radar_enrichment_selection import (
    RadarEnrichmentPassContext,
    select_format_enrichment_video_ids,
)
from app.services.video_format_outcomes import OUTCOME_FAILED, OUTCOME_MISSING


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _channel(session, cid: str, *, status: str | None, subs: int = 100):
    session.add(
        Channel(
            id=cid,
            title="c",
            subscribers_count=subs,
            subscribers_api_status=status,
            subscribers_api_checked_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        ),
    )


def _video(session, vid: str, cid: str, fmt: VideoFormat = VideoFormat.UNKNOWN):
    session.add(
        Video(
            id=vid,
            title="t",
            channel_id=cid,
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_format=fmt,
            views_count=100,
        ),
    )


def test_many_ineligible_then_sixty_eligible_selects_fifty() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    for i in range(2000):
        cid = f"bad{i:04d}"
        _channel(session, cid, status=SUBSCRIBERS_API_MISSING, subs=0)
        _video(session, f"v{i:06d}", cid)
    for i in range(60):
        cid = f"good{i:04d}"
        _channel(session, cid, status=SUBSCRIBERS_API_KNOWN, subs=500)
        _video(session, f"z{i:06d}", cid)
    session.commit()

    picked = select_format_enrichment_video_ids(
        session,
        limit=50,
        context=RadarEnrichmentPassContext(pass_sequence=0),
        now=now,
    )
    assert len(picked) == 50
    assert all(vid.startswith("z") for vid in picked)


def test_zero_eligible_touched_channels_still_fills_from_backlog() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "touched", status=SUBSCRIBERS_API_MISSING, subs=0)
    _video(session, "v_touch", "touched")
    _channel(session, "backlog", status=SUBSCRIBERS_API_KNOWN, subs=100)
    for i in range(10):
        _video(session, f"v_back_{i:02d}", "backlog")
    session.commit()

    picked = select_format_enrichment_video_ids(
        session,
        limit=5,
        context=RadarEnrichmentPassContext(),
        priority_channel_ids=frozenset({"touched"}),
        now=now,
    )
    assert len(picked) == 5
    assert all(vid.startswith("v_back_") for vid in picked)


def test_dry_run_and_live_selection_match_when_data_unchanged() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100)
    for i in range(3):
        _video(session, f"v{i}", "c1")
    session.commit()

    direct = select_format_enrichment_video_ids(
        session,
        limit=3,
        context=RadarEnrichmentPassContext(pass_sequence=2),
        priority_channel_ids=frozenset({"c1"}),
        now=now,
    )

    class Client:
        def get_channels(self, ids):
            return {
                cid: YouTubeChannelDetails(
                    channel_id=cid,
                    title="c",
                    subscribers_count=100,
                    subscribers_known=True,
                )
                for cid in ids
            }

        def get_videos(self, ids):
            return [
                YouTubeVideoDetails(
                    video_id=vid,
                    channel_id="c1",
                    title="t",
                    published_at=now,
                    views_count=100,
                    likes_count=0,
                    comments_count=0,
                    duration_seconds=120,
                    live_broadcast_content="none",
                )
                for vid in ids
            ]

    dry = run_radar_enrichment_pass(
        session,
        Client(),
        context=RadarEnrichmentPassContext(pass_sequence=2),
        dry_run=True,
        now=now,
    )
    session.rollback()
    live = run_radar_enrichment_pass(
        session,
        Client(),
        context=RadarEnrichmentPassContext(pass_sequence=2),
        dry_run=False,
        now=now,
    )
    session.rollback()

    assert direct == ["v0", "v1", "v2"]
    assert dry.format_videos_planned == 3
    assert live.format_videos_planned == 3
    assert dry.format_videos_planned == live.format_videos_planned


def test_missing_failed_respect_retry_cooldown() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100)
    _video(session, "v_miss", "c1")
    _video(session, "v_fail", "c1")
    session.add_all(
        [
            VideoFormatEnrichmentAttempt(
                video_id="v_miss",
                last_attempt_at=now - timedelta(hours=1),
                last_outcome=OUTCOME_MISSING,
            ),
            VideoFormatEnrichmentAttempt(
                video_id="v_fail",
                last_attempt_at=now - timedelta(hours=1),
                last_outcome=OUTCOME_FAILED,
            ),
        ],
    )
    session.commit()
    settings = RadarEnrichmentSettings(format_enrichment_retry_after_hours=6)
    ids = select_format_enrichment_video_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
        settings=settings,
        now=now,
    )
    assert ids == []

    later = now + timedelta(hours=7)
    ids_later = select_format_enrichment_video_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
        settings=settings,
        now=later,
    )
    assert set(ids_later) == {"v_miss", "v_fail"}


def test_selection_order_deterministic_for_pass_sequence() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100)
    for i in range(4):
        _video(session, f"v{i}", "c1")
    session.commit()
    ctx = RadarEnrichmentPassContext(pass_sequence=7)
    first = select_format_enrichment_video_ids(session, limit=4, context=ctx, now=now)
    second = select_format_enrichment_video_ids(session, limit=4, context=ctx, now=now)
    assert first == second
    assert set(first) == {"v0", "v1", "v2", "v3"}


def main() -> int:
    test_many_ineligible_then_sixty_eligible_selects_fifty()
    test_zero_eligible_touched_channels_still_fills_from_backlog()
    test_dry_run_and_live_selection_match_when_data_unchanged()
    test_missing_failed_respect_retry_cooldown()
    test_selection_order_deterministic_for_pass_sequence()
    print("OK format enrichment selection regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
