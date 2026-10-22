"""Peer comparison for single-channel analysis v1 (live views, age window heuristic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from app.models.orm import VideoFormat
from app.services.metrics import ensure_utc, utc_now
from app.services.video_format_from_api import infer_video_format_from_details

FOCUS_MIN_AGE_HOURS = 48.0
PEER_AGE_RATIO_LOW = 0.75
PEER_AGE_RATIO_HIGH = 1.25
MIN_PEER_COUNT = 5

ComparisonStatus = Literal[
    "ok",
    "focus_too_young",
    "insufficient_peers",
    "median_zero",
    "insufficient_data",
    "focus_channel_mismatch",
    "no_focus",
]


class PublicationKind(str, Enum):
    REGULAR = "regular"
    SHORT = "short"
    LIVE = "live"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PublicationForCompare:
    video_id: str
    channel_id: str
    views_count: int
    published_at: datetime | None
    content_format: VideoFormat | None


@dataclass(frozen=True, slots=True)
class AgePeerMatch:
    video_id: str
    views_count: int
    age_hours: float


@dataclass(frozen=True, slots=True)
class FocusComparisonResult:
    status: ComparisonStatus
    multiplier: float | None
    peer_count: int
    median_views: int | None
    focus_views: int | None
    focus_age_hours: float | None
    peer_age_min_hours: float | None
    peer_age_max_hours: float | None
    searched_age_low_hours: float | None
    searched_age_high_hours: float | None
    age_peer_matches: tuple[AgePeerMatch, ...]
    message: str
    disclaimer: str


def age_hours_since_publish(published_at: datetime, *, now: datetime | None = None) -> float:
    reference = ensure_utc(now or utc_now())
    published = ensure_utc(published_at)
    return max((reference - published).total_seconds() / 3600.0, 0.0)


def publication_kind_from_format(fmt: VideoFormat | None) -> PublicationKind:
    if fmt is None or fmt == VideoFormat.UNKNOWN:
        return PublicationKind.UNKNOWN
    if fmt == VideoFormat.SHORT:
        return PublicationKind.SHORT
    if fmt == VideoFormat.LIVE:
        return PublicationKind.LIVE
    if fmt in (VideoFormat.MEDIUM, VideoFormat.LONG):
        return PublicationKind.REGULAR
    return PublicationKind.UNKNOWN


def is_confirmed_regular(fmt: VideoFormat | None) -> bool:
    return publication_kind_from_format(fmt) == PublicationKind.REGULAR


def classify_from_api_details(details) -> VideoFormat | None:
    return infer_video_format_from_details(details)


def peer_age_in_window(peer_age_hours: float, focus_age_hours: float) -> bool:
    if focus_age_hours <= 0:
        return False
    low = focus_age_hours * PEER_AGE_RATIO_LOW
    high = focus_age_hours * PEER_AGE_RATIO_HIGH
    return low <= peer_age_hours <= high


def searched_age_window_hours(focus_age_hours: float) -> tuple[float, float]:
    return focus_age_hours * PEER_AGE_RATIO_LOW, focus_age_hours * PEER_AGE_RATIO_HIGH


def collect_age_peers(
    *,
    channel_id: str,
    focus: PublicationForCompare,
    catalog: list[PublicationForCompare],
    now: datetime | None = None,
) -> tuple[AgePeerMatch, ...]:
    focus_age = age_hours_since_publish(focus.published_at, now=now)
    matches: list[AgePeerMatch] = []
    for item in catalog:
        if item.video_id == focus.video_id:
            continue
        if (item.channel_id or "").strip() != channel_id.strip():
            continue
        if not is_confirmed_regular(item.content_format):
            continue
        if item.published_at is None or item.views_count <= 0:
            continue
        item_age = age_hours_since_publish(item.published_at, now=now)
        if not peer_age_in_window(item_age, focus_age):
            continue
        matches.append(
            AgePeerMatch(
                video_id=item.video_id,
                views_count=item.views_count,
                age_hours=round(item_age, 1),
            ),
        )
    return tuple(matches)


def compute_focus_comparison(
    *,
    channel_id: str,
    focus: PublicationForCompare | None,
    catalog: list[PublicationForCompare],
    now: datetime | None = None,
) -> FocusComparisonResult:
    disclaimer = (
        "Ориентировочное сравнение текущих просмотров. "
        "Это не замеры на одинаковом возрасте видео."
    )
    if focus is None:
        return FocusComparisonResult(
            status="no_focus",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=None,
            focus_age_hours=None,
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=None,
            searched_age_high_hours=None,
            age_peer_matches=(),
            message="Видео для сравнения не выбрано.",
            disclaimer=disclaimer,
        )

    if (focus.channel_id or "").strip() != channel_id.strip():
        return FocusComparisonResult(
            status="focus_channel_mismatch",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=focus.views_count if focus.views_count > 0 else None,
            focus_age_hours=None,
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=None,
            searched_age_high_hours=None,
            age_peer_matches=(),
            message="Выбранное видео не принадлежит этому каналу.",
            disclaimer=disclaimer,
        )

    if focus.published_at is None or not is_confirmed_regular(focus.content_format):
        return FocusComparisonResult(
            status="insufficient_data",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=focus.views_count if focus.views_count > 0 else None,
            focus_age_hours=None,
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=None,
            searched_age_high_hours=None,
            age_peer_matches=(),
            message="Недостаточно данных для сравнения выбранного видео.",
            disclaimer=disclaimer,
        )

    if focus.views_count <= 0:
        return FocusComparisonResult(
            status="insufficient_data",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=None,
            focus_age_hours=None,
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=None,
            searched_age_high_hours=None,
            age_peer_matches=(),
            message="Недостаточно данных: просмотры выбранного видео неизвестны.",
            disclaimer=disclaimer,
        )

    focus_age = age_hours_since_publish(focus.published_at, now=now)
    age_low, age_high = searched_age_window_hours(focus_age)
    if focus_age < FOCUS_MIN_AGE_HOURS:
        return FocusComparisonResult(
            status="focus_too_young",
            multiplier=None,
            peer_count=0,
            median_views=None,
            focus_views=focus.views_count,
            focus_age_hours=round(focus_age, 1),
            peer_age_min_hours=None,
            peer_age_max_hours=None,
            searched_age_low_hours=round(age_low, 1),
            searched_age_high_hours=round(age_high, 1),
            age_peer_matches=(),
            message="Видео младше 48 часов — сравнение с каналом пока не рассчитывается.",
            disclaimer=disclaimer,
        )

    age_matches = collect_age_peers(
        channel_id=channel_id,
        focus=focus,
        catalog=catalog,
        now=now,
    )
    peer_views = [m.views_count for m in age_matches]
    peer_ages = [m.age_hours for m in age_matches]
    peer_count = len(peer_views)
    if peer_count < MIN_PEER_COUNT:
        return FocusComparisonResult(
            status="insufficient_peers",
            multiplier=None,
            peer_count=peer_count,
            median_views=None,
            focus_views=focus.views_count,
            focus_age_hours=round(focus_age, 1),
            peer_age_min_hours=round(min(peer_ages), 1) if peer_ages else None,
            peer_age_max_hours=round(max(peer_ages), 1) if peer_ages else None,
            searched_age_low_hours=round(age_low, 1),
            searched_age_high_hours=round(age_high, 1),
            age_peer_matches=age_matches,
            message=f"Недостаточно роликов близкого возраста: найдено {peer_count}, нужно {MIN_PEER_COUNT}.",
            disclaimer=disclaimer,
        )

    sorted_views = sorted(peer_views)
    mid = len(sorted_views) // 2
    if len(sorted_views) % 2 == 1:
        median_views = sorted_views[mid]
    else:
        median_views = round((sorted_views[mid - 1] + sorted_views[mid]) / 2)

    if median_views <= 0:
        return FocusComparisonResult(
            status="median_zero",
            multiplier=None,
            peer_count=peer_count,
            median_views=0,
            focus_views=focus.views_count,
            focus_age_hours=round(focus_age, 1),
            peer_age_min_hours=round(min(peer_ages), 1),
            peer_age_max_hours=round(max(peer_ages), 1),
            searched_age_low_hours=round(age_low, 1),
            searched_age_high_hours=round(age_high, 1),
            age_peer_matches=age_matches,
            message="Медиана просмотров группы равна нулю — множитель не рассчитывается.",
            disclaimer=disclaimer,
        )

    multiplier = round(focus.views_count / median_views, 2)
    return FocusComparisonResult(
        status="ok",
        multiplier=multiplier,
        peer_count=peer_count,
        median_views=median_views,
        focus_views=focus.views_count,
        focus_age_hours=round(focus_age, 1),
        peer_age_min_hours=round(min(peer_ages), 1),
        peer_age_max_hours=round(max(peer_ages), 1),
        searched_age_low_hours=round(age_low, 1),
        searched_age_high_hours=round(age_high, 1),
        age_peer_matches=age_matches,
        message=f"В {multiplier:g} раза относительно медианы {peer_count} роликов близкого возраста.",
        disclaimer=disclaimer,
    )
