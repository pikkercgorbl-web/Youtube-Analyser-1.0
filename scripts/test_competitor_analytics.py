"""Verification for competitor analytics module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db import Base
from app.models.orm import Channel, Video, VideoFormat
from app.services.competitor_analysis_service import CompetitorAnalysisService
from app.services.metrics import calc_vph


def _seed_channel(
    db: Session,
    *,
    channel_id: str,
    title: str,
    subscribers: int,
    topic: str,
    videos: list[tuple[str, int, str, list[str], VideoFormat, int]],
) -> None:
    now = datetime.now(timezone.utc)
    channel = Channel(
        id=channel_id,
        title=title,
        subscribers_count=subscribers,
        topic=topic,
        created_at=now - timedelta(days=400),
    )
    db.add(channel)

    for index, (vid, views, video_topic, tags, fmt, hours_ago) in enumerate(videos):
        db.add(
            Video(
                id=vid,
                title=f"{title} #{index}",
                views_count=views,
                likes_count=views // 100,
                comments_count=views // 500,
                published_at=now - timedelta(hours=hours_ago),
                duration_seconds=45 if fmt == VideoFormat.SHORT else 900,
                content_format=fmt,
                topic=video_topic,
                tags=tags,
                channel_id=channel_id,
            ),
        )


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db: Session = sessionmaker(bind=engine)()

    channel_specs = [
        ("UC0000000000000000000001", "Horror Stories A", "horror", VideoFormat.SHORT, "scary stories"),
        ("UC0000000000000000000002", "Horror Stories B", "horror", VideoFormat.MEDIUM, "true crime"),
        ("UC0000000000000000000003", "History Facts A", "history", VideoFormat.MEDIUM, "ancient rome"),
        ("UC0000000000000000000004", "History Facts B", "history", VideoFormat.LONG, "medieval"),
        ("UC0000000000000000000005", "Horror Stories C", "horror", VideoFormat.SHORT, "creepypasta"),
        ("UC0000000000000000000006", "History Facts C", "history", VideoFormat.SHORT, "ww2"),
        ("UC0000000000000000000007", "Horror Stories D", "horror", VideoFormat.MEDIUM, "paranormal"),
        ("UC0000000000000000000008", "History Facts D", "history", VideoFormat.MEDIUM, "egypt"),
        ("UC0000000000000000000009", "Horror Stories E", "horror", VideoFormat.SHORT, "reddit"),
        ("UC0000000000000000000010", "History Facts E", "history", VideoFormat.LONG, "vikings"),
    ]

    for idx, (cid, title, niche, fmt, topic) in enumerate(channel_specs):
        views_base = 50_000 + idx * 10_000
        _seed_channel(
            db,
            channel_id=cid,
            title=title,
            subscribers=10_000 + idx * 1_000,
            topic=niche,
            videos=[
                (
                    f"{cid}_v{i}",
                    views_base + i * 5_000,
                    topic,
                    [topic.replace(" ", "-"), niche],
                    fmt,
                    24 + i * 12,
                )
                for i in range(3)
            ],
        )

    db.commit()

    service = CompetitorAnalysisService(db)

    refs = [spec[0] for spec in channel_specs]
    mass = service.mass_analyze(refs, videos_per_channel=50)
    assert mass.channels_found == 10
    assert mass.total_videos_analyzed == 30
    assert mass.videos
    assert mass.videos[0].video_url.startswith("https://www.youtube.com/watch?v=")
    assert mass.videos[0].channel_url.startswith("https://www.youtube.com/channel/")
    assert mass.videos[0].outlier_score >= mass.videos[-1].outlier_score

    growing = db.get(Channel, "UC0000000000000000000001")
    assert growing is not None
    old_snapshot = service.record_channel_snapshot(
        growing.id,
        recorded_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    old_snapshot.subscribers_count = 1_000
    old_snapshot.total_views = 10_000
    db.commit()

    growing.subscribers_count = 5_000
    for video in db.query(Video).filter(Video.channel_id == growing.id):
        video.views_count *= 3
    db.commit()

    leaders = service.get_youtube_leaders(window_days=7, limit=5)
    assert leaders.leaders
    assert leaders.leaders[0].channel_id == growing.id
    assert leaders.leaders[0].growth_score > 0

    sample_vph = calc_vph(120_000, datetime.now(timezone.utc) - timedelta(hours=24))
    assert sample_vph == 5_000.0

    print("Competitor analytics checks passed.")


if __name__ == "__main__":
    main()
