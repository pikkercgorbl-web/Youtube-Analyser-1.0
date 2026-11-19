"""Stage 2: API format mapping, eligibility, metrics (no network)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import LiveBroadcastStatus, VideoSearchModel, YouTubeVideoDetails
from app.models.orm import Channel, Video, VideoFormat, VideoSnapshot
from app.services.attention_engine_types import AttentionEngineConfig
from app.services.attention_evidence import AttentionEvidenceBundle, AttentionVideoRecord
from app.services.attention_patterns import build_pattern_candidates
from app.services.attention_video_winners import build_video_winners
from app.services.discovery_cycle import DiscoveryCycleSummary
from app.services.keyword_discovery_metrics_storage import _content_format_label
from app.services.monitoring_video_source import _format_flags
from app.services.radar_target_eligibility import (
    RADAR_MAX_CHANNEL_SUBSCRIBERS,
    REJECTION_OVER_SUBSCRIBER_LIMIT,
    REJECTION_UNKNOWN_SUBSCRIBERS,
    radar_target_rejection_reason,
    resolve_known_subscribers,
)
from app.services.video_format_from_api import (
    chunk_video_ids,
    infer_video_format_from_videos_list_item,
    merge_api_content_format,
)


def _item(
    *,
    lbc: str | None = "none",
    duration: str = "PT120S",
    streaming: dict | None = None,
    video_id: str = "vid1",
) -> dict:
    snippet: dict = {"liveBroadcastContent": lbc} if lbc is not None else {}
    item = {
        "id": video_id,
        "snippet": snippet,
        "contentDetails": {"duration": duration},
    }
    if streaming is not None:
        item["liveStreamingDetails"] = streaming
    return item


def test_live_broadcast_content_mapping() -> None:
    assert infer_video_format_from_videos_list_item(_item(lbc="live")) == VideoFormat.LIVE
    assert infer_video_format_from_videos_list_item(_item(lbc="upcoming")) == VideoFormat.LIVE
    assert infer_video_format_from_videos_list_item(_item(lbc="none", duration="PT90S")) == VideoFormat.MEDIUM
    assert infer_video_format_from_videos_list_item(_item(lbc="none", duration="PT30S")) == VideoFormat.SHORT


def test_completed_broadcast_via_streaming_details() -> None:
    fmt = infer_video_format_from_videos_list_item(
        _item(lbc="none", duration="PT3600S", streaming={"actualEndTime": "2020-01-01T00:00:00Z"}),
    )
    assert fmt == VideoFormat.LIVE


def test_opaque_unknown_stays_unknown() -> None:
    assert infer_video_format_from_videos_list_item(_item(lbc=None, duration="PT0S")) is None
    assert infer_video_format_from_videos_list_item({"id": "x", "snippet": {}, "contentDetails": {}}) is None


def test_merge_does_not_downgrade_live() -> None:
    assert (
        merge_api_content_format(VideoFormat.LIVE, VideoFormat.MEDIUM)
        == VideoFormat.LIVE
    )
    assert merge_api_content_format(VideoFormat.LIVE, None) == VideoFormat.LIVE


def test_batch_chunks_fifty() -> None:
    ids = [f"v{i}" for i in range(125)]
    batches = chunk_video_ids(ids, batch_size=50)
    assert len(batches) == 3
    assert len(batches[0]) == 50
    assert len(batches[1]) == 50
    assert len(batches[2]) == 25


def test_partial_missing_not_regular() -> None:
    merged = merge_api_content_format(VideoFormat.UNKNOWN, None)
    assert merged == VideoFormat.UNKNOWN


def test_subscriber_limits() -> None:
    ch = Channel(
        id="UC1234567890123456789012",
        title="t",
        subscribers_count=RADAR_MAX_CHANNEL_SUBSCRIBERS,
        subscribers_api_status="known",
        created_at=datetime.now(timezone.utc),
    )
    assert radar_target_rejection_reason(
        content_format=VideoFormat.MEDIUM,
        channel=ch,
        latest_snapshot=None,
    ) is None
    ch_big = Channel(
        id="UC1234567890123456789012",
        title="t",
        subscribers_count=RADAR_MAX_CHANNEL_SUBSCRIBERS + 1,
        subscribers_api_status="known",
        created_at=datetime.now(timezone.utc),
    )
    assert (
        radar_target_rejection_reason(
            content_format=VideoFormat.MEDIUM,
            channel=ch_big,
            latest_snapshot=None,
        )
        == REJECTION_OVER_SUBSCRIBER_LIMIT
    )


def test_unknown_subscribers_not_zero() -> None:
    ch = Channel(
        id="UC1234567890123456789012",
        title="t",
        subscribers_count=0,
        created_at=datetime.now(timezone.utc),
    )
    assert resolve_known_subscribers(channel=ch, latest_snapshot=None) is None
    snap = VideoSnapshot(
        video_id="v",
        views=1,
        subscribers=0,
        vph=1.0,
        captured_at=datetime.now(timezone.utc),
    )
    assert resolve_known_subscribers(channel=ch, latest_snapshot=snap) == 0


def test_accelerating_cannot_bypass_format() -> None:
    now = datetime.now(timezone.utc)
    video = Video(
        id="v1",
        title="t",
        channel_id="c1",
        published_at=now,
        content_format=VideoFormat.UNKNOWN,
    )
    ch = Channel(
        id="c1",
        title="c",
        subscribers_count=100,
        subscribers_api_status="known",
        created_at=now,
    )
    rec = AttentionVideoRecord(
        video=video,
        channel=ch,
        latest_snapshot=None,
        snapshots=[],
        hits=[],
        state=MagicMock(breakout_eligible=False, raw_vph=100.0, age_hours=1.0),
        breakout_eligible=False,
        breakout_rank=None,
        subscribers=100,
        views=1000,
        vph=100.0,
    )
    bundle = AttentionEvidenceBundle(
        window_start=now,
        window_end=now,
        records={"v1": rec},
        hits_by_video={},
        hits_by_keyword={},
        keyword_text={},
        channel_snapshots={},
        channels_by_id={"c1": ch},
        extra_channel_videos={},
        extra_video_states={},
        extra_latest_snapshots={},
        extra_hits_by_video={},
    )
    winners = build_video_winners(bundle, AttentionEngineConfig(video_limit=50), now=now)
    assert winners == []


def test_top50_backfill_skips_ineligible() -> None:
    now = datetime.now(timezone.utc)

    def make_rec(vid: str, fmt: VideoFormat, subs: int, rank: int | None) -> AttentionVideoRecord:
        ch = Channel(
            id=f"ch_{vid}",
            title="c",
            subscribers_count=subs,
            subscribers_api_status="known",
            created_at=now,
        )
        video = Video(
            id=vid,
            title="t",
            channel_id=ch.id,
            published_at=now,
            content_format=fmt,
        )
        return AttentionVideoRecord(
            video=video,
            channel=ch,
            latest_snapshot=None,
            snapshots=[],
            hits=[],
            state=MagicMock(breakout_eligible=True, raw_vph=10.0, age_hours=2.0),
            breakout_eligible=True,
            breakout_rank=rank,
            subscribers=subs,
            views=100,
            vph=10.0,
        )

    records = {
        "bad": make_rec("bad", VideoFormat.LIVE, 100, 1),
        "good": make_rec("good", VideoFormat.MEDIUM, 100, 2),
    }
    bundle = AttentionEvidenceBundle(
        window_start=now,
        window_end=now,
        records=records,
        hits_by_video={},
        hits_by_keyword={},
        keyword_text={},
        channel_snapshots={},
        channels_by_id={records["good"].channel.id: records["good"].channel},
        extra_channel_videos={},
        extra_video_states={},
        extra_latest_snapshots={},
        extra_hits_by_video={},
    )
    winners = build_video_winners(bundle, AttentionEngineConfig(video_limit=50), now=now)
    assert len(winners) == 1
    assert winners[0].video_id == "good"


def test_pattern_counts_after_filter() -> None:
    now = datetime.now(timezone.utc)
    ch = Channel(
        id="c1",
        title="c",
        subscribers_count=50,
        subscribers_api_status="known",
        created_at=now,
    )
    good = Video(id="g1", title="hello world", channel_id="c1", published_at=now, content_format=VideoFormat.MEDIUM)
    bad = Video(id="b1", title="hello world", channel_id="c1", published_at=now, content_format=VideoFormat.UNKNOWN)
    rec_good = AttentionVideoRecord(
        video=good,
        channel=ch,
        latest_snapshot=None,
        snapshots=[],
        hits=[],
        state=MagicMock(breakout_eligible=True, raw_vph=1.0, age_hours=1.0),
        breakout_eligible=True,
        breakout_rank=1,
        subscribers=50,
        views=10,
        vph=1.0,
    )
    rec_bad = AttentionVideoRecord(
        video=bad,
        channel=ch,
        latest_snapshot=None,
        snapshots=[],
        hits=[],
        state=MagicMock(breakout_eligible=True, raw_vph=1.0, age_hours=1.0),
        breakout_eligible=True,
        breakout_rank=2,
        subscribers=50,
        views=10,
        vph=1.0,
    )
    bundle = AttentionEvidenceBundle(
        window_start=now,
        window_end=now,
        records={"g1": rec_good, "b1": rec_bad},
        hits_by_video={},
        hits_by_keyword={},
        keyword_text={},
        channel_snapshots={},
        channels_by_id={"c1": ch},
        extra_channel_videos={},
        extra_video_states={},
        extra_latest_snapshots={},
        extra_hits_by_video={},
    )
    patterns = build_pattern_candidates(
        bundle,
        AttentionEngineConfig(min_pattern_videos=2, min_pattern_channels=1),
        winners=[],
        now=now,
    )
    assert patterns == []


def test_metrics_unknown_and_completed() -> None:
    unknown = VideoSearchModel(
        video_id="v",
        channel_id="c",
        title="t",
        live_broadcast_status=LiveBroadcastStatus.UNKNOWN,
    )
    assert _content_format_label(unknown) == "unknown"
    completed = VideoSearchModel(
        video_id="v2",
        channel_id="c",
        title="t",
        live_broadcast_status=LiveBroadcastStatus.COMPLETED,
    )
    assert _content_format_label(completed) == "live"
    _, _, is_live = _format_flags(VideoFormat.LIVE)
    assert is_live is True


def test_discovery_summary_buckets() -> None:
    summary = DiscoveryCycleSummary(
        run_id="r",
        started_at=datetime.now(timezone.utc),
    )
    regular = VideoSearchModel(
        video_id="r1",
        channel_id="c",
        title="t",
        live_broadcast_status=LiveBroadcastStatus.NONE,
    )
    unknown = VideoSearchModel(
        video_id="u1",
        channel_id="c",
        title="t",
        live_broadcast_status=LiveBroadcastStatus.UNKNOWN,
    )
    from app.integrations.youtube.client import video_is_regular_item, video_is_stream_content

    for video in (regular,):
        if video_is_regular_item(video):
            summary.regular_video_count += 1
    for video in (unknown,):
        if video.live_broadcast_status == LiveBroadcastStatus.UNKNOWN:
            summary.unknown_format_count += 1
    assert summary.regular_video_count == 1
    assert summary.unknown_format_count == 1


def test_get_videos_requests_live_streaming_part() -> None:
    import inspect

    from app.integrations.youtube.client import YouTubeApiClient

    source = inspect.getsource(YouTubeApiClient.get_videos)
    assert "liveStreamingDetails" in source
    assert "snippet,statistics,contentDetails,liveStreamingDetails" in source.replace(" ", "")


def test_apply_api_details_persists_medium_to_live() -> None:
    from app.integrations.youtube.client import YouTubeVideoDetails
    from app.models.orm import Video
    from app.services.video_format_persistence import apply_api_details_to_video_content_format

    now = datetime.now(timezone.utc)
    video = Video(
        id="v",
        title="t",
        channel_id="c",
        published_at=now,
        content_format=VideoFormat.MEDIUM,
    )
    details = YouTubeVideoDetails(
        video_id="v",
        channel_id="c",
        title="t",
        published_at=now,
        views_count=1,
        likes_count=0,
        comments_count=0,
        duration_seconds=3600,
        live_broadcast_content="none",
        has_live_streaming_details=True,
    )
    before, after = apply_api_details_to_video_content_format(video, details)
    assert before == VideoFormat.MEDIUM
    assert after == VideoFormat.LIVE


def test_daily_budget_exhausted_skips_selection() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import Base, RadarApiBudgetDay, Video, VideoFormat
    from app.services.radar_api_budget import BUDGET_KIND_VIDEOS_LIST, utc_calendar_day
    from app.services.unknown_format_enrichment import select_unknown_video_ids_for_enrichment
    from app.services.unknown_format_enrichment_config import (
        DEFAULT_UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    now = datetime.now(timezone.utc)
    session.add(
        Video(
            id="u1",
            title="t",
            channel_id="c",
            published_at=now,
            content_format=VideoFormat.UNKNOWN,
        ),
    )
    session.add(
        RadarApiBudgetDay(
            budget_kind=BUDGET_KIND_VIDEOS_LIST,
            utc_day=utc_calendar_day(now),
            id_units_reserved=DEFAULT_UNKNOWN_FORMAT_ENRICHMENT_DAILY_VIDEO_LIMIT,
            http_requests=0,
        ),
    )
    session.commit()
    assert select_unknown_video_ids_for_enrichment(session, now=now) == []


def test_get_channels_hidden_and_known_zero() -> None:
    from app.integrations.youtube.client import YouTubeApiClient, YouTubeChannelDetails

    class FakeKeys:
        key_count = 0

        def current_key(self):
            return "x"

    client = YouTubeApiClient.__new__(YouTubeApiClient)
    client._key_manager = FakeKeys()

    def fake_request(endpoint, params):
        assert endpoint == "channels"
        return {
            "items": [
                {
                    "id": "UChidden000000000000000001",
                    "snippet": {"title": "H"},
                    "statistics": {"hiddenSubscriberCount": True},
                },
                {
                    "id": "UCzero00000000000000000002",
                    "snippet": {"title": "Z"},
                    "statistics": {"subscriberCount": "0"},
                },
            ],
        }

    client._request = fake_request  # type: ignore[method-assign]
    out = client.get_channels(["UChidden000000000000000001", "UCzero00000000000000000002"])
    assert out["UChidden000000000000000001"].subscribers_known is False
    assert out["UChidden000000000000000001"].subscribers_hidden is True
    assert out["UCzero00000000000000000002"].subscribers_known is True
    assert out["UCzero00000000000000000002"].subscribers_count == 0


def test_resolve_known_zero_via_api_status() -> None:
    from datetime import datetime, timezone

    from app.models.orm import Channel
    from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN, apply_channel_subscriber_details
    from app.services.radar_target_eligibility import resolve_known_subscribers
    from app.integrations.youtube.client import YouTubeChannelDetails

    ch = Channel(
        id="UCzero00000000000000000002",
        title="t",
        subscribers_count=999,
        created_at=datetime.now(timezone.utc),
    )
    apply_channel_subscriber_details(
        ch,
        YouTubeChannelDetails(
            channel_id=ch.id,
            title="t",
            subscribers_count=0,
            subscribers_known=True,
        ),
    )
    assert ch.subscribers_api_status == SUBSCRIBERS_API_KNOWN
    assert resolve_known_subscribers(channel=ch, latest_snapshot=None) == 0


def test_hidden_api_blocks_stale_snapshot_subscribers() -> None:
    from app.services.radar_target_eligibility import resolve_known_subscribers, resolve_subscriber_provenance

    now = datetime.now(timezone.utc)
    ch = Channel(
        id="UChidden000000000000000001",
        title="t",
        subscribers_count=50_000,
        subscribers_api_status="hidden",
        created_at=now,
    )
    snap = VideoSnapshot(
        video_id="v",
        views=1,
        subscribers=12_000,
        vph=1.0,
        captured_at=now,
    )
    assert resolve_known_subscribers(channel=ch, latest_snapshot=snap) is None
    assert resolve_subscriber_provenance(channel=ch, latest_snapshot=snap) == (None, None)


def test_publish_cap_prefers_confirmed_over_unverified_top_ranks() -> None:
    now = datetime.now(timezone.utc)
    confirmed: set[str] = set()

    def make_rec(vid: str, rank: int, *, is_confirmed: bool) -> AttentionVideoRecord:
        ch = Channel(
            id=f"ch_{vid}",
            title="c",
            subscribers_count=100,
            subscribers_api_status="known",
            created_at=now,
        )
        video = Video(
            id=vid,
            title="t",
            channel_id=ch.id,
            published_at=now,
            content_format=VideoFormat.MEDIUM,
        )
        if is_confirmed:
            confirmed.add(vid)
        return AttentionVideoRecord(
            video=video,
            channel=ch,
            latest_snapshot=None,
            snapshots=[],
            hits=[],
            state=MagicMock(breakout_eligible=True, raw_vph=float(1000 - rank), age_hours=2.0),
            breakout_eligible=True,
            breakout_rank=rank,
            subscribers=100,
            views=100,
            vph=float(1000 - rank),
        )

    records = {}
    for i in range(1, 20):
        rec = make_rec(f"unverified_{i}", i, is_confirmed=False)
        records[rec.video.id] = rec
    for i in range(20, 70):
        rec = make_rec(f"verified_{i}", i, is_confirmed=True)
        records[rec.video.id] = rec

    bundle = AttentionEvidenceBundle(
        window_start=now,
        window_end=now,
        records=records,
        hits_by_video={},
        hits_by_keyword={},
        keyword_text={},
        channel_snapshots={},
        channels_by_id={rec.channel.id: rec.channel for rec in records.values()},
        extra_channel_videos={},
        extra_video_states={},
        extra_latest_snapshots={},
        extra_hits_by_video={},
    )
    winners = build_video_winners(
        bundle,
        AttentionEngineConfig(video_limit=50),
        now=now,
        publishable_confirmed_ids=frozenset(confirmed),
    )
    assert len(winners) == 50
    assert all(w.video_id.startswith("verified_") for w in winners)
    assert not any(w.video_id.startswith("unverified_") for w in winners)


def test_format_confirmation_persists_in_db() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.orm import Base, VideoFormatEnrichmentAttempt
    from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
    from app.services.unknown_format_enrichment import record_format_enrichment_attempt
    from app.services.video_format_api_verification import load_api_format_confirmed_video_ids

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    record_format_enrichment_attempt(
        session,
        video_id="vid_persist",
        outcome=OUTCOME_CONFIRMED_REGULAR,
        attempted_at=datetime.now(timezone.utc),
    )
    session.commit()
    session.close()
    session = Session()
    assert "vid_persist" in load_api_format_confirmed_video_ids(session)


def main() -> int:
    tests = [
        test_live_broadcast_content_mapping,
        test_completed_broadcast_via_streaming_details,
        test_opaque_unknown_stays_unknown,
        test_merge_does_not_downgrade_live,
        test_batch_chunks_fifty,
        test_partial_missing_not_regular,
        test_subscriber_limits,
        test_unknown_subscribers_not_zero,
        test_accelerating_cannot_bypass_format,
        test_top50_backfill_skips_ineligible,
        test_pattern_counts_after_filter,
        test_metrics_unknown_and_completed,
        test_discovery_summary_buckets,
        test_get_videos_requests_live_streaming_part,
        test_apply_api_details_persists_medium_to_live,
        test_daily_budget_exhausted_skips_selection,
        test_get_channels_hidden_and_known_zero,
        test_resolve_known_zero_via_api_status,
        test_hidden_api_blocks_stale_snapshot_subscribers,
        test_publish_cap_prefers_confirmed_over_unverified_top_ranks,
        test_format_confirmation_persists_in_db,
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
