"""Format enriched InnerTube search results into human-readable cards and JSON."""

from __future__ import annotations

from collections import Counter
import json
from typing import Literal

from pydantic import BaseModel, Field

from app.integrations.youtube.client import EnrichedVideoModel
from app.utils.text import extract_title_keywords

OutputFormat = Literal["json", "text"]


class VideoCardOutput(BaseModel):
    """Single video card matching the product spec layout."""

    title: str
    video_url: str
    channel_title: str
    channel_url: str
    published_at: str
    views_count: int
    views_label: str
    channel_total_videos: int
    channel_total_videos_label: str
    virality_coefficient: float
    virality_label: str


class TrendingQueriesWidget(BaseModel):
    """FR-2 widget: similar trending queries derived from top filtered videos."""

    title: str = "Похожие трендовые запросы"
    source_videos_count: int = Field(ge=0)
    queries: list[str] = Field(default_factory=list)


class EnrichedResultsReport(BaseModel):
    """Structured report for enriched and sorted video results."""

    total: int = Field(ge=0)
    cards: list[VideoCardOutput] = Field(default_factory=list)
    trending_queries: TrendingQueriesWidget

    def to_text(self) -> str:
        lines: list[str] = [
            f"Найдено видео: {self.total}",
            "=" * 72,
        ]

        for index, card in enumerate(self.cards, start=1):
            lines.append(f"#{index}")
            lines.extend(_render_video_card_text(card))
            lines.append("-" * 72)

        lines.append("")
        _append_trending_queries_text(lines, self.trending_queries)
        return "\n".join(lines)


def format_enriched_results(
    videos: list[EnrichedVideoModel],
    *,
    output_format: OutputFormat = "json",
) -> str | dict:
    """
    Build a report from a sorted list of enriched videos.

    Returns a JSON-serializable dict by default or a plain-text card layout.
    """
    report = build_enriched_results_report(videos)
    if output_format == "text":
        return report.to_text()
    return report.model_dump()


def build_enriched_results_report(
    videos: list[EnrichedVideoModel],
) -> EnrichedResultsReport:
    """Create a structured report with video cards and the FR-2 widget."""
    return EnrichedResultsReport(
        total=len(videos),
        cards=[_build_video_card(item) for item in videos],
        trending_queries=build_trending_queries_widget(videos),
    )


def build_trending_queries_widget(
    videos: list[EnrichedVideoModel],
    *,
    top_videos: int = 5,
    limit: int = 10,
) -> TrendingQueriesWidget:
    """
    FR-2: extract keywords from top filtered videos as similar trending queries.
    """
    return TrendingQueriesWidget(
        source_videos_count=min(len(videos), top_videos),
        queries=extract_trending_queries(videos, top_videos=top_videos, limit=limit),
    )


def extract_trending_queries(
    videos: list[EnrichedVideoModel],
    *,
    top_videos: int = 5,
    limit: int = 10,
) -> list[str]:
    """Collect and rank keywords from the top-N filtered video titles."""
    keyword_counts: Counter[str] = Counter()

    for item in videos[:top_videos]:
        for keyword in extract_title_keywords(item.video.title):
            keyword_counts[keyword] += 1

    ranked_keywords = [
        keyword
        for keyword, _ in keyword_counts.most_common(limit)
    ]

    if ranked_keywords:
        return ranked_keywords

    return [
        item.video.title.strip()
        for item in videos[:top_videos]
        if item.video.title.strip()
    ][:limit]


def _build_video_card(item: EnrichedVideoModel) -> VideoCardOutput:
    video = item.video
    return VideoCardOutput(
        title=video.title,
        video_url=_build_video_url(video.video_id),
        channel_title=video.channel_title or "Unknown channel",
        channel_url=_build_channel_url(video.channel_id),
        published_at=video.published_text or "—",
        views_count=video.views_count,
        views_label=_format_count(video.views_count),
        channel_total_videos=item.channel.total_videos,
        channel_total_videos_label=_format_count(item.channel.total_videos),
        virality_coefficient=item.virality_coefficient,
        virality_label=_format_virality_label(item.virality_coefficient),
    )


def _build_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _build_channel_url(channel_id: str) -> str:
    if channel_id:
        return f"https://www.youtube.com/channel/{channel_id}"
    return "https://www.youtube.com/"


def _format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_virality_label(value: float) -> str:
    return f"Коэффициент виральности: {value:.2f}"


def _render_video_card_text(card: VideoCardOutput) -> list[str]:
    return [
        card.title,
        card.video_url,
        "",
        f"Канал: {card.channel_title}",
        card.channel_url,
        "",
        f"Дата публикации: {card.published_at}",
        f"Просмотры: {card.views_label}",
        f"Видео на канале: {card.channel_total_videos_label}",
        card.virality_label,
    ]


def _append_trending_queries_text(lines: list[str], widget: TrendingQueriesWidget) -> None:
    lines.append("Похожие трендовые запросы (FR-2)")
    lines.append("-" * 72)
    if not widget.queries:
        lines.append("Нет данных для формирования трендов.")
        return
    for index, query in enumerate(widget.queries, start=1):
        lines.append(f"{index}. {query}")


def render_enriched_results_json(videos: list[EnrichedVideoModel], *, indent: int = 2) -> str:
    """Serialize enriched results report to a JSON string."""
    report = build_enriched_results_report(videos)
    return json.dumps(report.model_dump(), ensure_ascii=False, indent=indent)


def render_enriched_results_text(videos: list[EnrichedVideoModel]) -> str:
    """Render enriched results report as plain text."""
    return build_enriched_results_report(videos).to_text()
