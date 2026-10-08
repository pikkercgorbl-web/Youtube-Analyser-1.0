"""Stage 2.5: Radar enrichment orchestrator tests (no network)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.integrations.youtube.client import YouTubeChannelDetails, YouTubeVideoDetails
from app.models.orm import (
    Base,
    Channel,
    ChannelSubscriberEnrichmentAttempt,
    KeywordDiscoveryHit,
    RadarApiBudgetDay,
    Video,
    VideoFormat,
    VideoFormatEnrichmentAttempt,
)
from app.services.channel_subscriber_backfill import (
    SUBSCRIBERS_API_HIDDEN,
    SUBSCRIBERS_API_KNOWN,
    SUBSCRIBERS_API_MISSING,
)
from app.services.channel_subscriber_enrichment import (
    REASON_API_ITEM_UPSERTED,
    apply_subscriber_enrichment_batch,
)
from app.services.video_format_outcomes import OUTCOME_CONFIRMED_REGULAR
from app.services.monitoring_video_source import load_monitored_video_states
from app.services.radar_api_budget import (
    BUDGET_KIND_CHANNELS_LIST,
    BUDGET_KIND_VIDEOS_LIST,
    try_reserve_id_units,
    utc_calendar_day,
)
from app.services.radar_enrichment_config import RadarEnrichmentSettings
from app.services.radar_enrichment_orchestrator import run_radar_enrichment_pass
from app.services.radar_enrichment_selection import (
    RadarEnrichmentPassContext,
    select_format_enrichment_video_ids,
    select_subscriber_enrichment_channel_ids,
)
from app.services.radar_target_eligibility import RADAR_MAX_CHANNEL_SUBSCRIBERS


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _channel(session, cid: str, *, status: str | None = None, subs: int = 100, checked_at: datetime | None = None):
    session.add(
        Channel(
            id=cid,
            title="c",
            subscribers_count=subs,
            subscribers_api_status=status,
            subscribers_api_checked_at=checked_at,
            created_at=datetime.now(timezone.utc),
        ),
    )


def _video(session, vid: str, cid: str, fmt: VideoFormat, *, views: int = 1000):
    session.add(
        Video(
            id=vid,
            title="t",
            channel_id=cid,
            published_at=datetime.now(timezone.utc),
            content_format=fmt,
            views_count=views,
        ),
    )


def test_pass_runs_without_discovery_results() -> None:
    session = _session()
    client = MagicMock()
    report = run_radar_enrichment_pass(
        session,
        client,
        context=RadarEnrichmentPassContext(pass_sequence=1),
        dry_run=True,
    )
    assert report.dry_run is True
    client.get_channels.assert_not_called()
    client.get_videos.assert_not_called()


def test_dry_run_and_budget_read_do_not_create_ledger_rows() -> None:
    from app.services.radar_api_budget import BUDGET_KIND_CHANNELS_LIST, count_budget_rows, remaining_id_units
    from app.services.radar_enrichment_config import radar_enrichment_settings

    session = _session()
    now = datetime.now(timezone.utc)
    assert count_budget_rows(session) == 0
    remaining_id_units(
        session,
        budget_kind=BUDGET_KIND_CHANNELS_LIST,
        daily_limit=radar_enrichment_settings.channel_subscriber_enrichment_daily_limit,
        now=now,
    )
    assert count_budget_rows(session) == 0
    run_radar_enrichment_pass(
        session,
        MagicMock(),
        context=RadarEnrichmentPassContext(pass_sequence=0),
        dry_run=True,
        now=now,
    )
    assert count_budget_rows(session) == 0


def test_format_selection_skips_over_100k_subscribers() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "big", status=SUBSCRIBERS_API_KNOWN, subs=RADAR_MAX_CHANNEL_SUBSCRIBERS + 1, checked_at=now)
    _video(session, "v1", "big", VideoFormat.UNKNOWN)
    session.commit()
    ids = select_format_enrichment_video_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
    )
    assert ids == []


def test_format_selection_does_not_require_snapshots() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=500, checked_at=now)
    _video(session, "v1", "c1", VideoFormat.UNKNOWN)
    session.commit()
    ids = select_format_enrichment_video_ids(session, limit=10, context=RadarEnrichmentPassContext())
    assert ids == ["v1"]


def test_hidden_channel_cooldown_blocks_repeat() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(
        session,
        "hidden1",
        status=SUBSCRIBERS_API_HIDDEN,
        subs=0,
        checked_at=now - timedelta(hours=1),
    )
    session.commit()
    settings = RadarEnrichmentSettings(subscriber_hidden_cooldown_hours=720)
    ids = select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
        settings=settings,
        now=now,
    )
    assert "hidden1" not in ids


def test_backlog_gets_turn_via_pass_sequence() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _channel(session, "c2", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _video(session, "old1", "c1", VideoFormat.UNKNOWN, views=10)
    _video(session, "old2", "c2", VideoFormat.UNKNOWN, views=10)
    session.commit()
    for seq in range(12):
        picked = select_format_enrichment_video_ids(
            session,
            limit=2,
            context=RadarEnrichmentPassContext(pass_sequence=seq),
            now=now,
        )
        assert set(picked) == {"old1", "old2"}


def test_daily_budget_blocks_concurrent_reservations() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    day = utc_calendar_day(now)
    session.add(
        RadarApiBudgetDay(
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            utc_day=day,
            id_units_reserved=195,
            http_requests=0,
        ),
    )
    session.commit()
    r1 = try_reserve_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        unit_count=10,
        daily_limit=200,
        now=now,
    )
    assert r1.reserved == 5
    session.commit()
    r2 = try_reserve_id_units(
        session,
        budget_kind=BUDGET_KIND_VIDEOS_LIST,
        unit_count=10,
        daily_limit=200,
        now=now,
    )
    assert r2.reserved == 0


def test_repeated_video_attempts_do_not_inflate_budget_via_attempt_rows() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id="v1",
            last_attempt_at=now,
            last_outcome="missing",
        ),
    )
    session.commit()
    for _ in range(3):
        try_reserve_id_units(
            session,
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            unit_count=1,
            daily_limit=200,
            now=now,
        )
        session.commit()
    row = session.scalar(
        select(RadarApiBudgetDay.id_units_reserved).where(
            RadarApiBudgetDay.budget_kind == BUDGET_KIND_VIDEOS_LIST,
        ),
    )
    assert row == 3
    attempt_count = session.scalar(select(func.count()).select_from(VideoFormatEnrichmentAttempt))
    assert attempt_count == 1


def test_monitoring_gate_requires_confirmed_regular() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _video(session, "v1", "c1", VideoFormat.MEDIUM)
    session.commit()
    assert load_monitored_video_states(session) == []
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id="v1",
            last_attempt_at=now,
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
        ),
    )
    session.commit()
    states = load_monitored_video_states(session)
    assert len(states) == 1
    assert states[0].video_id == "v1"


def test_orchestrator_dedup_within_pass() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _video(session, "v1", "c1", VideoFormat.UNKNOWN)
    session.commit()

    class Client:
        channel_calls = 0
        video_calls = 0

        def get_channels(self, ids):
            Client.channel_calls += 1
            return {
                "c1": YouTubeChannelDetails(
                    channel_id="c1",
                    title="c",
                    subscribers_count=100,
                    subscribers_known=True,
                ),
            }

        def get_videos(self, ids):
            Client.video_calls += 1
            return [
                YouTubeVideoDetails(
                    video_id="v1",
                    channel_id="c1",
                    title="t",
                    published_at=now,
                    views_count=100,
                    likes_count=0,
                    comments_count=0,
                    duration_seconds=120,
                    live_broadcast_content="none",
                ),
            ]

    settings = RadarEnrichmentSettings(
        channel_subscriber_enrichment_pass_limit=50,
        video_format_enrichment_pass_limit=50,
    )
    import app.services.radar_enrichment_orchestrator as orch_mod

    old = orch_mod.radar_enrichment_settings
    orch_mod.radar_enrichment_settings = settings
    try:
        ctx = RadarEnrichmentPassContext(
            cycle_video_ids=frozenset({"v1"}),
            cycle_channel_ids=frozenset({"c1"}),
            fetched_channel_ids=frozenset({"c1"}),
            fetched_video_ids=frozenset(),
            pass_sequence=1,
        )
        report = run_radar_enrichment_pass(session, Client(), context=ctx, dry_run=False, now=now)
    finally:
        orch_mod.radar_enrichment_settings = old
    assert Client.channel_calls == 0
    assert Client.video_calls == 1
    assert report.format_videos_processed == 1


def test_api_item_without_channel_row_upserts_and_persists_status() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _video(session, "v1", "orphan", VideoFormat.UNKNOWN)
    session.commit()
    details = {
        "orphan": YouTubeChannelDetails(
            channel_id="orphan",
            title="Orphan",
            subscribers_count=42,
            subscribers_known=True,
        ),
    }
    report = apply_subscriber_enrichment_batch(session, ["orphan"], details, attempted_at=now)
    session.commit()
    ch = session.get(Channel, "orphan")
    assert ch is not None
    assert ch.subscribers_api_status == SUBSCRIBERS_API_KNOWN
    assert report.outcomes[0].reason == REASON_API_ITEM_UPSERTED
    attempt = session.get(ChannelSubscriberEnrichmentAttempt, "orphan")
    assert attempt is not None
    assert attempt.last_outcome == SUBSCRIBERS_API_KNOWN


def test_missing_without_channel_persists_cooldown_and_blocks_reselect() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _video(session, "v1", "ghost", VideoFormat.UNKNOWN)
    session.commit()
    apply_subscriber_enrichment_batch(session, ["ghost"], {}, attempted_at=now)
    session.commit()
    assert session.get(Channel, "ghost") is None
    attempt = session.get(ChannelSubscriberEnrichmentAttempt, "ghost")
    assert attempt is not None
    assert attempt.last_outcome == SUBSCRIBERS_API_MISSING
    settings = RadarEnrichmentSettings(subscriber_retry_after_hours=6)
    ids = select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(),
        settings=settings,
        now=now,
    )
    assert "ghost" not in ids


def test_dry_run_does_not_mutate_fetched_rotation_state() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=None, subs=0)
    session.commit()
    ctx = RadarEnrichmentPassContext(pass_sequence=7, fetched_channel_ids=frozenset())
    client = MagicMock()
    report = run_radar_enrichment_pass(session, client, context=ctx, dry_run=True, now=now)
    assert report.subscriber_channels_planned >= 1
    client.get_channels.assert_not_called()
    ids_after = select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=ctx,
        now=now,
    )
    ids_fresh = select_subscriber_enrichment_channel_ids(
        session,
        limit=10,
        context=RadarEnrichmentPassContext(pass_sequence=7),
        now=now,
    )
    assert ids_after == ids_fresh


def test_new_known_channel_enables_format_selection_in_same_pass() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=None, subs=0)
    _video(session, "v1", "c1", VideoFormat.UNKNOWN)
    session.commit()

    class Client:
        def get_channels(self, ids):
            return {
                "c1": YouTubeChannelDetails(
                    channel_id="c1",
                    title="c",
                    subscribers_count=500,
                    subscribers_known=True,
                ),
            }

        def get_videos(self, ids):
            return [
                YouTubeVideoDetails(
                    video_id="v1",
                    channel_id="c1",
                    title="t",
                    published_at=now,
                    views_count=100,
                    likes_count=0,
                    comments_count=0,
                    duration_seconds=120,
                    live_broadcast_content="none",
                ),
            ]

    settings = RadarEnrichmentSettings(
        channel_subscriber_enrichment_pass_limit=50,
        video_format_enrichment_pass_limit=50,
    )
    import app.services.radar_enrichment_orchestrator as orch_mod

    old = orch_mod.radar_enrichment_settings
    orch_mod.radar_enrichment_settings = settings
    try:
        report = run_radar_enrichment_pass(
            session,
            Client(),
            context=RadarEnrichmentPassContext(pass_sequence=1),
            dry_run=False,
            now=now,
        )
    finally:
        orch_mod.radar_enrichment_settings = old
    assert report.subscriber_channels_processed >= 1
    assert report.format_videos_planned >= 1
    assert report.format_videos_processed >= 1
    diag = report.notes.get("format_selection_after_subscribers") or {}
    assert int(diag.get("selected_would_be", 0)) >= 1


def test_cycle_priority_over_backlog() -> None:
    session = _session()
    now = datetime.now(timezone.utc)
    _channel(session, "c1", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _channel(session, "c2", status=SUBSCRIBERS_API_KNOWN, subs=100, checked_at=now)
    _video(session, "backlog", "c1", VideoFormat.UNKNOWN, views=1)
    _video(session, "cycle", "c2", VideoFormat.UNKNOWN, views=99999)
    session.commit()
    ids = select_format_enrichment_video_ids(
        session,
        limit=1,
        context=RadarEnrichmentPassContext(cycle_video_ids=frozenset({"cycle"})),
    )
    assert ids == ["cycle"]


def main() -> int:
    tests = [
        test_pass_runs_without_discovery_results,
        test_dry_run_and_budget_read_do_not_create_ledger_rows,
        test_format_selection_skips_over_100k_subscribers,
        test_format_selection_does_not_require_snapshots,
        test_hidden_channel_cooldown_blocks_repeat,
        test_backlog_gets_turn_via_pass_sequence,
        test_daily_budget_blocks_concurrent_reservations,
        test_repeated_video_attempts_do_not_inflate_budget_via_attempt_rows,
        test_monitoring_gate_requires_confirmed_regular,
        test_orchestrator_dedup_within_pass,
        test_api_item_without_channel_row_upserts_and_persists_status,
        test_missing_without_channel_persists_cooldown_and_blocks_reselect,
        test_dry_run_does_not_mutate_fetched_rotation_state,
        test_new_known_channel_enables_format_selection_in_same_pass,
        test_cycle_priority_over_backlog,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
