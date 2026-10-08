from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
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
    subscribers_api_status: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="channels.list: known | hidden | missing | failed",
    )
    subscribers_api_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
    published_at_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="innertube_relative | api_snippet",
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
    lifecycle_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        index=True,
    )
    scan_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="seed")
    parent_keyword_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="SET NULL"),
        nullable=True,
    )

    scan_runs: Mapped[list[KeywordScanRun]] = relationship(
        back_populates="keyword",
        cascade="all, delete-orphan",
    )
    discovery_hits: Mapped[list[KeywordDiscoveryHit]] = relationship(
        back_populates="keyword",
        cascade="all, delete-orphan",
    )
    lifecycle_events: Mapped[list[KeywordLifecycleEvent]] = relationship(
        back_populates="keyword",
        cascade="all, delete-orphan",
    )


class KeywordLifecycleEvent(Base):
    """Audit trail for keyword lifecycle transitions (Stage 1.16B)."""

    __tablename__ = "keyword_lifecycle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    actor_source: Mapped[str] = mapped_column(String(32), nullable=False, default="system")

    keyword: Mapped[TargetKeyword] = relationship(back_populates="lifecycle_events")


class KeywordExpansionEvent(Base):
    """Audit trail for keyword expansion attempts (Stage 1.16C)."""

    __tablename__ = "keyword_expansion_events"
    __table_args__ = (
        Index("ix_keyword_expansion_parent_source_at", "parent_keyword_id", "source_type", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_keyword_id: Mapped[int] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_text: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_candidate: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    created_keyword_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    discovery_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class KeywordScanRun(Base):
    """One keyword scan within a discovery cycle (Stage 1.16A)."""

    __tablename__ = "keyword_scan_runs"
    __table_args__ = (
        UniqueConstraint(
            "keyword_id",
            "discovery_run_id",
            name="uq_keyword_scan_run_keyword_cycle",
        ),
        Index("ix_keyword_scan_runs_keyword_started", "keyword_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    discovery_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    within_keyword_duplicate_candidates: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    cross_keyword_duplicate_candidates: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    persisted_videos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualification_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualification_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)

    keyword: Mapped[TargetKeyword] = relationship(back_populates="scan_runs")


class KeywordDiscoveryHit(Base):
    """Keyword-to-video discovery attribution for one cycle (Stage 1.16A)."""

    __tablename__ = "keyword_discovery_hits"
    __table_args__ = (
        UniqueConstraint(
            "keyword_id",
            "video_id",
            "discovery_run_id",
            name="uq_keyword_discovery_hit_keyword_video_cycle",
        ),
        Index("ix_keyword_discovery_hits_video", "video_id"),
        Index("ix_keyword_discovery_hits_keyword_discovered", "keyword_id", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    discovery_run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    was_within_keyword_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_cross_keyword_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    video_existed_before_discovery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_format: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    views_at_discovery: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vph_at_discovery: Mapped[float | None] = mapped_column(nullable=True)
    qualification_state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    first_failure_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    persisted_for_monitoring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    keyword: Mapped[TargetKeyword] = relationship(back_populates="discovery_hits")


class KeywordPerformanceGlobalSnapshot(Base):
    """Global breakout denominator metadata for keyword performance reads (Stage 1.20E.4)."""

    __tablename__ = "keyword_performance_global_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    global_eligible_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_decile_rank_cutoff: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ranking_version: Mapped[str] = mapped_column(String(32), nullable=False)


class KeywordPerformanceKeywordSnapshot(Base):
    """Precomputed keyword performance row (Stage 1.20E.4)."""

    __tablename__ = "keyword_performance_keyword_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "keyword_id",
            "attribution_mode",
            name="uq_keyword_performance_snapshot_keyword_mode",
        ),
        Index("ix_keyword_performance_snapshot_mode", "attribution_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attribution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    global_run_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)


class MonitoringVideoQueueEntry(Base):
    """Persisted priority-queue read model for one monitoring cycle (Stage 1.20E.3)."""

    __tablename__ = "monitoring_video_queue"
    __table_args__ = (
        UniqueConstraint("run_id", "video_id", name="uq_monitoring_video_queue_run_video"),
        Index("ix_monitoring_video_queue_run_priority", "run_id", "priority_rank"),
        Index("ix_monitoring_video_queue_run_tier", "run_id", "tier"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(1), nullable=False)
    monitoring_status: Mapped[str] = mapped_column(String(16), nullable=False)
    has_due_checkpoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_overdue_checkpoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_pending_checkpoint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    current_vph: Mapped[float | None] = mapped_column(nullable=True)
    current_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    age_hours: Mapped[float | None] = mapped_column(nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_checkpoint_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_checkpoint_hours_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    overdue_checkpoint_hours_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    channel_velocity_baseline_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vph_vs_channel_median: Mapped[float | None] = mapped_column(nullable=True)
    content_format: Mapped[str | None] = mapped_column(String(16), nullable=True)


class MonitoringCycleRun(Base):
    """Append-only summary of one monitoring worker cycle (Stage 1.14A)."""

    __tablename__ = "monitoring_cycle_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    cycle_status: Mapped[str] = mapped_column(String(16), nullable=False)
    loaded_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_a_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_b_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_c_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overdue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deferred_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persistence_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutcomeCaptureCycleRun(Base):
    """Append-only summary of one delayed outcome capture cycle (Stage 1.20E.2)."""

    __tablename__ = "outcome_capture_cycle_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    cycle_status: Mapped[str] = mapped_column(String(16), nullable=False)
    attribution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="all_hits")
    attributed_observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    satisfied_existing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capture_due_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capture_overdue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_due_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deferred_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutcomeCaptureWorkerState(Base):
    """Singleton lock/state for delayed outcome capture worker (Stage 1.20E.2)."""

    __tablename__ = "outcome_capture_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    lock_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MonitoringWorkerState(Base):
    """Singleton lock/state for the automatic snapshot monitoring worker (Stage 1.13C)."""

    __tablename__ = "monitoring_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    lock_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DiscoveryWorkerState(Base):
    """Singleton lock/state for the automatic discovery worker (Stage 1.15B)."""

    __tablename__ = "discovery_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    lock_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_cycle_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RadarWorkerState(Base):
    """Round-robin cursor for the explosive-channels radar worker."""

    __tablename__ = "radar_worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_target_keyword_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VideoSnapshot(Base):
    """Append-only observation of one video at one capture moment (Stage 1.11)."""

    __tablename__ = "video_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "captured_at",
            "source",
            "run_id",
            name="uq_video_snapshot_capture",
        ),
        Index("ix_video_snapshots_video_captured", "video_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    age_hours: Mapped[float | None] = mapped_column(nullable=True)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    subscribers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    vph: Mapped[float | None] = mapped_column(nullable=True)
    views_per_subscriber: Mapped[float | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
        index=True,
    )
    experiment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    keyword: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_short: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    raw_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)


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


class AttentionRun(Base):
    """One Attention Engine refresh snapshot (Stage 1.22A)."""

    __tablename__ = "attention_runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone_name: Mapped[str] = mapped_column(String(32), nullable=False, default="UTC")
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candidate_video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winner_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pattern_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel_momentum_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    pattern_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    channel_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class AttentionVideoWinnerRow(Base):
    """Persisted VideoWinner row for one attention run."""

    __tablename__ = "attention_video_winners"
    __table_args__ = (
        UniqueConstraint("run_id", "video_id", name="uq_attention_video_winner_run_video"),
        Index("ix_attention_video_winners_run_rank", "run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class AttentionPatternRow(Base):
    """Persisted Pattern v1 row for one attention run."""

    __tablename__ = "attention_patterns"
    __table_args__ = (
        UniqueConstraint("run_id", "pattern_key", name="uq_attention_pattern_run_key"),
        Index("ix_attention_patterns_run_rank", "run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class AttentionPatternVideoRow(Base):
    """Pattern membership for GET /patterns/{id} without recomputing groups."""

    __tablename__ = "attention_pattern_videos"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "pattern_key",
            "video_id",
            name="uq_attention_pattern_video",
        ),
        Index("ix_attention_pattern_videos_run_key", "run_id", "pattern_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)


class AttentionPatternFamilyRow(Base):
    """Persisted PatternFamily aggregation for one attention run (Stage 1.22B.1)."""

    __tablename__ = "attention_pattern_families"
    __table_args__ = (
        UniqueConstraint("run_id", "family_key", name="uq_attention_family_run_key"),
        Index("ix_attention_pattern_families_run_rank", "run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    family_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class AttentionPatternFamilyMemberRow(Base):
    __tablename__ = "attention_pattern_family_members"
    __table_args__ = (
        UniqueConstraint("run_id", "family_key", "pattern_key", name="uq_attention_family_member"),
        Index("ix_attention_family_members_run_key", "run_id", "family_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_key: Mapped[str] = mapped_column(String(160), nullable=False)
    pattern_key: Mapped[str] = mapped_column(String(128), nullable=False)


class AttentionPatternFamilyVideoRow(Base):
    __tablename__ = "attention_pattern_family_videos"
    __table_args__ = (
        UniqueConstraint("run_id", "family_key", "video_id", name="uq_attention_family_video"),
        Index("ix_attention_family_videos_run_key", "run_id", "family_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_key: Mapped[str] = mapped_column(String(160), nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)


class AttentionFamilyIdentity(Base):
    """Cross-run map pattern_key → family_key so bookmarks survive membership growth."""

    __tablename__ = "attention_family_identity"

    pattern_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    family_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelSubscriberEnrichmentAttempt(Base):
    """channels.list subscriber checks when Channel row may be absent (Stage 2.5)."""

    __tablename__ = "channel_subscriber_enrichment_attempts"

    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    last_outcome: Mapped[str] = mapped_column(String(32), nullable=False)


class RadarApiBudgetDay(Base):
    """UTC-day reserved ID units and HTTP batch counts for enrichment API caps (Stage 2.5)."""

    __tablename__ = "radar_api_budget_daily"

    budget_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    utc_day: Mapped[date] = mapped_column(Date, primary_key=True)
    id_units_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReadModelPublishLock(Base):
    """Singleton publish lock per read model kind (Attention, keyword performance)."""

    __tablename__ = "read_model_publish_locks"

    kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    lock_holder: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class VideoFormatEnrichmentAttempt(Base):
    """Tracks videos.list format checks for daily budget and queue rotation (Stage 2.1)."""

    __tablename__ = "video_format_enrichment_attempts"

    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    last_outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")


class SavedTopicStatus(str, enum.Enum):
    WATCHING = "WATCHING"
    WANT_TO_TEST = "WANT_TO_TEST"
    TESTING = "TESTING"
    DROPPED = "DROPPED"


class SavedTopic(Base):
    """User watchlist entry keyed by Pattern Family (Stage 1.22C)."""

    __tablename__ = "saved_topics"
    __table_args__ = (UniqueConstraint("family_key", name="uq_saved_topics_family_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SavedTopicStatus.WATCHING.value)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    frozen_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class SavedTopicEvent(Base):
    """Append-only user decision log for a saved topic (Stage 1.22D)."""

    __tablename__ = "saved_topic_events"
    __table_args__ = (Index("ix_saved_topic_events_topic_occurred", "saved_topic_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    saved_topic_id: Mapped[int] = mapped_column(
        ForeignKey("saved_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class SavedTopicFeedback(Base):
    """Append-only analyst feedback on a saved topic (Stage 1.22D)."""

    __tablename__ = "saved_topic_feedback"
    __table_args__ = (Index("ix_saved_topic_feedback_topic_recorded", "saved_topic_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    saved_topic_id: Mapped[int] = mapped_column(
        ForeignKey("saved_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finding_rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    own_test_video_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    own_test_video_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    own_test_outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    manual_metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class SavedTopicObservation(Base):
    """Append-only live-state capture per Attention publication (Stage 1.22C)."""

    __tablename__ = "saved_topic_observations"
    __table_args__ = (
        UniqueConstraint("saved_topic_id", "attention_run_id", name="uq_saved_topic_observation_run"),
        Index("ix_saved_topic_observations_topic_captured", "saved_topic_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    saved_topic_id: Mapped[int] = mapped_column(
        ForeignKey("saved_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attention_run_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class AttentionChannelMomentumRow(Base):
    """Persisted ChannelMomentum row for one attention run."""

    __tablename__ = "attention_channel_momentum"
    __table_args__ = (
        UniqueConstraint("run_id", "channel_id", name="uq_attention_channel_run"),
        Index("ix_attention_channel_momentum_run_rank", "run_id", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("attention_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class TopicExplorationPass(Base):
    """One broad exploration query execution within a discovery cycle (Stage 6)."""

    __tablename__ = "topic_exploration_passes"
    __table_args__ = (
        UniqueConstraint(
            "pass_discovery_run_id",
            name="uq_topic_exploration_pass_run_id",
        ),
        Index("ix_topic_exploration_pass_query_observed", "exploration_query_id", "observed_at"),
        Index("ix_topic_exploration_pass_cycle", "cycle_discovery_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_discovery_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pass_discovery_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exploration_query_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exploration_query_text: Mapped[str] = mapped_column(String(512), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    pages_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_videos_observed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settings_version: Mapped[str] = mapped_column(String(32), nullable=False)
    pass_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    video_observations: Mapped[list[TopicExplorationVideoObservation]] = relationship(
        back_populates="pass_row",
        cascade="all, delete-orphan",
    )
    phrase_stats: Mapped[list[TopicExplorationPhrasePassStat]] = relationship(
        back_populates="pass_row",
        cascade="all, delete-orphan",
    )


class TopicExplorationVideoObservation(Base):
    """Unique video seen in one exploration pass (deduped per pass)."""

    __tablename__ = "topic_exploration_video_observations"
    __table_args__ = (
        UniqueConstraint(
            "pass_id",
            "video_id",
            name="uq_topic_exploration_video_per_pass",
        ),
        Index("ix_topic_exploration_video_obs_video", "video_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pass_id: Mapped[int] = mapped_column(
        ForeignKey("topic_exploration_passes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    pass_row: Mapped[TopicExplorationPass] = relationship(back_populates="video_observations")


class TopicExplorationPhrasePassStat(Base):
    """Phrase support counts for one exploration pass (novelty / audit)."""

    __tablename__ = "topic_exploration_phrase_pass_stats"
    __table_args__ = (
        UniqueConstraint(
            "pass_id",
            "normalized_phrase",
            name="uq_topic_exploration_phrase_per_pass",
        ),
        Index("ix_topic_exploration_phrase_fp", "normalized_phrase", "pass_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pass_id: Mapped[int] = mapped_column(
        ForeignKey("topic_exploration_passes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    normalized_phrase: Mapped[str] = mapped_column(String(256), nullable=False)
    distinct_video_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_channel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    cycle_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    exploration_query_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admitted_keyword_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_keywords.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_video_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_channel_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    pass_discovery_run_id: Mapped[str] = mapped_column(String(128), nullable=False)

    pass_row: Mapped[TopicExplorationPass] = relationship(back_populates="phrase_stats")
