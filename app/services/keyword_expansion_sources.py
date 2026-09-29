"""Keyword expansion source implementations (Stage 1.16C)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import get_related_search_suggestions, get_search_suggestions
from app.models.orm import KeywordDiscoveryHit, Video
from app.services.keyword_expansion_types import KeywordExpansionCandidate, SimpleExpansionContext
from app.services.keyword_lifecycle_service import normalize_keyword_text
from app.services.keyword_scheduling_policy import SOURCE_CHANNEL, SOURCE_RELATED, SOURCE_SUGGESTION
from app.services.metrics import utc_now


def _dedupe_suggestions(
    texts: list[str],
    *,
    parent_normalized: str,
    limit: int,
) -> list[str]:
    seen: set[str] = {parent_normalized.casefold()}
    result: list[str] = []
    for raw in texts:
        cleaned = normalize_keyword_text(raw)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _to_candidates(
    keywords: list[str],
    *,
    source_type: str,
    context: SimpleExpansionContext,
    discovered_at: datetime,
    source_reference: str | None = None,
) -> list[KeywordExpansionCandidate]:
    return [
        KeywordExpansionCandidate(
            keyword=text,
            normalized_keyword=normalize_keyword_text(text),
            source_type=source_type,
            parent_keyword_id=context.parent_keyword_id,
            parent_keyword=context.parent_keyword,
            source_reference=source_reference,
            discovered_at=discovered_at,
        )
        for text in keywords
    ]


class SuggestionExpansionSource:
    source_type = SOURCE_SUGGESTION

    def __init__(self, *, max_suggestions: int = 20) -> None:
        self._max = max(1, max_suggestions)

    async def expand(
        self,
        seed_keyword: str,
        context: SimpleExpansionContext,
    ) -> list[KeywordExpansionCandidate]:
        discovered_at = utc_now()
        parent_norm = normalize_keyword_text(seed_keyword).casefold()
        primary = await get_search_suggestions(seed_keyword)
        # Secondary partial query may surface additional autocomplete (API cap ~10 each).
        secondary = await get_search_suggestions(f"{seed_keyword} ")
        merged = _dedupe_suggestions(
            [*primary, *secondary],
            parent_normalized=parent_norm,
            limit=self._max,
        )
        return _to_candidates(
            merged,
            source_type=self.source_type,
            context=context,
            discovered_at=discovered_at,
            source_reference="innertube_autocomplete",
        )


class RelatedQueryExpansionSource:
    """
    Related search terms via filtered autocomplete (no InnerTube refinement chips in repo).
    """

    source_type = SOURCE_RELATED

    def __init__(self, *, max_suggestions: int = 20) -> None:
        self._max = max(1, max_suggestions)

    async def expand(
        self,
        seed_keyword: str,
        context: SimpleExpansionContext,
    ) -> list[KeywordExpansionCandidate]:
        discovered_at = utc_now()
        related = await get_related_search_suggestions(
            seed_keyword,
            max_suggestions=min(self._max, 20),
        )
        parent_norm = normalize_keyword_text(seed_keyword).casefold()
        merged = _dedupe_suggestions(related, parent_normalized=parent_norm, limit=self._max)
        return _to_candidates(
            merged,
            source_type=self.source_type,
            context=context,
            discovered_at=discovered_at,
            source_reference="innertube_related_autocomplete",
        )


class ChannelTopicExpansionSource:
    """
    Conservative topic phrases from persisted discovery hits (Video.topic).

    Disabled when no structured topic data exists for the seed.
    """

    source_type = SOURCE_CHANNEL

    def __init__(self, session: Session, *, max_topics: int = 20) -> None:
        self._session = session
        self._max = max(1, max_topics)

    async def expand(
        self,
        seed_keyword: str,
        context: SimpleExpansionContext,
    ) -> list[KeywordExpansionCandidate]:
        discovered_at = utc_now()
        parent_norm = normalize_keyword_text(seed_keyword).casefold()
        rows = self._session.execute(
            select(Video.topic)
            .join(KeywordDiscoveryHit, KeywordDiscoveryHit.video_id == Video.id)
            .where(
                KeywordDiscoveryHit.keyword_id == context.parent_keyword_id,
                Video.topic.is_not(None),
                Video.topic != "",
            )
            .distinct()
            .limit(self._max * 3),
        ).all()
        topics: list[str] = []
        seen: set[str] = {parent_norm}
        for (topic,) in rows:
            cleaned = normalize_keyword_text(str(topic))
            key = cleaned.casefold()
            if len(cleaned) < 3 or key in seen:
                continue
            seen.add(key)
            topics.append(cleaned)
            if len(topics) >= self._max:
                break
        return _to_candidates(
            topics,
            source_type=self.source_type,
            context=context,
            discovered_at=discovered_at,
            source_reference="video_topic_from_discovery_hits",
        )
