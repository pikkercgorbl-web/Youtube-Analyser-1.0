"""Product Fix 2B — honest Pattern Family presentation for Opportunities (read path)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import Video
from app.services.attention_engine_types import (
    FLAG_BROAD_KEYWORD_GROUP,
    FLAG_KEYWORD_ONLY,
    FLAG_PHRASE_SUPPORTED,
    FLAG_REPEATED_TITLE_TEMPLATE,
    FLAG_TOPIC_SUPPORTED,
    PatternFamily,
    VideoWinner,
)
from app.services.attention_family_tokens import family_content_tokens

OpportunityPresentationTier = Literal[
    "repeating_idea",
    "needs_review",
    "search_collection",
]
GroupingBasisKind = Literal[
    "single_search_query",
    "metadata_topic",
    "title_phrase_similarity",
    "mixed_search_and_metadata",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class OpportunityFamilyPresentation:
    opportunity_presentation_tier: OpportunityPresentationTier
    grouping_basis_kind: GroupingBasisKind
    grouping_basis_label: str
    tier_reason: str
    feed_winner_video_ids: tuple[str, ...]
    title_evidence_video_ids: tuple[str, ...]


def load_video_title_channel_maps(
    session: Session,
    video_ids: set[str],
    *,
    winner_rows: tuple[VideoWinner, ...] | list[VideoWinner],
) -> tuple[dict[str, str], dict[str, str]]:
    titles: dict[str, str] = {}
    channels: dict[str, str] = {}
    for row in winner_rows:
        titles[row.video_id] = row.title
        channels[row.video_id] = row.channel_id
    missing = [vid for vid in video_ids if vid not in titles]
    if missing:
        for video in session.scalars(select(Video).where(Video.id.in_(missing))).all():
            titles[video.id] = video.title or ""
            channels[video.id] = video.channel_id
    return titles, channels


def _phrase_member_labels(family: PatternFamily) -> tuple[str, ...]:
    labels: list[str] = []
    for key, label in zip(family.member_pattern_keys, family.member_labels, strict=False):
        if key.startswith("phrase:"):
            labels.append(label)
    if not labels and family.family_kind == "title_phrase":
        labels.append(family.label)
    return tuple(dict.fromkeys(labels))


def _video_matches_phrase(title: str, phrase_label: str) -> bool:
    phrase_tokens = family_content_tokens(phrase_label)
    if len(phrase_tokens) < 2:
        return False
    title_tokens = family_content_tokens(title)
    return phrase_tokens <= title_tokens


def title_evidence_video_ids(
    family: PatternFamily,
    *,
    video_titles: dict[str, str],
) -> tuple[str, ...]:
    phrases = _phrase_member_labels(family)
    if not phrases:
        return ()
    matched: set[str] = set()
    for video_id in family.video_ids:
        title = video_titles.get(video_id, "")
        if not title:
            continue
        if any(_video_matches_phrase(title, phrase) for phrase in phrases):
            matched.add(video_id)
    return tuple(sorted(matched))


def _distinct_channel_count(
    video_ids: tuple[str, ...] | list[str],
    *,
    video_channels: dict[str, str],
) -> int:
    channels = {video_channels[vid] for vid in video_ids if video_channels.get(vid)}
    return len(channels)


def _feed_winner_ids(
    family: PatternFamily,
    *,
    feed_winner_id_set: frozenset[str],
) -> tuple[str, ...]:
    return tuple(vid for vid in family.video_ids if vid in feed_winner_id_set)


def _is_search_collection_basis(family: PatternFamily, flags: set[str]) -> bool:
    if family.family_kind in ("keyword_provenance", "video_topic"):
        return True
    if FLAG_KEYWORD_ONLY in flags or FLAG_BROAD_KEYWORD_GROUP in flags:
        return True
    if FLAG_TOPIC_SUPPORTED in flags and FLAG_PHRASE_SUPPORTED not in flags:
        return True
    return False


def _grouping_basis(
    family: PatternFamily,
    flags: set[str],
    *,
    has_title_evidence: bool,
) -> tuple[GroupingBasisKind, str]:
    has_keyword = "keyword" in family.support_sources or family.family_kind == "keyword_provenance"
    has_topic = FLAG_TOPIC_SUPPORTED in flags or family.family_kind == "video_topic"
    has_phrase = has_title_evidence or FLAG_PHRASE_SUPPORTED in flags

    if has_phrase and not has_keyword and not has_topic:
        sample = _phrase_member_labels(family)
        phrase_hint = sample[0] if sample else family.label
        return (
            "title_phrase_similarity",
            f"похожие формулировки в названиях (например: «{phrase_hint}»)",
        )
    if has_keyword and not has_topic:
        return ("single_search_query", "найдены по одному запросу")
    if has_topic and not has_keyword:
        return ("metadata_topic", "общая тема из метаданных")
    if has_keyword and has_topic:
        return (
            "mixed_search_and_metadata",
            "общий поисковый запрос и тема из метаданных",
        )
    if has_phrase:
        sample = _phrase_member_labels(family)
        phrase_hint = sample[0] if sample else family.label
        return (
            "title_phrase_similarity",
            f"сходство названий («{phrase_hint}») вместе с другими основаниями",
        )
    return ("unknown", "основание группировки не определено")


def _qualifies_repeating_idea(
    family: PatternFamily,
    flags: set[str],
    *,
    evidence_ids: tuple[str, ...],
    feed_winner_ids: tuple[str, ...],
    video_channels: dict[str, str],
) -> bool:
    if _is_search_collection_basis(family, flags) and FLAG_PHRASE_SUPPORTED not in flags:
        return False
    if family.family_kind == "keyword_provenance":
        return False
    if family.family_kind == "video_topic" and FLAG_PHRASE_SUPPORTED not in flags:
        return False
    if FLAG_KEYWORD_ONLY in flags or FLAG_BROAD_KEYWORD_GROUP in flags:
        return False

    evidence_channels = _distinct_channel_count(evidence_ids, video_channels=video_channels)
    if evidence_channels < 2:
        return False

    winner_channels = _distinct_channel_count(feed_winner_ids, video_channels=video_channels)
    if winner_channels < 2:
        return False

    if FLAG_REPEATED_TITLE_TEMPLATE in flags:
        return True
    if FLAG_PHRASE_SUPPORTED in flags or family.family_kind == "title_phrase":
        return True
    return False


def _qualifies_needs_review(
    family: PatternFamily,
    flags: set[str],
    *,
    evidence_ids: tuple[str, ...],
    video_channels: dict[str, str],
) -> bool:
    if _is_search_collection_basis(family, flags) and not evidence_ids:
        return False
    if not evidence_ids:
        return False
    if _distinct_channel_count(evidence_ids, video_channels=video_channels) < 2:
        return False
    if FLAG_PHRASE_SUPPORTED in flags or family.family_kind == "title_phrase":
        return True
    if FLAG_REPEATED_TITLE_TEMPLATE in flags:
        return True
    return False


def present_opportunity_family(
    family: PatternFamily,
    *,
    feed_winner_id_set: frozenset[str],
    video_titles: dict[str, str],
    video_channels: dict[str, str],
) -> OpportunityFamilyPresentation:
    flags = set(family.quality_flags)
    evidence_ids = title_evidence_video_ids(family, video_titles=video_titles)
    feed_ids = _feed_winner_ids(family, feed_winner_id_set=feed_winner_id_set)
    basis_kind, basis_label = _grouping_basis(
        family,
        flags,
        has_title_evidence=bool(evidence_ids),
    )

    if _qualifies_repeating_idea(
        family,
        flags,
        evidence_ids=evidence_ids,
        feed_winner_ids=feed_ids,
        video_channels=video_channels,
    ):
        return OpportunityFamilyPresentation(
            opportunity_presentation_tier="repeating_idea",
            grouping_basis_kind=basis_kind,
            grouping_basis_label=basis_label,
            tier_reason=(
                "узкий признак в названиях подтверждён минимум у двух видео с разных каналов "
                "и среди участников есть минимум два Winner с разных каналов"
            ),
            feed_winner_video_ids=feed_ids,
            title_evidence_video_ids=evidence_ids,
        )

    if _qualifies_needs_review(
        family,
        flags,
        evidence_ids=evidence_ids,
        video_channels=video_channels,
    ):
        return OpportunityFamilyPresentation(
            opportunity_presentation_tier="needs_review",
            grouping_basis_kind=basis_kind,
            grouping_basis_label=basis_label,
            tier_reason=(
                "сходство заголовков видно по сохранённым evidence; "
                "повторяемость формата или результата ещё не доказана автоматически"
            ),
            feed_winner_video_ids=feed_ids,
            title_evidence_video_ids=evidence_ids,
        )

    if _is_search_collection_basis(family, flags):
        reason = "группа объединена поиском или метаданными, без доказанного общего формата"
    elif feed_ids:
        reason = "есть Winner в подборке, но это не повышает доказанность всей группы"
    else:
        reason = "исследовательская подборка без Winner в текущем Top-50"

    return OpportunityFamilyPresentation(
        opportunity_presentation_tier="search_collection",
        grouping_basis_kind=basis_kind,
        grouping_basis_label=basis_label,
        tier_reason=reason,
        feed_winner_video_ids=feed_ids,
        title_evidence_video_ids=evidence_ids if evidence_ids else (),
    )
