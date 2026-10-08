"""Regression: discovery-time VPH bootstrap → tier → first due monitoring capture (offline)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import Channel, KeywordDiscoveryHit, TargetKeyword, Video, VideoFormat, VideoFormatEnrichmentAttempt
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
from app.services.metrics import utc_now
from app.services.monitoring_cycle import run_monitoring_cycle
from app.services.monitoring_video_source import load_monitored_video_states
from app.services.video_published_at import PUBLISHED_AT_SOURCE_API

UTC = timezone.utc


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_no_snapshot_with_discovery(
    session,
    *,
    video_id: str = "boot1",
    published_at: datetime,
    discovered_at: datetime,
    views_at_discovery: int,
) -> datetime:
    """Known subs, API published_at, confirmed_regular, discovery hit — no VideoSnapshot."""
    session.add(
        Channel(
            id="ch1",
            title="Ch",
            subscribers_count=5000,
            subscribers_api_status=SUBSCRIBERS_API_KNOWN,
            subscribers_api_checked_at=published_at,
            created_at=published_at,
        ),
    )
    session.add(
        Video(
            id=video_id,
            title="Boot video",
            channel_id="ch1",
            views_count=999_999,
            likes_count=0,
            comments_count=0,
            published_at=published_at,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            duration_seconds=600,
            content_format=VideoFormat.MEDIUM,
        ),
    )
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id=video_id,
            last_attempt_at=discovered_at,
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
        ),
    )
    session.add(TargetKeyword(id=1, keyword="kw", lifecycle_status="active"))
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id=video_id,
            channel_id="ch1",
            discovery_run_id="run1",
            discovered_at=discovered_at,
            views_at_discovery=views_at_discovery,
        ),
    )
    session.commit()
    cycle_now = discovered_at + timedelta(hours=7)
    return cycle_now


class _MockClient:
    def get_videos(self, video_ids: list[str]):
        from app.integrations.youtube.client import YouTubeVideoDetails

        return [
            YouTubeVideoDetails(
                video_id=vid,
                channel_id="ch1",
                title="t",
                published_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                views_count=5000,
                likes_count=0,
                comments_count=0,
                duration_seconds=600,
            )
            for vid in video_ids
        ]


def test_load_bootstraps_vph_from_discovery_not_views_count() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    disc = pub + timedelta(hours=6)
    session = _session()
    now = _seed_no_snapshot_with_discovery(
        session,
        published_at=pub,
        discovered_at=disc,
        views_at_discovery=6000,
    )
    state = load_monitored_video_states(session, now=now)[0]
    assert state.raw_vph == round(6000 / 6.0, 4)
    assert state.raw_vph != round(999_999 / 7.0, 4)


def test_exploration_only_no_hit_stays_missing_vph() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    session = _session()
    session.add(
        Channel(
            id="ch1",
            title="Ch",
            subscribers_count=100,
            subscribers_api_status=SUBSCRIBERS_API_KNOWN,
            subscribers_api_checked_at=pub,
            created_at=pub,
        ),
    )
    session.add(
        Video(
            id="expl1",
            title="Expl only",
            channel_id="ch1",
            views_count=5000,
            published_at=pub,
            published_at_source=PUBLISHED_AT_SOURCE_API,
            content_format=VideoFormat.MEDIUM,
            duration_seconds=60,
        ),
    )
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id="expl1",
            last_attempt_at=pub,
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
        ),
    )
    session.commit()
    now = pub + timedelta(hours=10)
    states = load_monitored_video_states(session, now=now)
    assert len(states) == 1
    assert states[0].raw_vph is None


def test_full_path_first_due_capture_without_prior_snapshot() -> None:
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    disc = pub + timedelta(hours=6)
    session = _session()
    now = _seed_no_snapshot_with_discovery(
        session,
        published_at=pub,
        discovered_at=disc,
        views_at_discovery=12_000,
    )
    client = _MockClient()
    summary = run_monitoring_cycle(
        session,
        youtube_client=client,
        dry_run=False,
        current_time=now,
        run_id="monitoring_bootstrap_test_abcd1234",
    )
    assert summary.loaded_video_count >= 1
    assert summary.eligible_video_count >= 1
    assert summary.due_count + summary.overdue_count >= 1
    assert summary.selected_request_count >= 1
    assert summary.inserted_snapshot_count >= 1
    assert client.get_videos  # mock was callable


def test_stale_age_unmonitored_not_policy_bypass() -> None:
    """Age > 72h → stale_discovery_age; no capture even with discovery VPH."""
    pub = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    disc = pub + timedelta(hours=6)
    session = _session()
    now = _seed_no_snapshot_with_discovery(
        session,
        published_at=pub,
        discovered_at=disc,
        views_at_discovery=6000,
    )
    now = pub + timedelta(hours=80)
    summary = run_monitoring_cycle(
        session,
        youtube_client=_MockClient(),
        dry_run=True,
        current_time=now,
    )
    assert summary.eligible_video_count == 0
    assert summary.selected_request_count == 0


def main() -> int:
    test_load_bootstraps_vph_from_discovery_not_views_count()
    test_exploration_only_no_hit_stays_missing_vph()
    test_full_path_first_due_capture_without_prior_snapshot()
    test_stale_age_unmonitored_not_policy_bypass()
    print("OK monitoring bootstrap discovery to capture regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
