"""SEO keyword research based on InnerTube search SERP."""

from __future__ import annotations

import asyncio
import re

from app.integrations.youtube.client import (
    EnrichedVideoModel,
    get_enriched_search_results,
    get_search_suggestions,
)
from app.models.schemas import (
    KeywordMetrics,
    KeywordResearchItem,
    KeywordResearchResponse,
    KeywordResearchSuggestions,
)

_MAX_SIMILAR_SUGGESTIONS = 7
_MAX_QUESTION_SUGGESTIONS = 7
_MAX_RELATED_SUGGESTIONS = 7

_QUESTION_SEED_TEMPLATES: tuple[str, ...] = (
    "how to {query}",
    "как {query}",
    "что такое {query}",
)

_QUESTION_PREFIX = re.compile(
    r"^(как|что|где|когда|почему|зачем|сколько|можно ли|нужно ли|что такое|"
    r"how|what|why|where|when|who)\b",
    re.IGNORECASE,
)

_VOLUME_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (10_000, 10),
    (100_000, 50),
    (500_000, 75),
    (1_000_000, 100),
)

_COMPETITION_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (10_000, 10),
    (100_000, 60),
    (1_000_000, 100),
)

_EXACT_MATCH_PENALTY_PER_VIDEO = 5
_EXACT_MATCH_PENALTY_MAX = 25


def _score_from_breakpoints(
    value: float,
    breakpoints: tuple[tuple[float, float], ...],
) -> float:
    """Map a numeric metric to a 0–100 score using piecewise linear interpolation."""
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    for index in range(len(breakpoints) - 1):
        low_value, low_score = breakpoints[index]
        high_value, high_score = breakpoints[index + 1]
        if low_value <= value <= high_value:
            if high_value == low_value:
                return high_score
            ratio = (value - low_value) / (high_value - low_value)
            return low_score + ratio * (high_score - low_score)

    return breakpoints[-1][1]


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _has_exact_keyword_match(title: str, query: str) -> bool:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return False
    return normalized_query in title.lower()


def _is_question_keyword(keyword: str) -> bool:
    trimmed = keyword.strip()
    return "?" in trimmed or bool(_QUESTION_PREFIX.search(trimmed))


def _unique_keywords(keywords: list[str], *, exclude: set[str] | None = None) -> list[str]:
    excluded = exclude or set()
    seen: set[str] = set()
    unique: list[str] = []
    for keyword in keywords:
        cleaned = keyword.strip()
        normalized = _normalize_query(cleaned)
        if not normalized or normalized in excluded or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(cleaned)
    return unique


def _question_seed_queries(query: str) -> tuple[str, ...]:
    return tuple(template.format(query=query.strip()) for template in _QUESTION_SEED_TEMPLATES)


async def collect_categorized_suggestions(query: str) -> dict[str, list[str]]:
    """Collect similar, question and related suggestions from multiple InnerTube vectors."""
    normalized_query = query.strip()
    main_normalized = _normalize_query(normalized_query)
    exclude = {main_normalized}

    standard_suggestions = await get_search_suggestions(normalized_query)
    question_seed_results = await asyncio.gather(
        *[get_search_suggestions(seed_query) for seed_query in _question_seed_queries(normalized_query)],
    )

    similar = _unique_keywords(
        standard_suggestions,
        exclude=exclude,
    )[:_MAX_SIMILAR_SUGGESTIONS]

    similar_normalized = {_normalize_query(keyword) for keyword in similar}

    question_pool: list[str] = []
    for seed_suggestions in question_seed_results:
        question_pool.extend(seed_suggestions)
    questions = _unique_keywords(
        question_pool,
        exclude=exclude | similar_normalized,
    )
    questions = [
        keyword
        for keyword in questions
        if _is_question_keyword(keyword)
    ][: _MAX_QUESTION_SUGGESTIONS]
    questions_normalized = {_normalize_query(keyword) for keyword in questions}

    related: list[str] = []
    for keyword in standard_suggestions:
        cleaned = keyword.strip()
        normalized = _normalize_query(cleaned)
        if not normalized or normalized in exclude:
            continue
        if normalized in similar_normalized or normalized in questions_normalized:
            continue
        if main_normalized in normalized:
            related.append(cleaned)
        if len(related) >= _MAX_RELATED_SUGGESTIONS:
            break

    return {
        "similar": similar,
        "questions": questions,
        "related": related,
    }


def _calc_search_volume_score(avg_views: float) -> int:
    return round(_score_from_breakpoints(avg_views, _VOLUME_BREAKPOINTS))


def _calc_competition_score(
    avg_subscribers: float,
    *,
    exact_match_count: int,
) -> int:
    base_score = _score_from_breakpoints(avg_subscribers, _COMPETITION_BREAKPOINTS)
    penalty = min(
        exact_match_count * _EXACT_MATCH_PENALTY_PER_VIDEO,
        _EXACT_MATCH_PENALTY_MAX,
    )
    return min(100, round(base_score + penalty))


def _calc_overall_score(search_volume: int, competition: int) -> float:
    return round((search_volume + (100 - competition)) / 2, 1)


def _metrics_from_results(query: str, results: list[EnrichedVideoModel]) -> KeywordMetrics:
    top_ten = results[:10]
    avg_views = sum(item.video.views_count for item in top_ten) / len(top_ten)
    avg_subscribers = sum(item.channel.subscribers_count for item in results) / len(results)

    exact_match_count = sum(
        1 for item in results if _has_exact_keyword_match(item.video.title, query)
    )

    search_volume = _calc_search_volume_score(avg_views)
    competition = _calc_competition_score(
        avg_subscribers,
        exact_match_count=exact_match_count,
    )
    overall_score = _calc_overall_score(search_volume, competition)

    return KeywordMetrics(
        query=query,
        volume=search_volume,
        competition=competition,
        score=overall_score,
    )


def _to_research_item(metrics: KeywordMetrics) -> KeywordResearchItem:
    return KeywordResearchItem(
        keyword=metrics.query,
        volume=metrics.volume,
        competition=metrics.competition,
        score=metrics.score,
    )


class KeywordResearchService:
    """Calculate SEO metrics from an InnerTube top-20 SERP."""

    async def calculate_metrics(self, query: str) -> KeywordMetrics:
        """Compute volume, competition and overall score without SERP video payloads."""
        normalized_query = query.strip()
        if not normalized_query:
            msg = "Query must not be empty"
            raise ValueError(msg)

        results = await get_enriched_search_results(normalized_query, max_results=20, save_to_db=False)
        if not results:
            msg = f"No YouTube results found for query: {normalized_query!r}"
            raise ValueError(msg)

        return _metrics_from_results(normalized_query, results)

    async def research(self, query: str) -> KeywordResearchResponse:
        normalized_query = query.strip()
        if not normalized_query:
            msg = "Query must not be empty"
            raise ValueError(msg)

        categorized = await collect_categorized_suggestions(normalized_query)
        all_keywords = _unique_keywords(
            [normalized_query, *categorized["similar"], *categorized["questions"], *categorized["related"]],
        )

        metric_results = await asyncio.gather(
            *[self.calculate_metrics(keyword) for keyword in all_keywords],
            return_exceptions=True,
        )

        metrics_by_keyword: dict[str, KeywordResearchItem] = {}
        main_item: KeywordResearchItem | None = None

        for keyword, result in zip(all_keywords, metric_results, strict=True):
            if isinstance(result, BaseException):
                if _normalize_query(keyword) == _normalize_query(normalized_query):
                    raise result
                continue
            item = _to_research_item(result)
            metrics_by_keyword[_normalize_query(keyword)] = item
            if _normalize_query(keyword) == _normalize_query(normalized_query):
                main_item = item

        if main_item is None:
            msg = f"No YouTube results found for query: {normalized_query!r}"
            raise ValueError(msg)

        def build_category_items(keywords: list[str]) -> list[KeywordResearchItem]:
            items = [
                metrics_by_keyword[_normalize_query(keyword)]
                for keyword in keywords
                if _normalize_query(keyword) in metrics_by_keyword
            ]
            items.sort(key=lambda item: item.score, reverse=True)
            return items

        return KeywordResearchResponse(
            main_query=main_item,
            suggestions=KeywordResearchSuggestions(
                similar=build_category_items(categorized["similar"]),
                questions=build_category_items(categorized["questions"]),
                related=build_category_items(categorized["related"]),
            ),
        )
