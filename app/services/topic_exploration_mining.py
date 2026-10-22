"""Mine repeated normalized phrases from exploration title hits (Stage 6)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.services.attention_title_normalization import normalize_title, title_ngrams
from app.services.keyword_lifecycle_service import find_keyword_by_normalized, normalize_keyword_text
from app.services.topic_exploration_mining_config import GENERIC_EXPLORATION_PHRASES, TopicExplorationMiningConfig
from app.services.topic_exploration_types import (
    TopicExplorationPhraseEvidence,
    TopicExplorationRejectedPhrase,
    TopicExplorationTitleHit,
)


@dataclass
class _PhraseAccumulator:
    videos: dict[str, TopicExplorationTitleHit] = None  # type: ignore[assignment]
    channels: dict[str, str] = None  # type: ignore[assignment]
    query_ids: set[str] = None  # type: ignore[assignment]
    run_ids: set[str] = None  # type: ignore[assignment]
    titles: set[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.videos is None:
            self.videos = {}
        if self.channels is None:
            self.channels = {}
        if self.query_ids is None:
            self.query_ids = set()
        if self.run_ids is None:
            self.run_ids = set()
        if self.titles is None:
            self.titles = set()


def _exploration_query_normalized(text: str) -> str:
    return normalize_title(text)


def _phrase_contained_in_exploration_query(phrase: str, exploration_queries: set[str]) -> bool:
    p = normalize_title(phrase)
    if not p:
        return True
    for q in exploration_queries:
        if p in q or q in p:
            return True
    return False


def _is_generic_phrase(phrase: str) -> bool:
    p = normalize_title(phrase)
    if p in GENERIC_EXPLORATION_PHRASES:
        return True
    tokens = p.split()
    if len(tokens) <= 1 and p in GENERIC_EXPLORATION_PHRASES:
        return True
    return False


def _spelling_variant_of_existing(session: Session, phrase: str) -> bool:
    from sqlalchemy import select

    from app.models.orm import TargetKeyword

    normalized = normalize_keyword_text(phrase)
    if find_keyword_by_normalized(session, normalized) is not None:
        return True
    folded = normalized.casefold().replace(" ", "")
    if len(folded) < 4:
        return False
    for row in session.scalars(select(TargetKeyword)).all():
        existing = normalize_keyword_text(row.keyword).casefold().replace(" ", "")
        if folded == existing:
            return True
    return False


def mine_phrases_from_hits(
    session: Session,
    hits: tuple[TopicExplorationTitleHit, ...],
    *,
    window_start,
    window_end,
    config: TopicExplorationMiningConfig | None = None,
) -> tuple[list[TopicExplorationPhraseEvidence], list[TopicExplorationRejectedPhrase]]:
    cfg = config or TopicExplorationMiningConfig()
    exploration_queries = {_exploration_query_normalized(h.exploration_query_text) for h in hits}

    accum: dict[str, _PhraseAccumulator] = defaultdict(_PhraseAccumulator)

    for hit in hits:
        if hit.video_topic and normalize_keyword_text(hit.video_topic).casefold() == normalize_keyword_text(
            hit.exploration_query_text,
        ).casefold():
            continue
        for phrase in title_ngrams(hit.title, min_n=cfg.min_ngram, max_n=cfg.max_ngram):
            norm = normalize_title(phrase)
            if not norm:
                continue
            bucket = accum[norm]
            if hit.video_id not in bucket.videos:
                bucket.videos[hit.video_id] = hit
            ch = (hit.channel_id or "").strip()
            if ch and ch not in bucket.channels:
                bucket.channels[ch] = hit.video_id
            bucket.query_ids.add(hit.exploration_query_id)
            bucket.run_ids.add(hit.discovery_run_id)
            bucket.titles.add(hit.title.strip())

    proposed: list[TopicExplorationPhraseEvidence] = []
    rejected: list[TopicExplorationRejectedPhrase] = []

    for norm_phrase, bucket in sorted(accum.items(), key=lambda x: x[0]):
        video_ids = tuple(sorted(bucket.videos))
        channel_ids = tuple(sorted(bucket.channels))
        evidence = TopicExplorationPhraseEvidence(
            phrase=norm_phrase,
            normalized_phrase=norm_phrase,
            distinct_video_ids=video_ids,
            distinct_channel_ids=channel_ids,
            source_titles=tuple(sorted(bucket.titles))[:20],
            exploration_query_ids=tuple(sorted(bucket.query_ids)),
            discovery_run_ids=tuple(sorted(bucket.run_ids)),
            observation_window_start=window_start,
            observation_window_end=window_end,
            support_video_count=len(video_ids),
            support_channel_count=len(channel_ids),
        )

        if _phrase_contained_in_exploration_query(norm_phrase, exploration_queries):
            rejected.append(
                TopicExplorationRejectedPhrase(
                    phrase=norm_phrase,
                    normalized_phrase=norm_phrase,
                    reason_code="exploration_query_overlap",
                    human_reason="Phrase overlaps broad exploration query text",
                    evidence=evidence,
                ),
            )
            continue
        if _is_generic_phrase(norm_phrase):
            rejected.append(
                TopicExplorationRejectedPhrase(
                    phrase=norm_phrase,
                    normalized_phrase=norm_phrase,
                    reason_code="generic_phrase",
                    human_reason="Phrase is too generic for a target keyword",
                    evidence=evidence,
                ),
            )
            continue
        if _spelling_variant_of_existing(session, norm_phrase):
            rejected.append(
                TopicExplorationRejectedPhrase(
                    phrase=norm_phrase,
                    normalized_phrase=norm_phrase,
                    reason_code="existing_keyword",
                    human_reason="Phrase matches or is a variant of an existing keyword",
                    evidence=evidence,
                ),
            )
            continue
        if evidence.support_channel_count < cfg.min_distinct_channels:
            rejected.append(
                TopicExplorationRejectedPhrase(
                    phrase=norm_phrase,
                    normalized_phrase=norm_phrase,
                    reason_code="insufficient_channel_support",
                    human_reason=(
                        f"Need at least {cfg.min_distinct_channels} independent channels "
                        f"(got {evidence.support_channel_count})"
                    ),
                    evidence=evidence,
                ),
            )
            continue
        if evidence.support_video_count < cfg.min_distinct_videos:
            rejected.append(
                TopicExplorationRejectedPhrase(
                    phrase=norm_phrase,
                    normalized_phrase=norm_phrase,
                    reason_code="insufficient_video_support",
                    human_reason=(
                        f"Need at least {cfg.min_distinct_videos} distinct videos "
                        f"(got {evidence.support_video_count})"
                    ),
                    evidence=evidence,
                ),
            )
            continue
        proposed.append(evidence)

    return proposed, rejected
