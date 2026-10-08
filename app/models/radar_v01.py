"""Persistence models for Radar v0.1 experimental trend detection.

These models are intentionally additive. The current application can keep using
SQLite while the semantic embedding column is represented as JSON; the planned
PostgreSQL migration can replace that storage with pgvector(384) without
changing the higher-level domain fields.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class RadarCandidate(Base):
    """Every eligible or rejected video discovered by the radar."""

    __tablename__ = "radar_candidates"

    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    discovery_keyword: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    first_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    eligible: Mapped[bool] = mapped_column(nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tier: Mapped[str] = mapped_column(String(2), nullable=False, default="T0")
    checks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoEmbedding(Base):
    """Deterministic semantic embedding metadata for an eligible video."""

    __tablename__ = "video_embeddings"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Temporary SQLite-compatible storage; replace with pgvector(384) on PostgreSQL.",
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RadarDiscoveryMetric(Base):
    """Aggregated Stage 0 throughput measurements per discovery cycle."""

    __tablename__ = "radar_discovery_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    keyword: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    videos_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    videos_format_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    videos_hard_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    videos_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_channels_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
