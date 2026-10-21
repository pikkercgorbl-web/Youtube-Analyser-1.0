"""Read-only single-channel analysis (InnerTube shelf + optional YouTube Data API enrich)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.integrations.youtube.client import (
    ChannelVideoBrowseModel,
    YouTubeApiClient,
    YouTubeApiError,
    YouTubeVideoDetails,
)
from app.integrations.youtube.key_manager import YouTubeApiKeyError
from app.models.orm import VideoFormat
from app.models.schemas import (
    ChannelSingleAgePeerSample,
    ChannelSingleAnalysisEnrichRequest,
    ChannelSingleAnalysisEnrichResponse,
    ChannelSingleAnalysisPublication,
    ChannelSingleAnalysisShelfMoreRequest,
    ChannelSingleAnalysisShelfMoreResponse,
    ChannelSingleAnalysisShelfRequest,
    ChannelSingleAnalysisShelfResponse,
    ChannelSingleCompareRequest,
    ChannelSingleCompareResponse,
    ChannelSingleFocusComparison,
)
from app.services.channel_single_analysis_compare import (
    FocusComparisonResult,
    PublicationForCompare,
    classify_from_api_details,
    compute_focus_comparison,
    publication_kind_from_format,
)
from app.utils.youtube import extract_channel_identifier
from app.services.metrics import utc_now

logger = logging.getLogger(__name__)

SHELF_LIMIT = 30
SHELF_MAX_TOTAL = 100
SHELF_MORE_STEP = 30
ENRICH_API_TIMEOUT_SECONDS = 45.0
INNERTUBE_PAGINATION_NOTE = (
    "Вкладка Videos загружается с начала; каждая порция повторно запрашивает уже показанные id у InnerTube."
)


async def _resolve_channel_id(
    client: YouTubeApiClient,
    *,
    channel_id: str | None,
    channel_ref: str | None,
) -> tuple[str, str]:
    if channel_id and channel_id.strip():
        return channel_id.strip(), ""
    if not channel_ref or not channel_ref.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите channel_id или ссылку / @handle канала.",
        )
    try:
        identifier = extract_channel_identifier(channel_ref.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        return await client.resolve_channel_identifier(identifier)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _browse_to_publication(
    browse: ChannelVideoBrowseModel,
    channel_id: str,
) -> ChannelSingleAnalysisPublication:
    return ChannelSingleAnalysisPublication(
        video_id=browse.video_id,
        title=browse.title,
        thumbnail_url=browse.thumbnail_url,
        views_count=browse.views_count,
        published_text=browse.published_text,
        duration_text=browse.duration_text,
        url=browse.url or f"https://www.youtube.com/watch?v={browse.video_id}",
        kind="unknown",
        published_at=None,
        duration_seconds=None,
        in_feed=True,
        channel_id=channel_id,
    )


def _details_to_compare(details: YouTubeVideoDetails) -> PublicationForCompare:
    fmt = classify_from_api_details(details)
    return PublicationForCompare(
        video_id=details.video_id,
        channel_id=details.channel_id or "",
        views_count=details.views_count,
        published_at=details.published_at,
        content_format=fmt,
    )


def _merge_publication(
    base: ChannelSingleAnalysisPublication,
    details: YouTubeVideoDetails | None,
) -> ChannelSingleAnalysisPublication:
    if details is None:
        return base
    fmt = classify_from_api_details(details)
    kind = publication_kind_from_format(fmt).value
    return base.model_copy(
        update={
            "views_count": details.views_count if details.views_count > 0 else base.views_count,
            "kind": kind,
            "published_at": details.published_at,
            "duration_seconds": details.duration_seconds if details.duration_seconds > 0 else None,
            "channel_id": details.channel_id or base.channel_id,
        },
    )


def _comparison_schema(
    result: FocusComparisonResult,
    publications_by_id: dict[str, ChannelSingleAnalysisPublication] | None = None,
) -> ChannelSingleFocusComparison:
    by_id = publications_by_id or {}
    age_peer_samples = [
        ChannelSingleAgePeerSample(
            video_id=match.video_id,
            title=(by_id.get(match.video_id).title if by_id.get(match.video_id) else ""),
            thumbnail_url=(by_id.get(match.video_id).thumbnail_url if by_id.get(match.video_id) else ""),
            views_count=match.views_count,
            age_hours=match.age_hours,
        )
        for match in result.age_peer_matches
    ]
    return ChannelSingleFocusComparison(
        status=result.status,
        multiplier=result.multiplier,
        peer_count=result.peer_count,
        median_views=result.median_views,
        focus_views=result.focus_views,
        focus_age_hours=result.focus_age_hours,
        peer_age_min_hours=result.peer_age_min_hours,
        peer_age_max_hours=result.peer_age_max_hours,
        searched_age_low_hours=result.searched_age_low_hours,
        searched_age_high_hours=result.searched_age_high_hours,
        age_peer_samples=age_peer_samples,
        message=result.message,
        disclaimer=result.disclaimer,
    )


def _format_for_kind(kind: str) -> VideoFormat | None:
    if kind == "regular":
        return VideoFormat.MEDIUM
    if kind == "short":
        return VideoFormat.SHORT
    if kind == "live":
        return VideoFormat.LIVE
    return None


def _publication_needs_api_fetch(pub: ChannelSingleAnalysisPublication | None) -> bool:
    if pub is None:
        return True
    return pub.published_at is None or pub.kind == "unknown"


def _build_compare_catalog(
    enriched_publications: list[ChannelSingleAnalysisPublication],
    channel_id: str,
) -> list[PublicationForCompare]:
    catalog: list[PublicationForCompare] = []
    for pub in enriched_publications:
        if pub.published_at is None:
            continue
        fmt = _format_for_kind(pub.kind)
        catalog.append(
            PublicationForCompare(
                video_id=pub.video_id,
                channel_id=pub.channel_id or channel_id,
                views_count=pub.views_count,
                published_at=pub.published_at,
                content_format=fmt,
            ),
        )
    return catalog


def _resolve_focus_compare_input(
    *,
    channel_id: str,
    focus_id: str,
    focus_pub: ChannelSingleAnalysisPublication | None,
    details_by_id: dict[str, YouTubeVideoDetails],
) -> PublicationForCompare | None:
    detail = details_by_id.get(focus_id)
    if detail is not None:
        return _details_to_compare(detail)
    if focus_pub and focus_pub.published_at and focus_pub.kind == "regular":
        return PublicationForCompare(
            video_id=focus_pub.video_id,
            channel_id=focus_pub.channel_id or channel_id,
            views_count=focus_pub.views_count,
            published_at=focus_pub.published_at,
            content_format=VideoFormat.MEDIUM,
        )
    return None


def _compute_comparison_result(
    *,
    channel_id: str,
    focus_id: str,
    focus_pub: ChannelSingleAnalysisPublication | None,
    enriched_publications: list[ChannelSingleAnalysisPublication],
    details_by_id: dict[str, YouTubeVideoDetails],
    enrichment_error: str | None,
) -> FocusComparisonResult:
    disclaimer = (
        "Ориентировочное сравнение текущих просмотров. "
        "Это не замеры на одинаковом возрасте видео."
    )
    if enrichment_error and not details_by_id:
        return FocusComparisonResult(
            status="insufficient_data",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=focus_pub.views_count if focus_pub and focus_pub.views_count > 0 else None,
            focus_age_hours=None,
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=None,
            searched_age_high_hours=None,
            age_peer_matches=(),
            message="Недостаточно данных",
            disclaimer=disclaimer,
        )

    catalog = _build_compare_catalog(enriched_publications, channel_id)
    focus_compare_input: PublicationForCompare | None = None
    if focus_id:
        focus_compare_input = _resolve_focus_compare_input(
            channel_id=channel_id,
            focus_id=focus_id,
            focus_pub=focus_pub,
            details_by_id=details_by_id,
        )

    return compute_focus_comparison(
        channel_id=channel_id,
        focus=focus_compare_input,
        catalog=catalog,
        now=utc_now(),
    )


async def _fetch_video_details(
    client: YouTubeApiClient,
    video_ids: list[str],
) -> tuple[dict[str, YouTubeVideoDetails], str | None]:
    if not video_ids:
        return {}, None
    try:
        details_list = await asyncio.wait_for(
            asyncio.to_thread(client.get_videos, video_ids),
            timeout=ENRICH_API_TIMEOUT_SECONDS,
        )
        return {row.video_id: row for row in details_list}, None
    except asyncio.TimeoutError:
        return {}, "Таймаут загрузки метаданных видео (YouTube Data API)."
    except YouTubeApiKeyError:
        return {}, "YouTube Data API недоступна (нет ключей). Сравнение не рассчитано."
    except YouTubeApiError as exc:
        logger.warning("channel_single video fetch failed: %s", exc)
        return {}, f"Не удалось обогатить метаданные: {exc}"


def _resolve_focus_publication(
    *,
    channel_id: str,
    focus_id: str,
    by_id: dict[str, ChannelSingleAnalysisPublication],
    details_by_id: dict[str, YouTubeVideoDetails],
) -> tuple[ChannelSingleAnalysisPublication | None, bool]:
    focus_supplement = bool(focus_id and focus_id not in by_id)
    if not focus_id:
        return None, False
    if focus_id in by_id:
        return _merge_publication(by_id[focus_id], details_by_id.get(focus_id)), focus_supplement
    if focus_id in details_by_id:
        detail = details_by_id[focus_id]
        return (
            ChannelSingleAnalysisPublication(
                video_id=focus_id,
                channel_id=detail.channel_id or channel_id,
                title=detail.title,
                thumbnail_url="",
                views_count=detail.views_count,
                published_text="",
                duration_text="",
                url=f"https://www.youtube.com/watch?v={focus_id}",
                kind=publication_kind_from_format(classify_from_api_details(detail)).value,
                published_at=detail.published_at,
                duration_seconds=detail.duration_seconds if detail.duration_seconds > 0 else None,
                in_feed=False,
            ),
            True,
        )
    return None, focus_supplement


async def run_channel_single_shelf(
    client: YouTubeApiClient,
    request: ChannelSingleAnalysisShelfRequest,
) -> ChannelSingleAnalysisShelfResponse:
    try:
        channel_id, title_hint = await _resolve_channel_id(
            client,
            channel_id=request.channel_id,
            channel_ref=request.channel_ref,
        )
    except HTTPException:
        raise
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        details, (tab_title, browse_videos) = await asyncio.gather(
            client.get_channel_details(channel_id),
            client.get_channel_videos_tab(channel_id, max_results=SHELF_LIMIT),
        )
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    resolved_title = tab_title if tab_title and tab_title != channel_id else (title_hint or channel_id)

    publications = [_browse_to_publication(v, channel_id) for v in browse_videos]
    fetched_at = datetime.now(timezone.utc)

    return ChannelSingleAnalysisShelfResponse(
        channel_id=channel_id,
        channel_title=resolved_title if resolved_title != channel_id else (title_hint or channel_id),
        subscribers_count=details.subscribers_count if details.subscribers_count > 0 else None,
        channel_avatar_url=details.channel_avatar_url,
        feed_loaded_count=len(publications),
        publications=publications,
        fetched_at=fetched_at,
    )


async def enrich_publications_for_channel(
    client: YouTubeApiClient,
    *,
    channel_id: str,
    publications: list[ChannelSingleAnalysisPublication],
) -> tuple[list[ChannelSingleAnalysisPublication], int, str | None]:
    """Batch videos.list merge without focus or peer comparison."""
    cid = channel_id.strip()
    by_id: dict[str, ChannelSingleAnalysisPublication] = {
        p.video_id: p.model_copy(update={"channel_id": cid}) for p in publications
    }
    feed_ids = list(by_id.keys())
    ids_to_fetch: list[str] = [
        vid for vid in dict.fromkeys(feed_ids) if _publication_needs_api_fetch(by_id[vid])
    ]
    details_by_id, enrichment_error = await _fetch_video_details(client, ids_to_fetch)
    enriched_publications: list[ChannelSingleAnalysisPublication] = []
    for vid in feed_ids:
        enriched_publications.append(_merge_publication(by_id[vid], details_by_id.get(vid)))
    regular_confirmed = sum(1 for p in enriched_publications if p.kind == "regular" and p.published_at)
    return enriched_publications, regular_confirmed, enrichment_error


async def run_channel_single_enrich(
    client: YouTubeApiClient,
    request: ChannelSingleAnalysisEnrichRequest,
) -> ChannelSingleAnalysisEnrichResponse:
    channel_id = request.channel_id.strip()
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel_id обязателен.",
        )

    by_id: dict[str, ChannelSingleAnalysisPublication] = {
        p.video_id: p.model_copy(update={"channel_id": channel_id}) for p in request.publications
    }
    feed_ids = list(by_id.keys())

    ids_to_fetch: list[str] = [
        vid for vid in dict.fromkeys(feed_ids) if _publication_needs_api_fetch(by_id[vid])
    ]
    focus_id = (request.focus_video_id or "").strip()
    if focus_id:
        focus_existing = by_id.get(focus_id)
        if focus_existing is None or _publication_needs_api_fetch(focus_existing):
            if focus_id not in ids_to_fetch:
                ids_to_fetch.append(focus_id)

    details_by_id, enrichment_error = await _fetch_video_details(client, ids_to_fetch)

    enriched_publications: list[ChannelSingleAnalysisPublication] = []
    for vid in feed_ids:
        enriched_publications.append(_merge_publication(by_id[vid], details_by_id.get(vid)))

    regular_confirmed = sum(1 for p in enriched_publications if p.kind == "regular" and p.published_at)

    focus_pub, focus_supplement = _resolve_focus_publication(
        channel_id=channel_id,
        focus_id=focus_id,
        by_id=by_id,
        details_by_id=details_by_id,
    )
    if focus_id and focus_pub is None:
        enrichment_error = enrichment_error or "Выбранное видео не найдено при обогащении."

    comparison = _compute_comparison_result(
        channel_id=channel_id,
        focus_id=focus_id,
        focus_pub=focus_pub,
        enriched_publications=enriched_publications,
        details_by_id=details_by_id,
        enrichment_error=enrichment_error,
    )

    return ChannelSingleAnalysisEnrichResponse(
        channel_id=channel_id,
        publications=enriched_publications,
        regular_confirmed_count=regular_confirmed,
        focus=focus_pub,
        focus_loaded_separately=focus_supplement,
        comparison=_comparison_schema(comparison, {p.video_id: p for p in enriched_publications}),
        enrichment_error=enrichment_error,
    )


async def run_channel_single_shelf_more(
    client: YouTubeApiClient,
    request: ChannelSingleAnalysisShelfMoreRequest,
) -> ChannelSingleAnalysisShelfMoreResponse:
    channel_id = request.channel_id.strip()
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel_id обязателен.",
        )

    max_total = min(max(1, request.max_total), SHELF_MAX_TOTAL)
    existing_ids = list(dict.fromkeys(v.strip() for v in request.existing_video_ids if v.strip()))
    current_count = len(existing_ids)
    existing_set = set(existing_ids)

    if current_count >= max_total:
        return ChannelSingleAnalysisShelfMoreResponse(
            channel_id=channel_id,
            new_publications=[],
            feed_loaded_count=current_count,
            has_more=False,
            pagination_note=INNERTUBE_PAGINATION_NOTE,
            fetched_at=datetime.now(timezone.utc),
        )

    target = min(current_count + SHELF_MORE_STEP, max_total)
    try:
        _, browse_videos = await client.get_channel_videos_tab(channel_id, max_results=target)
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    new_publications = [
        _browse_to_publication(v, channel_id)
        for v in browse_videos
        if v.video_id not in existing_set
    ]
    total_unique = len({v.video_id for v in browse_videos} | existing_set)
    has_more = len(browse_videos) >= target and target < max_total

    return ChannelSingleAnalysisShelfMoreResponse(
        channel_id=channel_id,
        new_publications=new_publications,
        feed_loaded_count=total_unique,
        has_more=has_more,
        pagination_note=INNERTUBE_PAGINATION_NOTE,
        fetched_at=datetime.now(timezone.utc),
    )


async def run_channel_single_compare(
    client: YouTubeApiClient,
    request: ChannelSingleCompareRequest,
) -> ChannelSingleCompareResponse:
    """Recompute comparison; fetch YouTube details only for focus when missing."""
    channel_id = request.channel_id.strip()
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="channel_id обязателен.",
        )

    enriched_publications = [
        p.model_copy(update={"channel_id": channel_id}) for p in request.publications
    ]
    by_id = {p.video_id: p for p in enriched_publications}
    focus_id = (request.focus_video_id or "").strip()

    ids_to_fetch: list[str] = []
    if focus_id:
        existing = by_id.get(focus_id)
        if _publication_needs_api_fetch(existing):
            ids_to_fetch.append(focus_id)

    details_by_id, enrichment_error = await _fetch_video_details(client, ids_to_fetch)

    focus_pub, focus_supplement = _resolve_focus_publication(
        channel_id=channel_id,
        focus_id=focus_id,
        by_id=by_id,
        details_by_id=details_by_id,
    )

    comparison = _compute_comparison_result(
        channel_id=channel_id,
        focus_id=focus_id,
        focus_pub=focus_pub,
        enriched_publications=enriched_publications,
        details_by_id=details_by_id,
        enrichment_error=enrichment_error if focus_id in ids_to_fetch else None,
    )

    pub_by_id = {p.video_id: p for p in enriched_publications}
    if focus_pub:
        pub_by_id[focus_pub.video_id] = focus_pub

    return ChannelSingleCompareResponse(
        comparison=_comparison_schema(comparison, pub_by_id),
        focus=focus_pub,
        focus_loaded_separately=focus_supplement and focus_id not in by_id,
        enrichment_error=enrichment_error if focus_id in ids_to_fetch else None,
    )
