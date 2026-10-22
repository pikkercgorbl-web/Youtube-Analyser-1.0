"""Manual search pipeline — filter gates and response shape."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import ChannelDetailModel, EnrichedVideoModel, VideoSearchModel
from app.services.manual_search_pipeline import (
    channel_browse_needed,
    channels_missing_subscriber_details,
    enriched_models_from_search_cards,
    has_known_subscriber_count,
    propagate_subscribers_within_batch,
    subscribers_enrichment_needed,
)
from app.services.video_filter_service import VideoFilterService


def test_channel_browse_needed_only_for_channel_filters() -> None:
    assert channel_browse_needed({}, "relevance") is False
    assert channel_browse_needed({"subscribers_min": 1000}, "virality") is False
    assert channel_browse_needed({"channel_views_min": 1}, "relevance") is True


def test_incomplete_channel_skips_channel_view_filter() -> None:
    video = VideoSearchModel(
        video_id="v1",
        channel_id="c1",
        title="t",
        views_count=1000,
    )
    item = enriched_models_from_search_cards([video])[0]
    item = EnrichedVideoModel(
        video=item.video,
        channel=ChannelDetailModel(total_views=0),
        virality_coefficient=item.virality_coefficient,
    )
    svc = VideoFilterService()
    out = svc.apply_filters(
        [item],
        {"channel_views_min": 100},
        allow_incomplete_channel=True,
    )
    assert len(out) == 1
    strict = svc.apply_filters([item], {"channel_views_min": 100})
    assert len(strict) == 0


def test_subscriber_enrichment_gates() -> None:
    video = VideoSearchModel(
        video_id="v1",
        channel_id="c1",
        title="t",
        views_count=1000,
        subscribers_count=5000,
    )
    with_subs = enriched_models_from_search_cards([video])[0]
    assert has_known_subscriber_count(with_subs) is True
    assert subscribers_enrichment_needed([with_subs]) is False

    video2 = VideoSearchModel(
        video_id="v2",
        channel_id="c2",
        title="t2",
        views_count=100,
    )
    without_subs = enriched_models_from_search_cards([video2])[0]
    assert subscribers_enrichment_needed([without_subs]) is True
    assert channels_missing_subscriber_details([with_subs, without_subs]) == ["c2"]

    twin_a = enriched_models_from_search_cards([video])[0]
    twin_b = enriched_models_from_search_cards([VideoSearchModel(
        video_id="v3",
        channel_id="c1",
        title="t3",
        views_count=200,
    )])[0]
    propagated = propagate_subscribers_within_batch([twin_b, twin_a])
    assert propagated[0].channel.subscribers_count == 5000


def main() -> None:
    test_channel_browse_needed_only_for_channel_filters()
    test_incomplete_channel_skips_channel_view_filter()
    test_subscriber_enrichment_gates()
    print("OK: manual search pipeline tests")


if __name__ == "__main__":
    main()
