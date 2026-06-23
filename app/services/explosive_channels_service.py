"""Detect and persist young high-virality channels during video analysis (FR-5)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.youtube.client import (
    ChannelAnalysisModel,
    EnrichedVideoModel,
    RADAR_SUBSCRIBER_FETCH_DELAY_SECONDS,
    VideoSearchModel,
    calc_virality_coefficient,
    fetch_channel_subscribers_from_homepage,
)
from app.models.db import SessionLocal
from app.models.orm import ExplosiveChannel, ExplosiveChannelSettings
from app.services.metrics import utc_now

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 180
DEFAULT_MIN_VIEWS = 50_000
DEFAULT_MIN_VIRAL_COEFF = 3.0
DEFAULT_UPLOAD_PERIOD = "all"
VALID_UPLOAD_PERIODS = frozenset({"all", "month", "3_months", "6_months", "year"})
UPLOAD_PERIOD_LABELS: dict[str, str] = {
    "all": "За всё время",
    "month": "До 1 месяца",
    "3_months": "До 3 месяцев",
    "6_months": "До 6 месяцев",
    "year": "До 1 года",
}
SETTINGS_ROW_ID = 1
MAX_REJECTION_LOGS = 5
DEFAULT_CHANNEL_AGE_DAYS = 0
indian_scripts_pattern = re.compile(r"[\u0900-\u0D7F]")
_MONTHS_AGO_PATTERN = re.compile(r"(\d+)\s+months?\s*(?:ago|назад)?", re.IGNORECASE)
_YEARS_AGO_PATTERN = re.compile(r"(\d+)\s+years?\s*(?:ago|назад)?", re.IGNORECASE)
_MULTI_YEARS_PATTERN = re.compile(r"\b([2-9]|\d{2,})\s+years?\b", re.IGNORECASE)
_YEAR_WORD_PATTERN = re.compile(r"\b(years?|год(?:а|у)?|лет)\b", re.IGNORECASE)
_MONTH_WORD_PATTERN = re.compile(r"\b(months?|месяц(?:а|ев)?)\b", re.IGNORECASE)
_RU_MONTHS_AGO_PATTERN = re.compile(r"(\d+)\s+месяц(?:а|ев)?\s*(?:назад)?", re.IGNORECASE)
_RU_YEARS_AGO_PATTERN = re.compile(r"(\d+)\s+(?:год(?:а|у)?|лет)\s*(?:назад)?", re.IGNORECASE)

PLACEHOLDER_CHANNEL_ID_PREFIXES = ("UCtest",)
PLACEHOLDER_CHANNEL_NAMES = frozenset({"a", "b", "test"})


def channel_metrics_usable(*, subscribers_count: int) -> bool:
    """Require subscriber count from search card before radar virality math."""
    return subscribers_count > 0


def explain_missing_channel_metrics(
    *,
    channel_name: str,
    subscribers_count: int,
) -> str | None:
    label = format_channel_label(channel_name)
    if subscribers_count <= 0:
        return f"Канал {label}: подписчики не определены ({subscribers_count})"
    return None


def format_channel_label(channel_name: str) -> str:
    label = channel_name.strip() or "Unknown"
    if not label.startswith("@"):
        label = f"@{label}"
    return label


def is_placeholder_channel(channel_id: str, channel_name: str) -> bool:
    normalized_id = channel_id.strip()
    normalized_name = channel_name.strip().lower()
    if any(normalized_id.startswith(prefix) for prefix in PLACEHOLDER_CHANNEL_ID_PREFIXES):
        return True
    return normalized_name in PLACEHOLDER_CHANNEL_NAMES


def xray_log(message: str) -> None:
    print(message, flush=True)


def passes_upload_date_text_filter(upload_date_text: str, upload_period: str) -> bool:
    """
    Filter InnerTube relative upload labels like ``5 days ago`` / ``4 months ago``.

    Returns True when the video is fresh enough for the selected radar period.
    """
    if upload_period == "all":
        return True

    text = upload_date_text.strip().lower()
    if not text:
        return True

    if upload_period in {"month", "3_months", "6_months"}:
        if _YEAR_WORD_PATTERN.search(text):
            return False

    if upload_period == "year":
        years_match = _YEARS_AGO_PATTERN.search(text) or _RU_YEARS_AGO_PATTERN.search(text)
        if years_match and int(years_match.group(1)) >= 2:
            return False
        if _MULTI_YEARS_PATTERN.search(text):
            return False
        ru_multi_years = re.search(r"\b([2-9]|\d{2,})\s+(?:год(?:а|у)?|лет)\b", text)
        return ru_multi_years is None

    if upload_period == "month":
        return (
            _MONTH_WORD_PATTERN.search(text) is None
            and _YEAR_WORD_PATTERN.search(text) is None
        )

    if upload_period in {"3_months", "6_months"}:
        limit = 3 if upload_period == "3_months" else 6
        for pattern in (_MONTHS_AGO_PATTERN, _RU_MONTHS_AGO_PATTERN):
            match = pattern.search(text)
            if match and int(match.group(1)) > limit:
                return False
        return True

    return True


def reject_upload_date_text(upload_date_text: str, upload_period: str) -> bool:
    """Return True when the video should be rejected for being too old."""
    return not passes_upload_date_text_filter(upload_date_text, upload_period)


@dataclass(frozen=True, slots=True)
class ExplosiveChannelThresholds:
    min_views: int = DEFAULT_MIN_VIEWS
    min_viral_coeff: float = DEFAULT_MIN_VIRAL_COEFF


@dataclass(frozen=True, slots=True)
class RadarChannelHit:
    channel_name: str
    viral_coefficient: float


class ExplosiveChannelsService:
    """Evaluate channels against FR-5 thresholds and upsert explosive watchlist rows."""

    @staticmethod
    def qualifies(
        thresholds: ExplosiveChannelThresholds,
        *,
        video_views: int,
        viral_coefficient: float,
    ) -> bool:
        if video_views < thresholds.min_views:
            return False
        return viral_coefficient >= thresholds.min_viral_coeff

    @staticmethod
    def explain_rejection(
        thresholds: ExplosiveChannelThresholds,
        *,
        channel_name: str,
        video_views: int,
        viral_coefficient: float,
        subscribers: int,
    ) -> str | None:
        label = format_channel_label(channel_name)

        missing_metrics = explain_missing_channel_metrics(
            channel_name=channel_name,
            subscribers_count=subscribers,
        )
        if missing_metrics:
            return missing_metrics

        if video_views < thresholds.min_views:
            return (
                f"Канал {label}: просмотры {video_views:,} "
                f"< {thresholds.min_views:,}"
            )

        if viral_coefficient < thresholds.min_viral_coeff:
            return (
                f"Канал {label}: виральность {viral_coefficient:.1f}× "
                f"< {thresholds.min_viral_coeff:.1f}× "
                f"(просмотры {video_views:,}, подписчики {subscribers:,})"
            )

        return None

    def purge_placeholder_channels(self, db: Session) -> int:
        records = list(db.scalars(select(ExplosiveChannel)).all())
        removed = 0
        for record in records:
            if not is_placeholder_channel(record.channel_id, record.channel_name):
                continue
            db.delete(record)
            removed += 1
        if removed:
            db.commit()
        return removed

    def clear_all_channels(self, db: Session) -> int:
        """Delete every row from explosive_channels."""
        records = list(db.scalars(select(ExplosiveChannel)).all())
        removed = len(records)
        for record in records:
            db.delete(record)
        if removed:
            db.commit()
        return removed

    def get_thresholds(self, db: Session) -> ExplosiveChannelThresholds:
        settings = self._get_or_create_settings(db)
        return ExplosiveChannelThresholds(
            min_views=settings.min_views,
            min_viral_coeff=settings.min_viral_coeff,
        )

    def get_upload_period(self, db: Session) -> str:
        settings = self._get_or_create_settings(db)
        period = settings.upload_period or DEFAULT_UPLOAD_PERIOD
        if period not in VALID_UPLOAD_PERIODS:
            return DEFAULT_UPLOAD_PERIOD
        return period

    def update_upload_period(self, db: Session, upload_period: str) -> str:
        if upload_period not in VALID_UPLOAD_PERIODS:
            msg = f"Unsupported upload_period: {upload_period!r}"
            raise ValueError(msg)

        settings = self._get_or_create_settings(db)
        settings.upload_period = upload_period
        settings.updated_at = utc_now()
        db.commit()
        db.refresh(settings)
        return settings.upload_period

    @staticmethod
    def filter_enriched_by_upload_period(
        items: list[EnrichedVideoModel],
        upload_period: str,
    ) -> list[EnrichedVideoModel]:
        """Keep only videos whose relative upload label fits the radar period."""
        if upload_period == "all":
            return items
        return [
            item
            for item in items
            if passes_upload_date_text_filter(item.video.published_text, upload_period)
        ]

    def update_thresholds(
        self,
        db: Session,
        *,
        min_views: int,
        min_viral_coeff: float,
    ) -> ExplosiveChannelThresholds:
        settings = self._get_or_create_settings(db)
        settings.min_views = min_views
        settings.min_viral_coeff = min_viral_coeff
        settings.updated_at = utc_now()
        db.commit()
        db.refresh(settings)
        return ExplosiveChannelThresholds(
            min_views=settings.min_views,
            min_viral_coeff=settings.min_viral_coeff,
        )

    def list_filtered(
        self,
        db: Session,
        *,
        min_views: int = DEFAULT_MIN_VIEWS,
        min_viral_coeff: float = DEFAULT_MIN_VIRAL_COEFF,
    ) -> list[ExplosiveChannel]:
        self.update_thresholds(
            db,
            min_views=min_views,
            min_viral_coeff=min_viral_coeff,
        )

        stmt = (
            select(ExplosiveChannel)
            .where(
                ExplosiveChannel.representative_video_views >= min_views,
                ExplosiveChannel.viral_coefficient >= min_viral_coeff,
            )
            .order_by(
                ExplosiveChannel.viral_coefficient.desc(),
                ExplosiveChannel.updated_at.desc(),
            )
        )
        records = list(db.scalars(stmt).all())
        return [
            record
            for record in records
            if not is_placeholder_channel(record.channel_id, record.channel_name)
        ]

    def process_enriched_videos(
        self,
        db: Session,
        items: list[EnrichedVideoModel],
        *,
        log_rejections: bool = False,
        filter_title_language: bool = False,
        upload_period: str | None = None,
    ) -> list[RadarChannelHit]:
        thresholds = self.get_thresholds(db)
        effective_upload_period = upload_period or self.get_upload_period(db)
        hits: list[RadarChannelHit] = []
        rejection_logs = 0

        for item in items:
            video = item.video
            channel = item.channel
            channel_name = video.channel_title or "Unknown"
            upload_date_text = video.published_text.strip() or "—"

            if effective_upload_period != "all" and reject_upload_date_text(
                upload_date_text,
                effective_upload_period,
            ):
                xray_log(
                    f"❌ [ОТКАЗ] Видео слишком старое ({upload_date_text}): {video.title}",
                )
                continue

            if not video.channel_id.strip():
                if log_rejections and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log("❌ [ОТКАЗ] Видео без channel_id — пропуск")
                    rejection_logs += 1
                continue

            if filter_title_language:
                if indian_scripts_pattern.search(video.title) or indian_scripts_pattern.search(
                    channel_name,
                ):
                    xray_log(f"❌ [ОТКАЗ] Индийские символы в названии: {video.title}")
                    continue

            raw_age = DEFAULT_CHANNEL_AGE_DAYS
            subscribers = max(channel.subscribers_count, 0)
            if not channel_metrics_usable(subscribers_count=subscribers):
                rejection = explain_missing_channel_metrics(
                    channel_name=channel_name,
                    subscribers_count=subscribers,
                )
                if log_rejections and rejection and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log(f"❌ [ОТКАЗ] {rejection}")
                    rejection_logs += 1
                continue

            video_views = max(video.views_count, 0)
            viral_coefficient = calc_virality_coefficient(video_views, subscribers)

            rejection = self.explain_rejection(
                thresholds,
                channel_name=channel_name,
                video_views=video_views,
                viral_coefficient=viral_coefficient,
                subscribers=subscribers,
            )
            if rejection:
                if log_rejections and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log(f"❌ [ОТКАЗ] {rejection}")
                    rejection_logs += 1
                continue

            hit = self._register_channel_video(
                db,
                thresholds,
                channel_id=video.channel_id,
                channel_name=channel_name,
                avatar_url=channel.channel_avatar_url or video.channel_avatar_url,
                subscribers=subscribers,
                channel_age_days=raw_age,
                total_views=max(channel.total_views, 0),
                viral_coefficient=viral_coefficient,
                representative_video_title=video.title,
                representative_video_thumbnail=video.thumbnail_url,
                representative_video_views=video_views,
                representative_video_id=video.video_id,
                skip_qualify_check=True,
            )
            if hit is not None:
                hits.append(hit)

        db.commit()
        return hits

    async def process_radar_videos(
        self,
        db: Session,
        videos: list[VideoSearchModel],
        *,
        log_rejections: bool = False,
        filter_title_language: bool = False,
        upload_period: str | None = None,
        subscriber_fetch_delay_seconds: float = RADAR_SUBSCRIBER_FETCH_DELAY_SECONDS,
    ) -> list[RadarChannelHit]:
        """
        Radar pipeline using search shelf data with a fast homepage fallback for subscribers.
        """
        thresholds = self.get_thresholds(db)
        effective_upload_period = upload_period or self.get_upload_period(db)
        hits: list[RadarChannelHit] = []
        rejection_logs = 0
        subscriber_cache: dict[str, int | None] = {}

        for video in videos:
            channel_name = video.channel_title or "Unknown"
            upload_date_text = video.published_text.strip() or "—"

            if effective_upload_period != "all" and reject_upload_date_text(
                upload_date_text,
                effective_upload_period,
            ):
                xray_log(
                    f"❌ [ОТКАЗ] Видео слишком старое ({upload_date_text}): {video.title}",
                )
                continue

            video_views = max(video.views_count, 0)
            if video_views < thresholds.min_views:
                if log_rejections and rejection_logs < MAX_REJECTION_LOGS:
                    label = format_channel_label(channel_name)
                    xray_log(
                        f"❌ [ОТКАЗ] {label}: просмотры {video_views:,} "
                        f"< {thresholds.min_views:,}",
                    )
                    rejection_logs += 1
                continue

            if not video.channel_id.strip():
                if log_rejections and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log("❌ [ОТКАЗ] Видео без channel_id — пропуск")
                    rejection_logs += 1
                continue

            if filter_title_language:
                if indian_scripts_pattern.search(video.title) or indian_scripts_pattern.search(
                    channel_name,
                ):
                    xray_log(f"❌ [ОТКАЗ] Индийские символы в названии: {video.title}")
                    continue

            subscribers = max(video.subscribers_count, 0)
            channel_id = video.channel_id

            if subscribers <= 0:
                if channel_id not in subscriber_cache:
                    await asyncio.sleep(subscriber_fetch_delay_seconds)
                    try:
                        subscriber_cache[channel_id] = (
                            await fetch_channel_subscribers_from_homepage(
                                channel_id,
                                channel_name=channel_name,
                            )
                        )
                    except Exception:
                        logger.exception(
                            "Failed to fetch subscribers from channel homepage for %s",
                            channel_id,
                        )
                        subscriber_cache[channel_id] = None

                fetched = subscriber_cache.get(channel_id)
                if fetched is not None and fetched > 0:
                    subscribers = fetched

            if not channel_metrics_usable(subscribers_count=subscribers):
                rejection = explain_missing_channel_metrics(
                    channel_name=channel_name,
                    subscribers_count=subscribers,
                )
                if log_rejections and rejection and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log(f"❌ [ОТКАЗ] {rejection}")
                    rejection_logs += 1
                continue

            viral_coefficient = calc_virality_coefficient(video_views, subscribers)

            rejection = self.explain_rejection(
                thresholds,
                channel_name=channel_name,
                video_views=video_views,
                viral_coefficient=viral_coefficient,
                subscribers=subscribers,
            )
            if rejection:
                if log_rejections and rejection_logs < MAX_REJECTION_LOGS:
                    xray_log(f"❌ [ОТКАЗ] {rejection}")
                    rejection_logs += 1
                continue

            hit = self._register_channel_video(
                db,
                thresholds,
                channel_id=video.channel_id,
                channel_name=channel_name,
                avatar_url=video.channel_avatar_url,
                subscribers=subscribers,
                channel_age_days=DEFAULT_CHANNEL_AGE_DAYS,
                total_views=0,
                viral_coefficient=viral_coefficient,
                representative_video_title=video.title,
                representative_video_thumbnail=video.thumbnail_url,
                representative_video_views=video_views,
                representative_video_id=video.video_id,
                skip_qualify_check=True,
            )
            if hit is not None:
                hits.append(hit)

        db.commit()
        return hits

    def process_channel_analysis(self, db: Session, analysis: ChannelAnalysisModel) -> None:
        thresholds = self.get_thresholds(db)
        subscribers = max(analysis.subscribers_count, 0)
        if not channel_metrics_usable(subscribers_count=subscribers):
            return
        for video in analysis.videos:
            video_views = max(video.views_count, 0)
            viral_coefficient = calc_virality_coefficient(video_views, subscribers)
            self._register_channel_video(
                db,
                thresholds,
                channel_id=analysis.channel_id,
                channel_name=analysis.channel_title or "Unknown",
                avatar_url=analysis.channel_avatar_url,
                subscribers=subscribers,
                channel_age_days=DEFAULT_CHANNEL_AGE_DAYS,
                total_views=max(analysis.total_views, 0),
                viral_coefficient=viral_coefficient,
                representative_video_title=video.title,
                representative_video_thumbnail=video.thumbnail_url,
                representative_video_views=video_views,
                representative_video_id=video.video_id,
            )
        db.commit()

    @classmethod
    def track_enriched_videos(cls, items: list[EnrichedVideoModel]) -> None:
        # Best-effort watchlist ingestion: must never break the user-facing
        # search response, so swallow and log any persistence error.
        if not items:
            return
        db = SessionLocal()
        try:
            cls().process_enriched_videos(db, items)
        except Exception:
            db.rollback()
            logger.exception("Failed to track enriched videos for explosive watchlist")
        finally:
            db.close()

    @classmethod
    def track_channel_analysis(cls, analysis: ChannelAnalysisModel) -> None:
        if not analysis.channel_id or not analysis.videos:
            return
        db = SessionLocal()
        try:
            cls().process_channel_analysis(db, analysis)
        except Exception:
            db.rollback()
            logger.exception("Failed to track channel analysis for explosive watchlist")
        finally:
            db.close()

    def _get_or_create_settings(self, db: Session) -> ExplosiveChannelSettings:
        settings = db.get(ExplosiveChannelSettings, SETTINGS_ROW_ID)
        if settings is not None:
            return settings

        settings = ExplosiveChannelSettings(
            id=SETTINGS_ROW_ID,
            max_age_days=DEFAULT_MAX_AGE_DAYS,
            min_views=DEFAULT_MIN_VIEWS,
            min_viral_coeff=DEFAULT_MIN_VIRAL_COEFF,
            upload_period=DEFAULT_UPLOAD_PERIOD,
            updated_at=utc_now(),
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
        return settings

    def _register(
        self,
        db: Session,
        thresholds: ExplosiveChannelThresholds,
        item: EnrichedVideoModel,
    ) -> RadarChannelHit | None:
        video = item.video
        channel = item.channel
        if not video.channel_id.strip():
            return None

        raw_age = DEFAULT_CHANNEL_AGE_DAYS
        subscribers = max(channel.subscribers_count, 0)
        if not channel_metrics_usable(subscribers_count=subscribers):
            return None

        video_views = max(video.views_count, 0)
        viral_coefficient = calc_virality_coefficient(video_views, subscribers)

        return self._register_channel_video(
            db,
            thresholds,
            channel_id=video.channel_id,
            channel_name=video.channel_title or "Unknown",
            avatar_url=channel.channel_avatar_url or video.channel_avatar_url,
            subscribers=subscribers,
            channel_age_days=raw_age,
            total_views=max(channel.total_views, 0),
            viral_coefficient=viral_coefficient,
            representative_video_title=video.title,
            representative_video_thumbnail=video.thumbnail_url,
            representative_video_views=video_views,
            representative_video_id=video.video_id,
        )

    def _register_channel_video(
        self,
        db: Session,
        thresholds: ExplosiveChannelThresholds,
        *,
        channel_id: str,
        channel_name: str,
        avatar_url: str,
        subscribers: int,
        channel_age_days: int,
        total_views: int,
        viral_coefficient: float,
        representative_video_title: str,
        representative_video_thumbnail: str,
        representative_video_views: int,
        representative_video_id: str = "",
        skip_qualify_check: bool = False,
    ) -> RadarChannelHit | None:
        if is_placeholder_channel(channel_id, channel_name):
            return None

        if not skip_qualify_check and not self.qualifies(
            thresholds,
            video_views=representative_video_views,
            viral_coefficient=viral_coefficient,
        ):
            return None

        now = utc_now()
        existing = db.get(ExplosiveChannel, channel_id)

        if existing is None:
            db.add(
                ExplosiveChannel(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    avatar_url=avatar_url,
                    subscribers=subscribers,
                    channel_age_days=channel_age_days,
                    total_views=total_views,
                    viral_coefficient=viral_coefficient,
                    representative_video_title=representative_video_title,
                    representative_video_thumbnail=representative_video_thumbnail,
                    representative_video_views=representative_video_views,
                    representative_video_id=representative_video_id,
                    updated_at=now,
                ),
            )
            # Flush immediately so a duplicate channel_id later in the same batch
            # is found by db.get() (autoflush is disabled) and updated instead of
            # being inserted again, which would raise a PK IntegrityError.
            db.flush()
            return RadarChannelHit(
                channel_name=channel_name,
                viral_coefficient=viral_coefficient,
            )

        existing.channel_name = channel_name
        existing.avatar_url = avatar_url
        existing.subscribers = subscribers
        existing.channel_age_days = channel_age_days
        existing.total_views = total_views
        existing.updated_at = now

        if viral_coefficient >= existing.viral_coefficient:
            existing.viral_coefficient = viral_coefficient
            existing.representative_video_title = representative_video_title
            existing.representative_video_thumbnail = representative_video_thumbnail
            existing.representative_video_views = representative_video_views
            existing.representative_video_id = representative_video_id
            return RadarChannelHit(
                channel_name=channel_name,
                viral_coefficient=viral_coefficient,
            )

        return None
