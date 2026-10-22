"""Read-only competitor channel preview (shelf + enrich, no DB)."""

from __future__ import annotations

from app.integrations.youtube.client import YouTubeApiClient
from app.models.schemas import (
    ChannelSingleAnalysisShelfRequest,
    CompetitorChannelPreviewRequest,
    CompetitorChannelPreviewResponse,
)
from app.services.channel_single_analysis_http import (
    enrich_publications_for_channel,
    run_channel_single_shelf,
)


async def run_competitor_channel_preview(
    client: YouTubeApiClient,
    request: CompetitorChannelPreviewRequest,
) -> CompetitorChannelPreviewResponse:
    input_ref = (request.input_ref or request.channel_ref or request.channel_id or "").strip()
    shelf = await run_channel_single_shelf(
        client,
        ChannelSingleAnalysisShelfRequest(
            channel_id=request.channel_id,
            channel_ref=request.channel_ref,
        ),
    )

    enriched, regular_count, enrichment_error = await enrich_publications_for_channel(
        client,
        channel_id=shelf.channel_id,
        publications=shelf.publications,
    )

    load_status = "partial" if enrichment_error else "ready"
    return CompetitorChannelPreviewResponse(
        input_ref=input_ref or shelf.channel_id,
        channel_id=shelf.channel_id,
        channel_title=shelf.channel_title,
        subscribers_count=shelf.subscribers_count,
        channel_avatar_url=shelf.channel_avatar_url,
        feed_loaded_count=shelf.feed_loaded_count,
        regular_confirmed_count=regular_count,
        publications=enriched,
        load_status=load_status,
        enrichment_error=enrichment_error,
        fetched_at=shelf.fetched_at,
    )
