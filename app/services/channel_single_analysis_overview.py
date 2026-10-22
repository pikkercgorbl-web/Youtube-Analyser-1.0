"""Descriptive overview helpers for single-channel analysis (no scoring)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.schemas import ChannelSingleAnalysisPublication


@dataclass(frozen=True, slots=True)
class ViewsRankResult:
    rank: int | None
    group_size: int
    regular_total: int
    focus_in_group: bool


def confirmed_regular_publications(
    publications: list[ChannelSingleAnalysisPublication],
) -> list[ChannelSingleAnalysisPublication]:
    return [p for p in publications if p.kind == "regular" and p.published_at is not None]


def regular_with_known_views(
    publications: list[ChannelSingleAnalysisPublication],
) -> list[ChannelSingleAnalysisPublication]:
    return [p for p in confirmed_regular_publications(publications) if p.views_count > 0]


def compute_views_rank(
    *,
    focus_video_id: str,
    publications: list[ChannelSingleAnalysisPublication],
) -> ViewsRankResult:
    regular_all = confirmed_regular_publications(publications)
    group = regular_with_known_views(publications)
    group_size = len(group)
    regular_total = len(regular_all)

    if not focus_video_id or group_size == 0:
        return ViewsRankResult(
            rank=None,
            group_size=group_size,
            regular_total=regular_total,
            focus_in_group=False,
        )

    focus_in_group = any(p.video_id == focus_video_id for p in group)
    if not focus_in_group:
        return ViewsRankResult(
            rank=None,
            group_size=group_size,
            regular_total=regular_total,
            focus_in_group=False,
        )

    sorted_by_views = sorted(group, key=lambda p: (-p.views_count, p.video_id))
    rank = 1
    prev_views: int | None = None
    focus_rank: int | None = None
    for index, pub in enumerate(sorted_by_views, start=1):
        if prev_views is None or pub.views_count < prev_views:
            rank = index
            prev_views = pub.views_count
        if pub.video_id == focus_video_id:
            focus_rank = rank
            break

    return ViewsRankResult(
        rank=focus_rank,
        group_size=group_size,
        regular_total=regular_total,
        focus_in_group=True,
    )


def sample_period_bounds(
    publications: list[ChannelSingleAnalysisPublication],
) -> tuple[datetime | None, datetime | None]:
    dates = [p.published_at for p in publications if p.published_at is not None]
    if not dates:
        return None, None
    return min(dates), max(dates)
