"""Keyword analysis for evergreen traffic opportunity scoring."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from statistics import median

from app.integrations.youtube.client import YouTubeApiClient, YouTubeVideoDetails
from app.models.orm import CompetitionLevel
from app.models.schemas import (
    KeywordAnalyzeResponse,
    KeywordCompetitionMetrics,
    KeywordSimilarTag,
    KeywordTopResultItem,
    KeywordVolumeMetrics,
)
from app.utils.text import extract_title_keywords

MEGA_CHANNEL_THRESHOLD = 1_000_000
SMALL_CHANNEL_THRESHOLD = 50_000
SERP_SIZE = 20
SIMILAR_TAGS_LIMIT = 15
MIN_LOG_SCALE_VALUE = 1_000


@dataclass(frozen=True, slots=True)
class _AnalyzedResult:
    rank: int
    video: YouTubeVideoDetails
    channel_title: str
    channel_subscribers: int


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _log_scale_score(value: float, *, low: float, high: float) -> float:
    """
    Convert a metric to a 0-100 score on a logarithmic scale.

    This keeps one viral outlier from dominating the keyword score and reflects
    how YouTube demand/authority usually grows by orders of magnitude.
    """
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0

    low_log = math.log10(low)
    high_log = math.log10(high)
    value_log = math.log10(max(value, 1))
    return _clamp_score((value_log - low_log) / (high_log - low_log) * 100.0)


class KeywordAnalysisService:
    """Evaluate keyword search volume, competition, and opportunity score."""

    def __init__(self, youtube_client: YouTubeApiClient) -> None:
        self._youtube = youtube_client

    def analyze(self, keyword: str) -> KeywordAnalyzeResponse:
        query = keyword.strip()
        if not query:
            msg = "Keyword must not be empty"
            raise ValueError(msg)

        search_hits = self._youtube.search_videos_relevance(query, max_results=SERP_SIZE)
        if not search_hits:
            msg = f"No YouTube results found for keyword: {query!r}"
            raise ValueError(msg)

        video_details = self._youtube.get_videos([hit.video_id for hit in search_hits])
        videos_by_id = {video.video_id: video for video in video_details}

        channel_ids = [video.channel_id for video in video_details if video.channel_id]
        channels = self._youtube.get_channels(channel_ids)

        analyzed: list[_AnalyzedResult] = []
        for rank, hit in enumerate(search_hits, start=1):
            video = videos_by_id.get(hit.video_id)
            if video is None:
                continue
            channel = channels.get(video.channel_id)
            analyzed.append(
                _AnalyzedResult(
                    rank=rank,
                    video=video,
                    channel_title=channel.title if channel else hit.title,
                    channel_subscribers=channel.subscribers_count if channel else 0,
                ),
            )

        if not analyzed:
            msg = f"Unable to enrich YouTube results for keyword: {query!r}"
            raise ValueError(msg)

        volume = self._calc_volume_metrics(query, analyzed)
        competition = self._calc_competition_metrics(query, analyzed)
        opportunity_score = self._calc_opportunity_score(volume.volume_score, competition.competition_score)
        similar_tags = self._extract_similar_tags(query, analyzed)
        top_results = self._build_top_results(analyzed)

        return KeywordAnalyzeResponse(
            keyword=query,
            opportunity_score=opportunity_score,
            volume=volume,
            competition=competition,
            similar_tags=similar_tags,
            top_results=top_results,
            analyzed_videos=len(analyzed),
            recommendation=self._build_recommendation(
                query,
                opportunity_score=opportunity_score,
                volume=volume,
                competition=competition,
            ),
        )

    def _calc_volume_metrics(self, keyword: str, analyzed: list[_AnalyzedResult]) -> KeywordVolumeMetrics:
        views = [item.video.views_count for item in analyzed]
        total_views = sum(views)
        avg_views = total_views / len(views)
        median_views = int(median(views))

        query_tokens = _keyword_tokens(keyword)
        tag_mentions = sum(
            1 for item in analyzed if _keyword_in_tags(query_tokens, item.video.tags)
        )
        title_mentions = sum(
            1 for item in analyzed if _keyword_in_text(query_tokens, item.video.title)
        )
        tag_mention_rate = tag_mentions / len(analyzed)
        title_mention_rate = title_mentions / len(analyzed)

        median_views_component = _log_scale_score(
            median_views,
            low=MIN_LOG_SCALE_VALUE,
            high=1_000_000,
        )
        avg_views_component = _log_scale_score(
            avg_views,
            low=5_000,
            high=2_000_000,
        )
        relevance_component = (0.70 * title_mention_rate + 0.30 * tag_mention_rate) * 100.0
        volume_score = round(
            _clamp_score(
                0.55 * median_views_component
                + 0.25 * avg_views_component
                + 0.20 * relevance_component,
            ),
            2,
        )

        return KeywordVolumeMetrics(
            total_views=total_views,
            avg_views=round(avg_views, 2),
            median_views=median_views,
            tag_mention_rate=round(tag_mention_rate, 4),
            title_mention_rate=round(title_mention_rate, 4),
            volume_score=volume_score,
        )

    def _calc_competition_metrics(
        self,
        keyword: str,
        analyzed: list[_AnalyzedResult],
    ) -> KeywordCompetitionMetrics:
        subscribers = [item.channel_subscribers for item in analyzed]
        mega_count = sum(1 for count in subscribers if count >= MEGA_CHANNEL_THRESHOLD)
        small_count = sum(1 for count in subscribers if count < SMALL_CHANNEL_THRESHOLD)
        mega_ratio = mega_count / len(subscribers)
        small_ratio = small_count / len(subscribers)
        exact_title_match_rate = sum(
            1 for item in analyzed if _has_exact_keyword_match(item.video.title, keyword)
        ) / len(analyzed)

        avg_subscribers = int(sum(subscribers) / len(subscribers))
        median_subscribers = int(median(subscribers))

        authority_component = _log_scale_score(
            median_subscribers,
            low=1_000,
            high=1_000_000,
        )
        mega_component = mega_ratio * 100.0
        exact_match_component = exact_title_match_rate * 100.0
        small_channel_relief = small_ratio * 100.0

        competition_score = round(
            _clamp_score(
                0.55 * authority_component
                + 0.25 * mega_component
                + 0.20 * exact_match_component
                - 0.15 * small_channel_relief,
            ),
            2,
        )
        competition_level = _competition_level(competition_score)

        return KeywordCompetitionMetrics(
            avg_channel_subscribers=avg_subscribers,
            median_channel_subscribers=median_subscribers,
            mega_channel_count=mega_count,
            small_channel_count=small_count,
            mega_channel_ratio=round(mega_ratio, 4),
            small_channel_ratio=round(small_ratio, 4),
            competition_score=competition_score,
            competition_level=competition_level,
        )

    def _calc_opportunity_score(self, volume_score: float, competition_score: float) -> int:
        raw = volume_score * 0.60 + (100.0 - competition_score) * 0.40
        return max(1, min(100, round(raw)))

    def _extract_similar_tags(self, keyword: str, analyzed: list[_AnalyzedResult]) -> list[KeywordSimilarTag]:
        query_tokens = set(_keyword_tokens(keyword))
        counter: Counter[str] = Counter()

        for item in analyzed:
            seen_in_video: set[str] = set()
            for raw_tag in item.video.tags:
                normalized = _normalize_tag(raw_tag)
                if not normalized or _is_query_tag(normalized, query_tokens):
                    continue
                seen_in_video.add(normalized)

            for token in extract_title_keywords(item.video.title):
                if _is_query_tag(token, query_tokens):
                    continue
                seen_in_video.add(token)

            for tag in seen_in_video:
                counter[tag] += 1

        total = len(analyzed)
        ranked = counter.most_common(SIMILAR_TAGS_LIMIT)
        return [
            KeywordSimilarTag(
                tag=tag,
                frequency=frequency,
                relevance=round(frequency / total, 4),
            )
            for tag, frequency in ranked
        ]

    def _build_top_results(self, analyzed: list[_AnalyzedResult]) -> list[KeywordTopResultItem]:
        return [
            KeywordTopResultItem(
                rank=item.rank,
                video_id=item.video.video_id,
                title=item.video.title,
                views_count=item.video.views_count,
                channel_id=item.video.channel_id,
                channel_title=item.channel_title,
                channel_subscribers=item.channel_subscribers,
            )
            for item in analyzed
        ]

    def _build_recommendation(
        self,
        keyword: str,
        *,
        opportunity_score: int,
        volume: KeywordVolumeMetrics,
        competition: KeywordCompetitionMetrics,
    ) -> str:
        volume_label = _volume_label(volume.volume_score)
        competition_label = {
            CompetitionLevel.LOW: "низкая",
            CompetitionLevel.MEDIUM: "средняя",
            CompetitionLevel.HIGH: "высокая",
        }[competition.competition_level]

        if opportunity_score >= 75:
            verdict = "Отличная ниша для вечнозелёного контента (туториалы, лайфхаки, обзоры)."
        elif opportunity_score >= 50:
            verdict = "Умеренный потенциал: стоит протестировать формат, но потребуется сильный контент."
        else:
            verdict = "Слабая возможность: высокий барьер входа или низкий спрос."

        return (
            f"Запрос «{keyword}»: объём {volume_label} ({volume.volume_score}/100), "
            f"конкуренция {competition_label} ({competition.competition_score}/100). "
            f"Оценка возможности {opportunity_score}/100. {verdict}"
        )


def _keyword_tokens(keyword: str) -> list[str]:
    return [token for token in re.split(r"\s+", keyword.strip().lower()) if token]


def _normalize_tag(value: str) -> str:
    return value.strip().lower()


def _keyword_in_tags(query_tokens: list[str], tags: tuple[str, ...]) -> bool:
    if not query_tokens or not tags:
        return False
    normalized_tags = [_normalize_tag(tag) for tag in tags]
    joined = " ".join(normalized_tags)
    return all(token in joined for token in query_tokens)


def _keyword_in_text(query_tokens: list[str], text: str) -> bool:
    if not query_tokens:
        return False
    lowered = text.lower()
    return all(token in lowered for token in query_tokens)


def _is_query_tag(tag: str, query_tokens: set[str]) -> bool:
    if tag in query_tokens:
        return True
    return any(token in tag.split() and len(token) >= 3 for token in query_tokens)


def _competition_level(score: float) -> CompetitionLevel:
    if score >= 70:
        return CompetitionLevel.HIGH
    if score >= 40:
        return CompetitionLevel.MEDIUM
    return CompetitionLevel.LOW


def _volume_label(score: float) -> str:
    if score >= 70:
        return "высокий"
    if score >= 40:
        return "средний"
    return "низкий"
