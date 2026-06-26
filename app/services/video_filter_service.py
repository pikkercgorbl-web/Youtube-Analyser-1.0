"""Local filtering for enriched InnerTube search results."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.integrations.youtube.client import EnrichedVideoModel

VideoType = Literal["short", "stream", "regular"]
SortOption = Literal["views", "date", "virality", "relevance"]

# Duration buckets in seconds: [low, high). "long" is open-ended.
_DURATION_BUCKETS: dict[str, tuple[int, float]] = {
    "short": (0, 180),
    "medium": (180, 1200),
    "long": (1200, float("inf")),
}

_PUBLISHED_WINDOWS: dict[str, timedelta] = {
    "hour": timedelta(hours=1),
    "24h": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}

# CJK, Japanese kana, Korean hangul, Devanagari (Hindi/Sanskrit script).
_HIEROGLYPH_PATTERN = re.compile(
    r"["
    r"\u0900-\u097f"  # Devanagari
    r"\u3040-\u309f"  # Hiragana
    r"\u30a0-\u30ff"  # Katakana
    r"\u3400-\u4dbf"  # CJK Extension A
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\uac00-\ud7af"  # Hangul syllables
    r"\u1100-\u11ff"  # Hangul Jamo
    r"]",
)

_STREAM_MARKERS = (
    "streamed",
    "streaming",
    "was live",
    "live now",
    "premiere",
    "прямой эфир",
    "трансляция",
)

_RELATIVE_DATE_PATTERN = re.compile(
    r"(?:(?:streamed|premiered|uploaded)\s+)?"
    r"(\d+)\s+"
    r"(second|minute|hour|day|week|month|year|"
    r"seconds|minutes|hours|days|weeks|months|years|"
    r"секунд|секунды|минут|минуты|час|часа|часов|"
    r"день|дня|дней|недел|недели|недель|"
    r"месяц|месяца|месяцев|год|года|лет)"
    r"(?:\s+ago|\s+назад)?",
    re.IGNORECASE,
)

_A_RELATIVE_DATE_PATTERN = re.compile(
    r"(?:an?|one)\s+"
    r"(second|minute|hour|day|week|month|year|"
    r"секунд|минут|час|день|недел|месяц|год)"
    r"(?:\s+ago|\s+назад)?",
    re.IGNORECASE,
)


class VideoFilterService:
    """
    Apply local filters to enriched video search results.

    Supported ``filters_config`` keys:

    - ``hide_shorts``, ``hide_regular``, ``hide_streams`` (bool)
    - ``published_within`` (str): ``hour`` | ``24h`` | ``week`` | ``month`` | ``year``
    - ``duration`` (str): ``short`` (<3m) | ``medium`` (3-20m) | ``long`` (>20m)
    - ``hide_hieroglyphs`` (bool)
    - ``virality_only_above_one`` (bool): keep only ``virality_coefficient > 1.0``
    - ``virality_min``, ``virality_max`` (float)
    - ``views_min``, ``views_max`` (int): video views
    - ``subscribers_min``, ``subscribers_max`` (int): channel subscribers
    - ``channel_views_min``, ``channel_views_max`` (int): total channel views
    - ``channel_videos_min``, ``channel_videos_max`` (int): total videos on channel
    - ``channel_age_min``, ``channel_age_max`` (int): channel age in days

    ``sort_results`` supports: ``views``, ``date``, ``virality``, ``relevance``.
    """

    def apply_filters(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        """Sequentially filter videos according to ``filters_config``."""
        filtered = list(videos)

        filtered = self._filter_by_video_type(filtered, filters_config)
        filtered = self._filter_by_duration(filtered, filters_config)
        filtered = self._filter_by_published_within(filtered, filters_config)
        filtered = self._filter_hieroglyphs(filtered, filters_config)
        filtered = self._filter_virality_toggle(filtered, filters_config)
        filtered = self._filter_ranges(filtered, filters_config)

        return filtered

    def _filter_by_video_type(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        hide_shorts = bool(filters_config.get("hide_shorts"))
        hide_regular = bool(filters_config.get("hide_regular"))
        hide_streams = bool(filters_config.get("hide_streams"))

        if not (hide_shorts or hide_regular or hide_streams):
            return videos

        result: list[EnrichedVideoModel] = []
        for item in videos:
            video_type = _detect_video_type(item)
            if hide_shorts and video_type == "short":
                continue
            if hide_streams and video_type == "stream":
                continue
            if hide_regular and video_type == "regular":
                continue
            result.append(item)
        return result

    def _filter_by_duration(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        bucket = filters_config.get("duration")
        if bucket not in _DURATION_BUCKETS:
            return videos

        low, high = _DURATION_BUCKETS[bucket]
        result: list[EnrichedVideoModel] = []
        for item in videos:
            seconds = parse_duration_text(item.video.duration_text)
            if seconds <= 0:
                # Unknown duration: keep to avoid dropping valid results.
                result.append(item)
                continue
            if seconds < low or seconds >= high:
                continue
            result.append(item)
        return result

    def _filter_by_published_within(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        window = filters_config.get("published_within")
        if window not in _PUBLISHED_WINDOWS:
            return videos

        cutoff = datetime.now(timezone.utc) - _PUBLISHED_WINDOWS[window]
        return [
            item
            for item in videos
            if parse_relative_published_date(item.video.published_text) >= cutoff
        ]

    def _filter_hieroglyphs(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        if not filters_config.get("hide_hieroglyphs"):
            return videos
        return [item for item in videos if not _contains_hieroglyphs(item.video.title)]

    def _filter_virality_toggle(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        if not filters_config.get("virality_only_above_one"):
            return videos
        return [item for item in videos if item.virality_coefficient > 1.0]

    def _filter_ranges(
        self,
        videos: list[EnrichedVideoModel],
        filters_config: dict,
    ) -> list[EnrichedVideoModel]:
        result: list[EnrichedVideoModel] = []
        for item in videos:
            if not _matches_range(
                item.virality_coefficient,
                filters_config,
                "virality_min",
                "virality_max",
            ):
                continue
            if not _matches_range(
                item.video.views_count,
                filters_config,
                "views_min",
                "views_max",
            ):
                continue
            if not _matches_range(
                item.channel.subscribers_count,
                filters_config,
                "subscribers_min",
                "subscribers_max",
            ):
                continue
            if not _matches_range(
                item.channel.total_views,
                filters_config,
                "channel_views_min",
                "channel_views_max",
            ):
                continue
            if not _matches_range(
                item.channel.total_videos,
                filters_config,
                "channel_videos_min",
                "channel_videos_max",
            ):
                continue
            if not _matches_channel_age(item.channel.channel_age_days, filters_config):
                continue
            result.append(item)
        return result

    def sort_results(
        self,
        videos: list[EnrichedVideoModel],
        sort_by: str,
    ) -> list[EnrichedVideoModel]:
        """Sort enriched videos by views, upload date, virality, or YouTube relevance."""
        normalized = sort_by.strip().lower()

        if normalized == "relevance":
            return list(videos)
        if normalized == "views":
            return sorted(
                videos,
                key=lambda item: item.video.views_count,
                reverse=True,
            )
        if normalized == "virality":
            return sorted(
                videos,
                key=lambda item: item.virality_coefficient,
                reverse=True,
            )
        if normalized == "date":
            return sorted(
                videos,
                key=lambda item: parse_relative_published_date(item.video.published_text),
                reverse=True,
            )

        msg = f"Unsupported sort option: {sort_by}"
        raise ValueError(msg)


def _detect_video_type(item: EnrichedVideoModel) -> VideoType:
    if _is_stream(item):
        return "stream"
    if _is_short(item):
        return "short"
    return "regular"


def _is_stream(item: EnrichedVideoModel) -> bool:
    published = item.video.published_text.lower()
    title = item.video.title.lower()
    if any(marker in published for marker in _STREAM_MARKERS):
        return True
    return " live" in title or title.endswith(" live")


def _is_short(item: EnrichedVideoModel) -> bool:
    if getattr(item.video, "is_short", False):
        return True

    duration_seconds = parse_duration_text(item.video.duration_text)
    if 0 < duration_seconds < 60:
        return True

    title_lower = item.video.title.lower()
    if "#shorts" in title_lower or "#short" in title_lower:
        return True
    if "/shorts/" in title_lower:
        return True
    return False


def _contains_hieroglyphs(title: str) -> bool:
    return _HIEROGLYPH_PATTERN.search(title) is not None


def parse_duration_text(value: str) -> int:
    """Parse InnerTube duration strings like ``12:00:00``, ``6:14:07`` or ``0:45``."""
    text = value.strip()
    if not text:
        return 0

    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (int(part) for part in parts)
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes, seconds = (int(part) for part in parts)
            return minutes * 60 + seconds
        if len(parts) == 1:
            return int(parts[0])
    except ValueError:
        return 0
    return 0


def parse_relative_published_date(text: str) -> datetime:
    """
    Convert relative publish labels to an approximate UTC datetime.

    Examples: ``2 days ago``, ``1 month ago``, ``Streamed 4 weeks ago``,
    ``3 дня назад``.
    """
    normalized = text.strip().lower()
    if not normalized:
        return datetime.min.replace(tzinfo=timezone.utc)

    if normalized in {"just now", "moments ago", "только что"}:
        return datetime.now(timezone.utc)

    a_match = _A_RELATIVE_DATE_PATTERN.search(normalized)
    if a_match:
        return datetime.now(timezone.utc) - _relative_delta(1, a_match.group(1))

    match = _RELATIVE_DATE_PATTERN.search(normalized)
    if not match:
        return datetime.min.replace(tzinfo=timezone.utc)

    amount = int(match.group(1))
    unit = match.group(2)
    return datetime.now(timezone.utc) - _relative_delta(amount, unit)


def _relative_delta(amount: int, unit: str) -> timedelta:
    normalized_unit = unit.lower().rstrip(".")

    if normalized_unit.startswith(("second", "секунд")):
        return timedelta(seconds=amount)
    if normalized_unit.startswith(("minute", "минут")):
        return timedelta(minutes=amount)
    if normalized_unit.startswith(("hour", "час")):
        return timedelta(hours=amount)
    if normalized_unit.startswith(("day", "день", "дня", "дней")):
        return timedelta(days=amount)
    if normalized_unit.startswith(("week", "недел")):
        return timedelta(weeks=amount)
    if normalized_unit.startswith(("month", "месяц")):
        return timedelta(days=amount * 30)
    if normalized_unit.startswith(("year", "год", "года", "лет")):
        return timedelta(days=amount * 365)

    return timedelta()


def _matches_channel_age(
    channel_age_days: int | None,
    config: dict,
) -> bool:
    min_value = config.get("channel_age_min")
    max_value = config.get("channel_age_max")
    if min_value is None and max_value is None:
        return True
    if channel_age_days is None:
        return False
    return _matches_range(channel_age_days, config, "channel_age_min", "channel_age_max")


def _matches_range(
    value: float | int,
    config: dict,
    min_key: str,
    max_key: str,
) -> bool:
    min_value = config.get(min_key)
    max_value = config.get(max_key)
    if min_value is None and max_value is None:
        return True
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True
