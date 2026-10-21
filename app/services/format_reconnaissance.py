"""Read-only «Format reconnaissance» prototype (manual search + channel preview)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.integrations.youtube.client import EnrichedVideoModel, YouTubeApiClient, get_enriched_search_results
from app.models.schemas import CompetitorChannelPreviewRequest
from app.services.competitor_channels_preview import run_competitor_channel_preview
from app.services.format_reconnaissance_match import assess_publication_against_hypothesis
from app.services.format_reconnaissance_query_suggest import FormatSearchDirection, suggest_format_search_directions
from app.utils.youtube import extract_video_id_from_url

DEFAULT_RESULTS_PER_QUERY = 25
DEFAULT_MAX_CHANNEL_PREVIEWS = 6
DEFAULT_MAX_DIRECTIONS = 3
INNERTUBE_PAGES_PER_SEARCH = 2  # documented estimate, aligns with similar watch page budget


@dataclass
class FormatReconnaissanceRequest:
    format_description: str
    example_video_url: str | None = None
    search_queries: list[str] | None = None
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY
    max_channel_previews: int = DEFAULT_MAX_CHANNEL_PREVIEWS


@dataclass
class SearchHitSummary:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    views_count: int
    matched_query: str
    duration_text: str = ""


@dataclass
class ChannelReconSummary:
    channel_id: str
    channel_title: str
    subscribers_count: int | None
    search_hits: int
    feed_loaded_count: int
    likely_format_count: int
    partial_or_better_count: int
    pattern_label: str
    example_publications: list[dict[str, Any]] = field(default_factory=list)
    preview_error: str | None = None


@dataclass
class FormatReconnaissanceReport:
    format_description: str
    example_video_title: str | None
    suggested_directions: list[FormatSearchDirection]
    queries_used: list[str]
    search_hits_total: int
    unique_channels_in_search: int
    channels: list[ChannelReconSummary]
    limitations: list[str]
    query_cost_note: str
    manual_verification: list[str]
    generated_at: datetime


async def _example_title_from_url(client: YouTubeApiClient, url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    video_id = extract_video_id_from_url(url.strip())
    if not video_id:
        return None
    try:
        details_list = await asyncio.to_thread(client.get_videos, [video_id])
        return details_list[0].title if details_list else None
    except Exception:
        return None


async def run_format_reconnaissance(
    client: YouTubeApiClient,
    request: FormatReconnaissanceRequest,
) -> FormatReconnaissanceReport:
    example_title = await _example_title_from_url(client, request.example_video_url)
    directions = suggest_format_search_directions(
        format_description=request.format_description,
        example_video_title=example_title,
    )
    if request.search_queries:
        queries = [q.strip() for q in request.search_queries if q and q.strip()][:DEFAULT_MAX_DIRECTIONS]
    else:
        queries = [d.query for d in directions]

    hits: list[SearchHitSummary] = []
    for query in queries:
        items: list[EnrichedVideoModel] = await get_enriched_search_results(
            query,
            max_results=max(10, min(50, request.results_per_query)),
            sort_by_upload_date=False,
            save_to_db=False,
            fetch_channel_browse=False,
        )
        for row in items:
            v = row.video
            hits.append(
                SearchHitSummary(
                    video_id=v.video_id,
                    title=v.title,
                    channel_id=v.channel_id,
                    channel_title=v.channel_title or row.channel.title if row.channel else "",
                    views_count=int(v.views_count or 0),
                    matched_query=query,
                    duration_text=v.duration_text or "",
                ),
            )

    by_channel: dict[str, list[SearchHitSummary]] = defaultdict(list)
    for h in hits:
        if h.channel_id:
            by_channel[h.channel_id].append(h)

    ranked_channels = sorted(
        by_channel.items(),
        key=lambda item: (len(item[1]), sum(x.views_count for x in item[1])),
        reverse=True,
    )
    preview_targets = ranked_channels[: max(1, request.max_channel_previews)]

    channel_summaries: list[ChannelReconSummary] = []
    for channel_id, channel_hits in preview_targets:
        title = channel_hits[0].channel_title if channel_hits else ""
        preview = None
        preview_error: str | None = None
        try:
            preview = await run_competitor_channel_preview(
                client,
                CompetitorChannelPreviewRequest(channel_id=channel_id, input_ref=channel_id),
            )
        except Exception as exc:
            preview_error = str(exc)

        likely = 0
        partial_plus = 0
        examples: list[dict[str, Any]] = []
        feed_count = 0
        subs = None

        if preview is not None:
            title = preview.channel_title or title
            subs = preview.subscribers_count
            feed_count = preview.feed_loaded_count
            assessed_rows: list[tuple[Any, Any]] = []
            for pub in preview.publications:
                if pub.kind == "short":
                    continue
                assessment = assess_publication_against_hypothesis(
                    title=pub.title,
                    duration_text=pub.duration_text,
                    duration_seconds=pub.duration_seconds,
                    kind=pub.kind,
                    format_description=request.format_description,
                )
                assessed_rows.append((pub, assessment))
                if assessment.tier in ("strong", "partial"):
                    partial_plus += 1
                if assessment.tier == "strong":
                    likely += 1

            assessed_rows.sort(key=lambda x: (-x[1].score, -x[0].views_count))
            for pub, assessment in assessed_rows[:3]:
                examples.append(
                    {
                        "video_id": pub.video_id,
                        "title": pub.title,
                        "views_count": pub.views_count,
                        "published_text": pub.published_text,
                        "published_at": pub.published_at.isoformat() if pub.published_at else None,
                        "duration_text": pub.duration_text,
                        "duration_seconds": pub.duration_seconds,
                        "match_tier": assessment.tier,
                        "match_score": assessment.score,
                        "match_reasons": list(assessment.reasons),
                        "url": pub.url,
                    },
                )

        if partial_plus >= 3:
            pattern = "Повторяющийся паттерн (≥3 ролика partial+ на полке)"
        elif partial_plus == 2:
            pattern = "Возможный паттерн (2 ролика partial+)"
        elif partial_plus == 1:
            pattern = "Единичное совпадение на полке — возможен one-hit"
        else:
            pattern = "На полке нет уверенных совпадений по метаданным"

        channel_summaries.append(
            ChannelReconSummary(
                channel_id=channel_id,
                channel_title=title,
                subscribers_count=subs,
                search_hits=len(channel_hits),
                feed_loaded_count=feed_count,
                likely_format_count=likely,
                partial_or_better_count=partial_plus,
                pattern_label=pattern,
                example_publications=examples,
                preview_error=preview_error,
            ),
        )

    # Include channels only seen in search if we have room in report list (up to 10 total mentioned)
    extra_ids = {cid for cid, _ in ranked_channels[request.max_channel_previews : 10]}
    for channel_id in extra_ids:
        ch_hits_list = by_channel[channel_id]
        channel_summaries.append(
            ChannelReconSummary(
                channel_id=channel_id,
                channel_title=ch_hits_list[0].channel_title,
                subscribers_count=None,
                search_hits=len(ch_hits_list),
                feed_loaded_count=0,
                likely_format_count=0,
                partial_or_better_count=0,
                pattern_label="Только попадание в поиск — preview не загружался",
                example_publications=[
                    {
                        "video_id": h.video_id,
                        "title": h.title,
                        "views_count": h.views_count,
                        "matched_query": h.matched_query,
                        "duration_text": h.duration_text,
                        "url": f"https://www.youtube.com/watch?v={h.video_id}",
                    }
                    for h in ch_hits_list[:2]
                ],
            ),
        )

    limitations = [
        "InnerTube search не видит содержимое ролика — только название, длительность, просмотры.",
        "Одинаковые каналы могут доминировать в выдаче по популярным sleep/history запросам.",
        "Полка канала — до ~30 последних Videos; старый успешный формат может быть вне окна.",
        "Сортировка search по умолчанию — релевантность YouTube, не «качество формата».",
    ]
    cost_note = (
        f"≈{len(queries)} поисковых запросов × до {INNERTUBE_PAGES_PER_SEARCH} страниц InnerTube каждый "
        f"(до {request.results_per_query} карточек/запрос); "
        f"до {len(preview_targets)} preview каналов (полка + enrich, YouTube Data API quota на enrich)."
    )
    manual = [
        "Просмотр 1–2 роликов: статичные кадры vs видео, тип озвучки, ведущий в кадре",
        "Субъективная «успокаивающая» подача и историческая точность",
        "Монетизация и доход не оцениваются",
    ]

    return FormatReconnaissanceReport(
        format_description=request.format_description.strip(),
        example_video_title=example_title,
        suggested_directions=directions,
        queries_used=queries,
        search_hits_total=len(hits),
        unique_channels_in_search=len(by_channel),
        channels=channel_summaries,
        limitations=limitations,
        query_cost_note=cost_note,
        manual_verification=manual,
        generated_at=datetime.now(timezone.utc),
    )


def report_to_dict(report: FormatReconnaissanceReport) -> dict[str, Any]:
    return {
        "format_description": report.format_description,
        "example_video_title": report.example_video_title,
        "suggested_directions": [
            {"query": d.query, "rationale": d.rationale} for d in report.suggested_directions
        ],
        "queries_used": report.queries_used,
        "search_hits_total": report.search_hits_total,
        "unique_channels_in_search": report.unique_channels_in_search,
        "channels": [
            {
                "channel_id": c.channel_id,
                "channel_title": c.channel_title,
                "subscribers_count": c.subscribers_count,
                "search_hits": c.search_hits,
                "feed_loaded_count": c.feed_loaded_count,
                "likely_format_count": c.likely_format_count,
                "partial_or_better_count": c.partial_or_better_count,
                "pattern_label": c.pattern_label,
                "example_publications": c.example_publications,
                "preview_error": c.preview_error,
            }
            for c in report.channels
        ],
        "limitations": report.limitations,
        "query_cost_note": report.query_cost_note,
        "manual_verification": report.manual_verification,
        "generated_at": report.generated_at.isoformat(),
    }
