"""Quick verification of advanced video search (run: python -m scripts.test_video_search)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db import Base
from app.models.orm import Channel, Video
from app.models.schemas import VideoSearchParams, VideoSortField
from app.services.video_service import VideoService, calc_virality_percent


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = sessionmaker(bind=engine)()

    now = datetime.now(timezone.utc)
    channel = Channel(
        id="ch_small",
        title="Tiny Channel",
        subscribers_count=50,
        topic="tech",
        created_at=now,
    )
    viral_video = Video(
        id="vid_viral",
        title="Unexpected hit",
        views_count=500_000,
        likes_count=12_000,
        comments_count=800,
        published_at=now,
        duration_seconds=420,
        channel_id="ch_small",
    )
    normal_video = Video(
        id="vid_normal",
        title="Regular upload",
        views_count=400,
        likes_count=40,
        comments_count=5,
        published_at=now,
        duration_seconds=180,
        channel_id="ch_small",
    )
    db.add_all([channel, viral_video, normal_video])
    db.commit()

    assert calc_virality_percent(500_000, 50) == 1_000_000.0

    service = VideoService(db)

    all_rows, all_total = service.advanced_search(VideoSearchParams())
    assert all_total == 2

    anomaly_rows, anomaly_total = service.advanced_search(
        VideoSearchParams(anomalies_only=True, min_virality_percent=1000.0),
    )
    assert anomaly_total == 1
    assert anomaly_rows[0].video.id == "vid_viral"
    assert anomaly_rows[0].virality_percent == 1_000_000.0

    sorted_rows, _ = service.advanced_search(
        VideoSearchParams(sort_by=VideoSortField.VIRALITY, min_virality_percent=0),
    )
    assert sorted_rows[0].video.id == "vid_viral"

    print("All video search checks passed.")


if __name__ == "__main__":
    main()
