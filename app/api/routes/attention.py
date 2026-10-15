"""Read-only Attention Engine API (Stage 1.22A). Default = persisted snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.schemas import (
    AttentionChannelListResponse,
    AttentionChannelMomentumResponse,
    AttentionParticipatingChannelResponse,
    AttentionPatternDetailResponse,
    AttentionPatternFamilyDetailResponse,
    AttentionPatternFamilyListResponse,
    AttentionPatternFamilyResponse,
    AttentionPatternListResponse,
    AttentionPatternMemberVideoResponse,
    AttentionPatternResponse,
    AttentionRelatedKeywordResponse,
    AttentionSummaryApiResponse,
    AttentionSummaryResponse,
    AttentionVideoDetailResponse,
    AttentionVideoListResponse,
    AttentionVideoWinnerResponse,
    ChannelRelativeSignalResponse,
)
from app.services.attention_engine_service import compute_attention_engine
from app.services.attention_engine_types import (
    AttentionEngineConfig,
    AttentionEngineResult,
    ChannelMomentum,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
)
from app.services.attention_pattern_hydrate import (
    hydrate_participating_channels,
    hydrate_pattern_member_videos,
    hydrate_related_keywords,
    hydrate_videos_by_ids,
)
from app.services.attention_read_model import load_attention_snapshot
from app.services.opportunity_family_presentation import (
    OpportunityFamilyPresentation,
    load_video_title_channel_maps,
    present_opportunity_family,
)

router = APIRouter()


def _family_presentation_context(
    db: Session,
    result: AttentionEngineResult,
    families: list[PatternFamily],
) -> tuple[frozenset[str], dict[str, str], dict[str, str]]:
    winner_id_set = frozenset(row.video_id for row in result.video_winners)
    video_ids: set[str] = set()
    for family in families:
        video_ids.update(family.video_ids)
    titles, channels = load_video_title_channel_maps(
        db,
        video_ids,
        winner_rows=result.video_winners,
    )
    return winner_id_set, titles, channels


def _family_response(
    row: PatternFamily,
    presentation: OpportunityFamilyPresentation | None = None,
) -> AttentionPatternFamilyResponse:
    pres = presentation
    return AttentionPatternFamilyResponse(
        family_key=row.family_key,
        label=row.label,
        family_kind=row.family_kind,
        member_pattern_keys=list(row.member_pattern_keys),
        member_labels=list(row.member_labels),
        video_count=row.video_count,
        channel_count=row.channel_count,
        keyword_count=row.keyword_count,
        breakout_eligible_count=row.breakout_eligible_count,
        videos_last_24h=row.videos_last_24h,
        videos_previous_24h=row.videos_previous_24h,
        videos_previous_48_24h=row.videos_previous_48_24h,
        grouping_reasons=list(row.grouping_reasons),
        quality_flags=list(row.quality_flags),
        support_sources=list(row.support_sources),
        first_seen_at=row.first_seen_at,
        latest_seen_at=row.latest_seen_at,
        participating_video_ids=list(row.video_ids),
        participating_channel_ids=list(row.channel_ids),
        participating_keyword_ids=list(row.keyword_ids),
        opportunity_presentation_tier=(
            pres.opportunity_presentation_tier if pres else "search_collection"
        ),
        grouping_basis_kind=pres.grouping_basis_kind if pres else "unknown",
        grouping_basis_label=pres.grouping_basis_label if pres else "",
        tier_reason=pres.tier_reason if pres else "",
        feed_winner_video_ids=list(pres.feed_winner_video_ids) if pres else [],
        title_evidence_video_ids=list(pres.title_evidence_video_ids) if pres else [],
    )


def _video_response(
    row: VideoWinner,
    *,
    keyword_by_id: dict[int, str] | None = None,
) -> AttentionVideoWinnerResponse:
    rel = None
    if row.channel_relative_signal is not None:
        rel = ChannelRelativeSignalResponse(
            status=row.channel_relative_signal.status,
            baseline_quality=row.channel_relative_signal.baseline_quality,
            comparable_video_count=row.channel_relative_signal.comparable_video_count,
            vph_vs_channel_median=row.channel_relative_signal.vph_vs_channel_median,
            notes=list(row.channel_relative_signal.notes),
        )
    return AttentionVideoWinnerResponse(
        video_id=row.video_id,
        title=row.title,
        channel_id=row.channel_id,
        channel_title=row.channel_title,
        youtube_url=row.youtube_url,
        published_at=row.published_at,
        age_hours=row.age_hours,
        views=row.views,
        vph=row.vph,
        subscribers=row.subscribers,
        breakout_rank=row.breakout_rank,
        breakout_eligible=row.breakout_eligible,
        channel_relative_signal=rel,
        acceleration_state=row.acceleration_state,
        delayed_outcome_state=row.delayed_outcome_state,
        delayed_outcome_growth=row.delayed_outcome_growth,
        reason_codes=list(row.reason_codes),
        human_reasons=list(row.human_reasons),
        keyword_ids=list(row.keyword_ids),
        discovery_keywords=[
            AttentionRelatedKeywordResponse(keyword_id=int(kid), keyword=keyword_by_id[int(kid)])
            for kid in row.keyword_ids
            if keyword_by_id is not None and int(kid) in keyword_by_id
        ],
    )


def _pattern_response(row: PatternCandidate) -> AttentionPatternResponse:
    return AttentionPatternResponse(
        pattern_key=row.pattern_key,
        kind=row.kind,
        label=row.label,
        video_count=row.video_count,
        channel_count=row.channel_count,
        keyword_count=row.keyword_count,
        breakout_video_count=row.breakout_video_count,
        small_channel_winner_count=row.small_channel_winner_count,
        first_seen_at=row.first_seen_at,
        latest_seen_at=row.latest_seen_at,
        videos_last_24h=row.videos_last_24h,
        videos_previous_24h=row.videos_previous_24h,
        videos_previous_48_24h=row.videos_previous_48_24h,
        participating_video_ids=list(row.participating_video_ids),
        participating_channel_ids=list(row.participating_channel_ids),
        participating_keyword_ids=list(row.participating_keyword_ids),
        reason_codes=list(row.reason_codes),
        human_reasons=list(row.human_reasons),
    )


def _channel_response(row: ChannelMomentum) -> AttentionChannelMomentumResponse:
    return AttentionChannelMomentumResponse(
        channel_id=row.channel_id,
        channel_title=row.channel_title,
        subscriber_count_latest=row.subscriber_count_latest,
        observed_video_count=row.observed_video_count,
        recent_video_count=row.recent_video_count,
        previous_video_count=row.previous_video_count,
        breakout_video_count=row.breakout_video_count,
        confirmed_72h_count=row.confirmed_72h_count,
        recent_median_vph=row.recent_median_vph,
        previous_median_vph=row.previous_median_vph,
        recent_median_vph_vs_previous=row.recent_median_vph_vs_previous,
        subscriber_growth_absolute=row.subscriber_growth_absolute,
        subscriber_growth_pct=row.subscriber_growth_pct,
        subscriber_growth_available=row.subscriber_growth_available,
        first_observed_at=row.first_observed_at,
        latest_observed_at=row.latest_observed_at,
        representative_video_ids=list(row.representative_video_ids),
        reason_codes=list(row.reason_codes),
        human_reasons=list(row.human_reasons),
        recent_window_days=row.recent_window_days,
        previous_window_days=row.previous_window_days,
        momentum_horizon_hours=row.momentum_horizon_hours,
        momentum_horizon_tolerance_hours=row.momentum_horizon_tolerance_hours,
        recent_eligible_count=row.recent_eligible_count,
        previous_eligible_count=row.previous_eligible_count,
        recent_measurable_count=row.recent_measurable_count,
        previous_measurable_count=row.previous_measurable_count,
        recent_improvement_count=row.recent_improvement_count,
        improvement_ratio_threshold=row.improvement_ratio_threshold,
        previous_baseline_zero=row.previous_baseline_zero,
        incompleteness_notes=list(row.incompleteness_notes),
    )


def _summary_response(result: AttentionEngineResult) -> AttentionSummaryResponse:
    s = result.summary
    return AttentionSummaryResponse(
        run_id=s.run_id,
        computed_at=s.computed_at,
        timezone_name=s.timezone_name,
        window_hours=s.window_hours,
        window_start=s.window_start,
        window_end=s.window_end,
        source=s.source,
        candidate_video_count=s.candidate_video_count,
        winner_count=s.winner_count,
        pattern_count=s.pattern_count,
        channel_momentum_count=s.channel_momentum_count,
        video_limit=s.video_limit,
        pattern_limit=s.pattern_limit,
        channel_limit=s.channel_limit,
        notes=s.notes,
    )


def _load_result(db: Session, *, live: bool) -> tuple[AttentionEngineResult | None, str]:
    if live:
        result = compute_attention_engine(db, config=AttentionEngineConfig(), source="live_compute")
        return result, "live_compute"
    result = load_attention_snapshot(db)
    if result is None:
        return None, "unavailable"
    return result, "snapshot"


@router.get("/summary", response_model=AttentionSummaryApiResponse)
def get_attention_summary(
    db: Session = Depends(get_db),
    live: bool = Query(False, description="Diagnostic recompute; default reads persisted snapshot"),
) -> AttentionSummaryApiResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionSummaryApiResponse(summary=None, data_source=source)
    return AttentionSummaryApiResponse(summary=_summary_response(result), data_source=source)


@router.get("/videos", response_model=AttentionVideoListResponse)
def list_attention_videos(
    db: Session = Depends(get_db),
    live: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AttentionVideoListResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionVideoListResponse(
            items=[],
            data_source=source,
            run_id=None,
            computed_at=None,
            limit=limit,
            offset=offset,
            total=0,
        )
    items = result.video_winners[offset : offset + limit]
    keyword_ids = list(dict.fromkeys(int(k) for row in items for k in row.keyword_ids))
    keyword_rows = hydrate_related_keywords(db, keyword_ids)
    keyword_by_id = {row["keyword_id"]: row["keyword"] for row in keyword_rows}
    return AttentionVideoListResponse(
        items=[_video_response(row, keyword_by_id=keyword_by_id) for row in items],
        data_source=source,
        run_id=result.summary.run_id,
        computed_at=result.summary.computed_at,
        limit=limit,
        offset=offset,
        total=len(result.video_winners),
    )


@router.get("/videos/{video_id}", response_model=AttentionVideoDetailResponse)
def get_attention_video(
    video_id: str,
    db: Session = Depends(get_db),
    live: bool = Query(False),
) -> AttentionVideoDetailResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionVideoDetailResponse(
            video=None,
            data_source=source,
            run_id=None,
            computed_at=None,
        )
    row = next((item for item in result.video_winners if item.video_id == video_id), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not in current winner snapshot")
    keyword_ids = list(dict.fromkeys(int(k) for k in row.keyword_ids))
    keyword_rows = hydrate_related_keywords(db, keyword_ids)
    keyword_by_id = {row["keyword_id"]: row["keyword"] for row in keyword_rows}
    return AttentionVideoDetailResponse(
        video=_video_response(row, keyword_by_id=keyword_by_id),
        data_source=source,
        run_id=result.summary.run_id,
        computed_at=result.summary.computed_at,
    )


@router.get("/patterns", response_model=AttentionPatternListResponse)
def list_attention_patterns(
    db: Session = Depends(get_db),
    live: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AttentionPatternListResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionPatternListResponse(
            items=[],
            data_source=source,
            run_id=None,
            computed_at=None,
            limit=limit,
            offset=offset,
            total=0,
        )
    items = result.patterns[offset : offset + limit]
    return AttentionPatternListResponse(
        items=[_pattern_response(row) for row in items],
        data_source=source,
        run_id=result.summary.run_id,
        computed_at=result.summary.computed_at,
        limit=limit,
        offset=offset,
        total=len(result.patterns),
    )


@router.get("/patterns/{pattern_id}", response_model=AttentionPatternDetailResponse)
def get_attention_pattern(
    pattern_id: str,
    db: Session = Depends(get_db),
    live: bool = Query(False),
) -> AttentionPatternDetailResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attention snapshot unavailable")
    for row in result.patterns:
        if row.pattern_key == pattern_id:
            videos = hydrate_pattern_member_videos(
                db,
                row,
                result.video_winners,
                computed_at=result.summary.computed_at,
            )
            return AttentionPatternDetailResponse(
                pattern=_pattern_response(row),
                data_source=source,
                run_id=result.summary.run_id,
                computed_at=result.summary.computed_at,
                videos=[AttentionPatternMemberVideoResponse(**item) for item in videos],
                related_keywords=[
                    AttentionRelatedKeywordResponse(**item)
                    for item in hydrate_related_keywords(db, row.participating_keyword_ids)
                ],
                channels=[
                    AttentionParticipatingChannelResponse(**item)
                    for item in hydrate_participating_channels(db, row.participating_channel_ids, videos)
                ],
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pattern not found in latest snapshot")


@router.get("/pattern-families", response_model=AttentionPatternFamilyListResponse)
def list_attention_pattern_families(
    db: Session = Depends(get_db),
    live: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AttentionPatternFamilyListResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionPatternFamilyListResponse(
            items=[],
            data_source=source,
            run_id=None,
            computed_at=None,
            limit=limit,
            offset=offset,
            total=0,
        )
    items = result.families[offset : offset + limit]
    winner_id_set, titles, channels = _family_presentation_context(db, result, list(items))
    return AttentionPatternFamilyListResponse(
        items=[
            _family_response(
                row,
                present_opportunity_family(
                    row,
                    feed_winner_id_set=winner_id_set,
                    video_titles=titles,
                    video_channels=channels,
                ),
            )
            for row in items
        ],
        data_source=source,
        run_id=result.summary.run_id,
        computed_at=result.summary.computed_at,
        limit=limit,
        offset=offset,
        total=len(result.families),
    )


@router.get("/pattern-families/{family_key}", response_model=AttentionPatternFamilyDetailResponse)
def get_attention_pattern_family(
    family_key: str,
    db: Session = Depends(get_db),
    live: bool = Query(False),
) -> AttentionPatternFamilyDetailResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attention snapshot unavailable")
    for row in result.families:
        if row.family_key == family_key:
            videos = hydrate_videos_by_ids(
                db,
                list(row.video_ids),
                result.video_winners,
                computed_at=result.summary.computed_at,
                extra_channel_ids=list(row.channel_ids),
            )
            patterns_by_key = {item.pattern_key: item for item in result.patterns}
            members = [patterns_by_key[key] for key in row.member_pattern_keys if key in patterns_by_key]
            winner_id_set, titles, channel_map = _family_presentation_context(db, result, [row])
            presentation = present_opportunity_family(
                row,
                feed_winner_id_set=winner_id_set,
                video_titles=titles,
                video_channels=channel_map,
            )
            return AttentionPatternFamilyDetailResponse(
                family=_family_response(row, presentation),
                data_source=source,
                run_id=result.summary.run_id,
                computed_at=result.summary.computed_at,
                videos=[AttentionPatternMemberVideoResponse(**item) for item in videos],
                related_keywords=[
                    AttentionRelatedKeywordResponse(**item)
                    for item in hydrate_related_keywords(db, row.keyword_ids)
                ],
                channels=[
                    AttentionParticipatingChannelResponse(**item)
                    for item in hydrate_participating_channels(db, row.channel_ids, videos)
                ],
                member_patterns=[_pattern_response(item) for item in members],
            )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pattern family not found in latest snapshot")


@router.get("/channels", response_model=AttentionChannelListResponse)
def list_attention_channels(
    db: Session = Depends(get_db),
    live: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AttentionChannelListResponse:
    result, source = _load_result(db, live=live)
    if result is None:
        return AttentionChannelListResponse(
            items=[],
            data_source=source,
            run_id=None,
            computed_at=None,
            limit=limit,
            offset=offset,
            total=0,
        )
    items = result.channels[offset : offset + limit]
    return AttentionChannelListResponse(
        items=[_channel_response(row) for row in items],
        data_source=source,
        run_id=result.summary.run_id,
        computed_at=result.summary.computed_at,
        limit=limit,
        offset=offset,
        total=len(result.channels),
    )
