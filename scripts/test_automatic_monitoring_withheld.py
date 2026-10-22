"""automatic_monitoring_withheld contract — manual save vs Monitoring vs Discovery handoff."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.db.migrations import ensure_videos_automatic_monitoring_withheld_column
from app.models.db import Base
from app.models.orm import (
    Channel,
    KeywordDiscoveryHit,
    TargetKeyword,
    Video,
    VideoFormat,
    VideoFormatEnrichmentAttempt,
)
from app.services.channel_subscriber_backfill import SUBSCRIBERS_API_KNOWN
from app.services.historical_video_format_verification import OUTCOME_CONFIRMED_REGULAR
from app.services.keyword_discovery_metrics_storage import mark_hits_persisted_for_monitoring
from app.services.manual_search_save import save_video_from_manual_search
from app.services.monitoring_video_source import iter_monitoring_candidate_videos
from app.services.saved_research import archive_video, restore_video
from app.services.video_format_batch_apply import apply_format_details_for_batch
from app.integrations.youtube.client import YouTubeVideoDetails

UTC = timezone.utc


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _session() -> Session:
    return sessionmaker(bind=_engine())()


def _keyword(session: Session, keyword_id: int, text: str) -> None:
    session.add(
        TargetKeyword(
            id=keyword_id,
            keyword=text,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def _channel(session: Session, channel_id: str = "ch-1") -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session.add(
        Channel(
            id=channel_id,
            title="Channel",
            subscribers_count=1000,
            subscribers_api_status=SUBSCRIBERS_API_KNOWN,
            created_at=now,
            updated_at=now,
        ),
    )


def _details(video_id: str, channel_id: str = "ch-1") -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=video_id,
        channel_id=channel_id,
        title="Title",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        views_count=1000,
        likes_count=0,
        comments_count=0,
        duration_seconds=600,
        tags=(),
    )


def _monitoring_ids(session: Session) -> set[str]:
    return {v.id for page in iter_monitoring_candidate_videos(session) for v in page}


def test_new_manual_video_withheld_and_format() -> None:
    session = _session()
    _channel(session)
    save_video_from_manual_search(session, _details("new-manual"))
    session.commit()
    video = session.get(Video, "new-manual")
    assert video is not None
    assert video.automatic_monitoring_withheld is True
    assert video.content_format == VideoFormat.MEDIUM


def test_confirmed_regular_does_not_bypass_withheld() -> None:
    session = _session()
    _channel(session)
    details = _details("refine-manual")
    save_video_from_manual_search(session, details)
    session.commit()
    report = apply_format_details_for_batch(
        session,
        ["refine-manual"],
        {"refine-manual": details},
    )
    session.commit()
    assert report.confirmed_regular == 1
    video = session.get(Video, "refine-manual")
    assert video is not None
    assert video.automatic_monitoring_withheld is True
    assert "refine-manual" not in _monitoring_ids(session)


def test_archive_restore_do_not_change_eligibility() -> None:
    session = _session()
    _channel(session)
    result = save_video_from_manual_search(session, _details("arch-manual"))
    session.commit()
    archive_video(session, result.item.id)
    session.commit()
    video = session.get(Video, "arch-manual")
    assert video.automatic_monitoring_withheld is True
    assert "arch-manual" not in _monitoring_ids(session)
    restore_video(session, result.item.id)
    session.commit()
    video = session.get(Video, "arch-manual")
    assert video.automatic_monitoring_withheld is True
    assert "arch-manual" not in _monitoring_ids(session)


def test_manual_save_existing_monitored_preserves_withheld() -> None:
    session = _session()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _channel(session, "ch-mon")
    session.add(
        Video(
            id="existing-mon",
            title="Mon",
            views_count=5000,
            likes_count=0,
            comments_count=0,
            published_at=now,
            duration_seconds=900,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch-mon",
            automatic_monitoring_withheld=False,
        ),
    )
    session.add(
        VideoFormatEnrichmentAttempt(
            video_id="existing-mon",
            last_outcome=OUTCOME_CONFIRMED_REGULAR,
            last_attempt_at=now,
        ),
    )
    session.commit()
    assert "existing-mon" in _monitoring_ids(session)
    save_video_from_manual_search(session, _details("existing-mon", "ch-mon"))
    session.commit()
    video = session.get(Video, "existing-mon")
    assert video.automatic_monitoring_withheld is False
    assert "existing-mon" in _monitoring_ids(session)


def test_manual_save_existing_not_monitored_preserves_withheld() -> None:
    session = _session()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    _channel(session, "ch-orphan")
    session.add(
        Video(
            id="orphan-vid",
            title="Orphan",
            views_count=100,
            likes_count=0,
            comments_count=0,
            published_at=now,
            duration_seconds=400,
            content_format=VideoFormat.MEDIUM,
            channel_id="ch-orphan",
            automatic_monitoring_withheld=False,
        ),
    )
    session.commit()
    save_video_from_manual_search(session, _details("orphan-vid", "ch-orphan"))
    session.commit()
    video = session.get(Video, "orphan-vid")
    assert video.automatic_monitoring_withheld is False


def test_hit_without_handoff_keeps_withheld() -> None:
    session = _session()
    _channel(session)
    _keyword(session, 1, "kw-hit-only")
    save_video_from_manual_search(session, _details("hit-only"))
    session.commit()
    now = datetime(2026, 1, 2, tzinfo=UTC)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=1,
            video_id="hit-only",
            discovery_run_id="run-1",
            discovered_at=now,
            persisted_for_monitoring=False,
            qualification_state="rejected",
        ),
    )
    session.commit()
    assert session.get(Video, "hit-only").automatic_monitoring_withheld is True
    assert "hit-only" not in _monitoring_ids(session)


def test_discovery_handoff_clears_withheld_and_allows_monitoring() -> None:
    session = _session()
    _channel(session)
    _keyword(session, 2, "kw-handoff")
    details = _details("handoff-vid")
    save_video_from_manual_search(session, details)
    session.commit()
    apply_format_details_for_batch(session, ["handoff-vid"], {"handoff-vid": details})
    session.commit()
    now = datetime(2026, 1, 2, tzinfo=UTC)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=2,
            video_id="handoff-vid",
            discovery_run_id="run-2",
            discovered_at=now,
            persisted_for_monitoring=False,
        ),
    )
    session.flush()
    mark_hits_persisted_for_monitoring(
        session,
        keyword_id=2,
        discovery_run_id="run-2",
        video_ids={"handoff-vid"},
    )
    session.commit()
    video = session.get(Video, "handoff-vid")
    assert video.automatic_monitoring_withheld is False
    assert "handoff-vid" in _monitoring_ids(session)


def test_repeat_save_after_handoff_does_not_rewithhold() -> None:
    session = _session()
    _channel(session)
    _keyword(session, 3, "kw-repeat")
    details = _details("repeat-vid")
    first = save_video_from_manual_search(session, details)
    session.commit()
    now = datetime(2026, 1, 2, tzinfo=UTC)
    session.add(
        KeywordDiscoveryHit(
            keyword_id=3,
            video_id="repeat-vid",
            discovery_run_id="run-3",
            discovered_at=now,
        ),
    )
    session.flush()
    mark_hits_persisted_for_monitoring(
        session,
        keyword_id=3,
        discovery_run_id="run-3",
        video_ids={"repeat-vid"},
    )
    session.commit()
    apply_format_details_for_batch(session, ["repeat-vid"], {"repeat-vid": details})
    session.commit()
    second = save_video_from_manual_search(session, details)
    session.commit()
    assert second.idempotent is True
    assert session.get(Video, "repeat-vid").automatic_monitoring_withheld is False
    assert "repeat-vid" in _monitoring_ids(session)


def test_migration_preserves_existing_monitoring() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE videos (
                    id VARCHAR(64) PRIMARY KEY,
                    title VARCHAR(512) NOT NULL,
                    views_count BIGINT NOT NULL DEFAULT 0,
                    likes_count BIGINT NOT NULL DEFAULT 0,
                    comments_count BIGINT NOT NULL DEFAULT 0,
                    published_at TIMESTAMP NOT NULL,
                    published_at_source VARCHAR(32),
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    content_format VARCHAR(16) NOT NULL,
                    topic VARCHAR(128),
                    tags JSON NOT NULL,
                    channel_id VARCHAR(64) NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
        )
        conn.execute(
            text(
                """
                INSERT INTO videos (
                    id, title, views_count, likes_count, comments_count,
                    published_at, duration_seconds, content_format, tags, channel_id, updated_at
                ) VALUES (
                    'legacy-mon', 'Legacy', 1, 0, 0,
                    '2026-01-01', 900, 'MEDIUM', '[]', 'ch-leg', CURRENT_TIMESTAMP
                )
                """,
            ),
        )
        conn.execute(
            text(
                """
                CREATE TABLE channels (
                    id VARCHAR(64) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    subscribers_count BIGINT NOT NULL DEFAULT 0,
                    subscribers_api_status VARCHAR(16),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
        )
        conn.execute(
            text(
                "INSERT INTO channels (id, title, subscribers_count, subscribers_api_status) "
                "VALUES ('ch-leg', 'Ch', 100, 'known')",
            ),
        )
        conn.execute(
            text(
                """
                CREATE TABLE video_format_enrichment_attempts (
                    video_id VARCHAR(64) PRIMARY KEY,
                    last_attempt_at TIMESTAMP NOT NULL,
                    last_outcome VARCHAR(32) NOT NULL
                )
                """,
            ),
        )
        conn.execute(
            text(
                "INSERT INTO video_format_enrichment_attempts "
                "(video_id, last_attempt_at, last_outcome) "
                "VALUES ('legacy-mon', '2026-01-01', 'confirmed_regular')",
            ),
        )

    ensure_videos_automatic_monitoring_withheld_column(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("videos")}
    assert "automatic_monitoring_withheld" in cols
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT automatic_monitoring_withheld FROM videos WHERE id='legacy-mon'"),
        ).one()
        assert row[0] in (0, False)


def main() -> None:
    test_new_manual_video_withheld_and_format()
    test_confirmed_regular_does_not_bypass_withheld()
    test_archive_restore_do_not_change_eligibility()
    test_manual_save_existing_monitored_preserves_withheld()
    test_manual_save_existing_not_monitored_preserves_withheld()
    test_hit_without_handoff_keeps_withheld()
    test_discovery_handoff_clears_withheld_and_allows_monitoring()
    test_repeat_save_after_handoff_does_not_rewithhold()
    test_migration_preserves_existing_monitoring()
    print("OK: automatic_monitoring_withheld tests passed")


if __name__ == "__main__":
    main()
