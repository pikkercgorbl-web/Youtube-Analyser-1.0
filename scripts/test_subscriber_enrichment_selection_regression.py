"""Regression tests for subscriber enrichment selection (Stage 2)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import (
    Base,
    Channel,
    ChannelSubscriberEnrichmentAttempt,
    Video,
    VideoFormat,
)
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_HIDDEN, SUBSCRIBERS_API_KNOWN
from app.services.radar_enrichment_config import RadarEnrichmentSettings
from app.services.radar_enrichment_selection import (
    RadarEnrichmentPassContext,
    select_subscriber_enrichment_channel_ids,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _channel(session, cid: str, *, status: str | None, checked_at: datetime | None):
    session.add(
        Channel(
            id=cid,
            title="c",
            subscribers_count=0,
            subscribers_api_status=status,
            subscribers_api_checked_at=checked_at,
            created_at=datetime.now(timezone.utc),
        ),
    )


def test_thousands_on_cooldown_still_fills_batch() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    settings = RadarEnrichmentSettings(subscriber_hidden_cooldown_hours=720)
    for i in range(2000):
        _channel(
            session,
            f"cool{i:04d}",
            status=SUBSCRIBERS_API_HIDDEN,
            checked_at=now - timedelta(hours=1),
        )
    for i in range(60):
        _channel(
            session,
            f"ok{i:04d}",
            status=None,
            checked_at=None,
        )
    session.commit()
    picked = select_subscriber_enrichment_channel_ids(
        session,
        limit=50,
        context=RadarEnrichmentPassContext(pass_sequence=0),
        settings=settings,
        now=now,
    )
    assert len(picked) == 50
    assert all(cid.startswith("ok") for cid in picked)


def test_orphan_without_channel_respects_attempt_cooldown() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    settings = RadarEnrichmentSettings(subscriber_retry_after_hours=6)
    session.add(
        Video(
            id="v1",
            title="t",
            channel_id="orphan1",
            published_at=now,
            content_format=VideoFormat.MEDIUM,
            views_count=1,
        ),
    )
    session.add(
        ChannelSubscriberEnrichmentAttempt(
            channel_id="orphan1",
            last_attempt_at=now - timedelta(hours=1),
            last_outcome="failed",
        ),
    )
    session.commit()
    assert (
        select_subscriber_enrichment_channel_ids(
            session,
            limit=10,
            context=RadarEnrichmentPassContext(),
            settings=settings,
            now=now,
        )
        == []
    )
    later = now + timedelta(hours=7)
    assert select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
        settings=settings,
        now=later,
    ) == ["orphan1"]


def test_backlog_and_recent_both_get_slots_with_constant_inflow() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    settings = RadarEnrichmentSettings(
        enrichment_backlog_pass_fraction=0.2,
        format_recent_hit_hours=48,
    )
    for i in range(30):
        _channel(session, f"back{i:02d}", status=SUBSCRIBERS_API_KNOWN, checked_at=now - timedelta(days=30))
    session.commit()
    picked = select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(pass_sequence=0),
        settings=settings,
        now=now,
    )
    assert len(picked) == 10
    assert len(set(picked)) == 10


def test_stable_tie_break_by_channel_id() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    for cid in ("b", "a", "c"):
        _channel(session, cid, status=None, checked_at=None)
    session.commit()
    ctx = RadarEnrichmentPassContext(pass_sequence=0)
    first = select_subscriber_enrichment_channel_ids(session, limit=3, context=ctx, now=now)
    second = select_subscriber_enrichment_channel_ids(session, limit=3, context=ctx, now=now)
    assert first == second
    assert len(first) == 3


def main() -> int:
    test_thousands_on_cooldown_still_fills_batch()
    test_orphan_without_channel_respects_attempt_cooldown()
    test_backlog_and_recent_both_get_slots_with_constant_inflow()
    test_stable_tie_break_by_channel_id()
    print("OK subscriber enrichment selection regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
