"""Product Fix 2B — unit tests for opportunity family presentation tiers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.attention_engine_types import (
    FLAG_BROAD_KEYWORD_GROUP,
    FLAG_CROSS_SOURCE,
    FLAG_KEYWORD_ONLY,
    FLAG_PHRASE_SUPPORTED,
    FLAG_REPEATED_TITLE_TEMPLATE,
    FLAG_TOPIC_SUPPORTED,
    PatternFamily,
)
from app.services.opportunity_family_presentation import present_opportunity_family


def _family(
    *,
    family_key: str = "family:test",
    label: str = "test label",
    family_kind: str = "keyword_provenance",
    member_pattern_keys: tuple[str, ...] = ("keyword:1",),
    member_labels: tuple[str, ...] = ("kw",),
    video_ids: tuple[str, ...] = ("v1", "v2"),
    channel_ids: tuple[str, ...] = ("c1", "c2"),
    quality_flags: tuple[str, ...] = (),
    support_sources: tuple[str, ...] = ("keyword",),
) -> PatternFamily:
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return PatternFamily(
        family_key=family_key,
        label=label,
        family_kind=family_kind,  # type: ignore[arg-type]
        member_pattern_keys=member_pattern_keys,
        member_labels=member_labels,
        video_ids=video_ids,
        channel_ids=channel_ids,
        keyword_ids=(1,),
        video_count=len(video_ids),
        channel_count=len(channel_ids),
        keyword_count=1,
        breakout_eligible_count=2,
        videos_last_24h=0,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        grouping_reasons=("shared_video_membership",),
        quality_flags=quality_flags,
        support_sources=support_sources,
        first_seen_at=now,
        latest_seen_at=now,
    )


def test_two_winners_shared_keyword_not_repeating_idea() -> None:
    family = _family(
        family_kind="keyword_provenance",
        quality_flags=(FLAG_KEYWORD_ONLY, FLAG_CROSS_SOURCE),
        support_sources=("keyword", "topic"),
        video_ids=("w1", "w2", "v3"),
        channel_ids=("ch-a", "ch-b", "ch-c"),
    )
    titles = {
        "w1": "Hacker broke into ChatGPT account",
        "w2": "Day trading strategy for beginners",
        "v3": "Unrelated third video title here",
    }
    channels = {"w1": "ch-a", "w2": "ch-b", "v3": "ch-c"}
    pres = present_opportunity_family(
        family,
        feed_winner_id_set=frozenset({"w1", "w2"}),
        video_titles=titles,
        video_channels=channels,
    )
    assert pres.opportunity_presentation_tier == "search_collection"
    assert pres.grouping_basis_kind in (
        "single_search_query",
        "mixed_search_and_metadata",
    )


def test_shared_video_topic_alone_is_search_collection() -> None:
    family = _family(
        family_kind="video_topic",
        member_pattern_keys=("topic:abc",),
        member_labels=("Gaming",),
        label="Gaming",
        quality_flags=(FLAG_TOPIC_SUPPORTED,),
        support_sources=("topic",),
        video_ids=("v1", "v2"),
    )
    titles = {"v1": "Zombie survival part 1", "v2": "Live taxi stream NYC"}
    channels = {"v1": "c1", "v2": "c2"}
    pres = present_opportunity_family(
        family,
        feed_winner_id_set=frozenset({"v1"}),
        video_titles=titles,
        video_channels=channels,
    )
    assert pres.opportunity_presentation_tier == "search_collection"
    assert pres.grouping_basis_kind == "metadata_topic"


def test_one_winner_phrase_supported_not_repeating_format() -> None:
    phrase = "ai cartoon kaise banaye"
    family = _family(
        family_kind="title_phrase",
        member_pattern_keys=("phrase:abc",),
        member_labels=(phrase,),
        label=phrase,
        quality_flags=(FLAG_PHRASE_SUPPORTED,),
        support_sources=("title_phrase",),
        video_ids=("w1", "v2"),
        channel_ids=("ch-a", "ch-b"),
    )
    titles = {
        "w1": f"Full tutorial — {phrase} step by step",
        "v2": f"Another {phrase} guide for kids",
    }
    channels = {"w1": "ch-a", "v2": "ch-b"}
    pres = present_opportunity_family(
        family,
        feed_winner_id_set=frozenset({"w1"}),
        video_titles=titles,
        video_channels=channels,
    )
    assert pres.opportunity_presentation_tier == "needs_review"
    assert pres.title_evidence_video_ids == ("v2", "w1") or set(pres.title_evidence_video_ids) == {
        "w1",
        "v2",
    }
    assert pres.opportunity_presentation_tier != "repeating_idea"


def test_repeating_idea_requires_two_feed_winners_and_title_evidence() -> None:
    phrase = "ai cartoon kaise banaye"
    family = _family(
        family_kind="title_phrase",
        member_pattern_keys=("phrase:abc",),
        member_labels=(phrase,),
        label=phrase,
        quality_flags=(FLAG_PHRASE_SUPPORTED, FLAG_REPEATED_TITLE_TEMPLATE),
        support_sources=("title_phrase",),
        video_ids=("w1", "w2", "v3"),
        channel_ids=("ch-a", "ch-b", "ch-c"),
    )
    titles = {
        "w1": f"{phrase} part 1",
        "w2": f"Best {phrase} tutorial",
        "v3": "Something else entirely different",
    }
    channels = {"w1": "ch-a", "w2": "ch-b", "v3": "ch-c"}
    pres = present_opportunity_family(
        family,
        feed_winner_id_set=frozenset({"w1", "w2"}),
        video_titles=titles,
        video_channels=channels,
    )
    assert pres.opportunity_presentation_tier == "repeating_idea"


def test_broad_keyword_stays_search_even_with_template_flag() -> None:
    family = _family(
        family_kind="keyword_provenance",
        quality_flags=(
            FLAG_KEYWORD_ONLY,
            FLAG_BROAD_KEYWORD_GROUP,
            FLAG_REPEATED_TITLE_TEMPLATE,
        ),
        video_ids=("w1", "w2"),
    )
    titles = {"w1": "Title A", "w2": "Title B"}
    channels = {"w1": "c1", "w2": "c2"}
    pres = present_opportunity_family(
        family,
        feed_winner_id_set=frozenset({"w1", "w2"}),
        video_titles=titles,
        video_channels=channels,
    )
    assert pres.opportunity_presentation_tier == "search_collection"


def main() -> None:
    test_two_winners_shared_keyword_not_repeating_idea()
    test_shared_video_topic_alone_is_search_collection()
    test_one_winner_phrase_supported_not_repeating_format()
    test_repeating_idea_requires_two_feed_winners_and_title_evidence()
    test_broad_keyword_stays_search_even_with_template_flag()
    print("test_opportunity_family_presentation_2b: OK")


if __name__ == "__main__":
    main()
