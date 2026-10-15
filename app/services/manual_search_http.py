"""HTTP helpers for manual POST /api/search (timing + phased enrichment)."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

from fastapi import HTTPException, status

from app.integrations.youtube.client import EnrichedVideoModel, YouTubeApiError, _get_innertube_client, get_enriched_search_results
from app.models.schemas import ManualSearchResponse, ManualSearchTimingResponse, SearchEnrichRequest, SearchFiltersModel, SearchRequest
from app.services.manual_search_pipeline import (
    ManualSearchTiming,
    StageTimer,
    channel_browse_needed,
    channels_missing_subscriber_details,
    merge_channel_details,
    propagate_subscribers_within_batch,
    subscribers_enrichment_needed,
)
from app.services.video_filter_service import VideoFilterService

logger = logging.getLogger(__name__)


def _timing_payload(timing: ManualSearchTiming, include: bool) -> ManualSearchTimingResponse | None:
    if not include:
        return None
    return ManualSearchTimingResponse.model_validate(asdict(timing))


def _filters_config(request: SearchRequest | SearchEnrichRequest) -> dict:
    return (request.filters or SearchFiltersModel()).model_dump()


def _apply_filter_sort(
    items: list[EnrichedVideoModel],
    *,
    filters_config: dict,
    sort_by: str,
    timing: ManualSearchTiming,
    allow_incomplete_channel: bool,
) -> list[EnrichedVideoModel]:
    filter_service = VideoFilterService()
    with StageTimer(timing, "filter_sort_wall_ms"):
        filtered = filter_service.apply_filters(
            items,
            filters_config,
            allow_incomplete_channel=allow_incomplete_channel,
        )
        try:
            return filter_service.sort_results(filtered, sort_by)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc


async def run_manual_search(request: SearchRequest) -> ManualSearchResponse:
    timing = ManualSearchTiming()
    total_started = time.perf_counter()
    filters_config = _filters_config(request)
    need_browse = channel_browse_needed(filters_config, request.sort_by)
    phase = request.phase or "full"

    fetch_browse = need_browse if phase != "basic" else False

    try:
        enriched = await get_enriched_search_results(
            request.query,
            max_results=50,
            sort_by_upload_date=request.sort_by.strip().lower() == "date",
            save_to_db=False,
            fetch_channel_browse=fetch_browse,
            timing=timing,
        )
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if phase == "basic" and need_browse:
        items = enriched
        needs_enrichment = True
    else:
        items = _apply_filter_sort(
            enriched,
            filters_config=filters_config,
            sort_by=request.sort_by,
            timing=timing,
            allow_incomplete_channel=not fetch_browse,
        )
        needs_enrichment = subscribers_enrichment_needed(items)

    timing.total_wall_ms = (time.perf_counter() - total_started) * 1000.0
    timing.result_count = len(items)
    logger.info("manual_search phase=%s %s", phase, timing.to_log_dict())

    return ManualSearchResponse(
        items=items,
        needs_channel_enrichment=needs_enrichment,
        timing=_timing_payload(timing, request.include_timing),
    )


async def run_manual_search_enrich(request: SearchEnrichRequest) -> ManualSearchResponse:
    timing = ManualSearchTiming()
    total_started = time.perf_counter()
    filters_config = _filters_config(request)
    client = _get_innertube_client()
    channel_ids = channels_missing_subscriber_details(request.items)
    try:
        channel_map = (
            await client.fetch_channel_details_map(channel_ids, timing=timing)
            if channel_ids
            else {}
        )
    except YouTubeApiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    enriched = propagate_subscribers_within_batch(
        merge_channel_details(request.items, channel_map),
    )
    items = _apply_filter_sort(
        enriched,
        filters_config=filters_config,
        sort_by=request.sort_by,
        timing=timing,
        allow_incomplete_channel=False,
    )
    timing.total_wall_ms = (time.perf_counter() - total_started) * 1000.0
    timing.result_count = len(items)
    logger.info("manual_search enrich %s", timing.to_log_dict())

    return ManualSearchResponse(
        items=items,
        needs_channel_enrichment=False,
        timing=_timing_payload(timing, request.include_timing),
    )
