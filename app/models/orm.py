from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


class CompetitionLevel(str, enum.Enum):
    """Keyword competition tier."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VideoFormat(str, enum.Enum):
    """Video content format inferred from metadata or duration."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    LIVE = "live"
    UNKNOWN = "unknown"


class Channel(Base):
    """YouTube channel entity."""

    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subscribers_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    custom_url: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        comment="YouTube @handle without prefix",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Channel creation date on YouTube",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    videos: Mapped[list[Video]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )
    snapshots: Mapped[list[ChannelSnapshot]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
    )


class ChannelSnapshot(Base):
    """Point-in-time channel metrics for trend and growth analysis."""

    __tablename__ = "channel_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subscribers_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    channel: Mapped[Channel] = relationship(back_populates="snapshots")


class Video(Base):
    """YouTube video entity linked to a channel."""

    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    views_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    likes_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Video upload date on YouTube",
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_format: Mapped[VideoFormat] = mapped_column(
        Enum(VideoFormat, name="video_format"),
        nullable=False,
        default=VideoFormat.UNKNOWN,
    )
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    channel: Mapped[Channel] = relationship(back_populates="videos")


class Keyword(Base):
    """Search keyword with volume and competition metrics."""

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    search_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    competition_level: Mapped[CompetitionLevel] = mapped_column(
        Enum(CompetitionLevel, name="competition_level"),
        nullable=False,
        default=CompetitionLevel.MEDIUM,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SavedKeyword(Base):
    """User-saved keyword from SEO research."""

    __tablename__ = "saved_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competition: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float] = mapped_column(nullable=False, default=0)
    category: Mapped[str] = mapped_column(String(128), nullable=False, default="")


class ExplosiveChannel(Base):
    """Young high-virality channel discovered during video analysis (FR-5)."""

    __tablename__ = "explosive_channels"

    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    subscribers: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    channel_age_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    viral_coefficient: Mapped[float] = mapped_column(nullable=False, default=0)
    representative_video_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    representative_video_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    representative_video_thumbnail: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    representative_video_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    vph: Mapped[float | None] = mapped_column(nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExplosiveChannelSettings(Base):
    """Global FR-5 thresholds shared by API filters and background ingestion."""

    __tablename__ = "explosive_channel_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_age_days: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    min_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=50_000)
    min_viral_coeff: Mapped[float] = mapped_column(nullable=False, default=3.0)
    upload_period: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TargetKeyword(Base):
    """Keyword queue for the explosive-channels background radar."""

    __tablename__ = "target_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_checked: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class RadarWorkerState(Base):
    """Round-robin cursor for the explosive-channels radar worker."""

    __tablename__ = "radar_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_target_keyword_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExtendedSearchCache(Base):
    """Cached extended anomaly search results (TTL-based)."""

    __tablename__ = "extended_search_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
