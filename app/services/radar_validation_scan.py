"""Validation scan orchestration hooks (Stage 1.8)."""

from __future__ import annotations

from app.services.explosive_channels_radar_worker import (
    AnalysisScanResult,
    ExplosiveChannelsRadarWorker,
)
from app.services.radar_candidate_enrichment import VideoDetailsClient, enrich_radar_candidates
from app.services.radar_validation_format import validation_content_filters


async def run_validation_analysis_scan(
    worker: ExplosiveChannelsRadarWorker,
    keyword: str,
    *,
    youtube_client: VideoDetailsClient | None = None,
) -> tuple[AnalysisScanResult, dict[str, int]]:
    """
    Dry-run keyword scan with validation format filters enabled.

    Shorts and LIVE streams are excluded via the existing
    filter_radar_videos_by_format() path before RadarCandidate creation.
    """
    with validation_content_filters():
        result = await worker.run_analysis_scan(keyword)
    enrichment_meta = {"missing_video_count": 0}
    if youtube_client is not None:
        enrichment_meta = enrich_radar_candidates(result.candidates, youtube_client)
    return result, enrichment_meta
