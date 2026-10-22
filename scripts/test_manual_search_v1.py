"""Manual search v1 — save, context, search path (delegates monitoring contract tests)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.api.routes import manual_search as manual_search_routes
from app.integrations.youtube.client import EnrichedVideoModel, VideoSearchModel, ChannelDetailModel, YouTubeVideoDetails
from app.main import app as main_app
from app.models.db import Base, get_db
from app.models.orm import Channel, KeywordDiscoveryHit, SavedVideo, Video, VideoFormat
from app.services.manual_search_save import save_video_from_manual_search
from app.services.monitoring_video_source import iter_monitoring_candidate_videos

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


def _sample_details(video_id: str = "yt-manual-1") -> YouTubeVideoDetails:
    return YouTubeVideoDetails(
        video_id=video_id,
        channel_id="ch-manual-1",
        title="Manual Save Title",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        views_count=1200,
        likes_count=10,
        comments_count=2,
        duration_seconds=600,
        tags=("tag",),
    )


def test_save_without_attention_winner() -> None:
    session = _session()
    session.add(
        Channel(
            id="ch-manual-1",
            title="Ch",
            subscribers_count=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    result = save_video_from_manual_search(session, _sample_details())
    session.commit()
    assert result.created is True
    video = session.get(Video, "yt-manual-1")
    assert video is not None
    assert video.content_format == VideoFormat.MEDIUM
    assert video.automatic_monitoring_withheld is True
    saved = session.scalar(select(SavedVideo).where(SavedVideo.video_id == "yt-manual-1"))
    assert saved is not None
    assert saved.created_from_attention_run_id is None


def test_save_idempotent() -> None:
    session = _session()
    session.add(
        Channel(
            id="ch-manual-1",
            title="Ch",
            subscribers_count=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    first = save_video_from_manual_search(session, _sample_details())
    session.commit()
    second = save_video_from_manual_search(session, _sample_details())
    session.commit()
    assert first.created is True
    assert second.idempotent is True
    count = session.scalar(select(func.count()).select_from(SavedVideo))
    assert count == 1


def test_new_video_not_in_monitoring_selectors() -> None:
    session = _session()
    session.add(
        Channel(
            id="ch-manual-1",
            title="Ch",
            subscribers_count=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    save_video_from_manual_search(session, _sample_details())
    session.commit()
    pages = list(iter_monitoring_candidate_videos(session))
    ids = {v.id for page in pages for v in page}
    assert "yt-manual-1" not in ids


def test_no_keyword_discovery_hit_on_save() -> None:
    session = _session()
    session.add(
        Channel(
            id="ch-manual-1",
            title="Ch",
            subscribers_count=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    save_video_from_manual_search(session, _sample_details())
    session.commit()
    hits = session.scalar(select(func.count()).select_from(KeywordDiscoveryHit))
    assert hits == 0


def test_search_uses_external_client_not_db_bulk_persist() -> None:
    enriched = [
        EnrichedVideoModel(
            video=VideoSearchModel(
                video_id="search-1",
                channel_id="ch-1",
                title="Hit",
                views_count=100,
            ),
            channel=ChannelDetailModel(),
            virality_coefficient=0.0,
        ),
    ]
    with patch(
        "app.services.manual_search_http.get_enriched_search_results",
        new_callable=AsyncMock,
        return_value=enriched,
    ) as mock_search:
        client = TestClient(main_app)
        response = client.post("/api/search", json={"query": "test query", "sort_by": "relevance"})
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.await_args.kwargs
    assert call_kwargs.get("save_to_db") is False
    db = _session()
    try:
        assert db.get(Video, "search-1") is None
    finally:
        db.close()


def test_manual_search_api_save_and_context() -> None:
    engine = _engine()
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    mini = FastAPI()
    mini.include_router(manual_search_routes.router, prefix="/api/manual-search")
    mini.dependency_overrides[get_db] = override_db

    mock_yt = type("YT", (), {"get_videos": lambda self, ids: [_sample_details("api-vid-1")]})()

    from app.api.deps import get_youtube_client

    mini.dependency_overrides[get_youtube_client] = lambda: mock_yt

    with SessionLocal() as db:
        db.add(
            Channel(
                id="ch-manual-1",
                title="Ch",
                subscribers_count=0,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        db.commit()

    client = TestClient(mini)
    ctx = client.post("/api/manual-search/video-context", json={"video_ids": ["missing"]})
    assert ctx.status_code == 200
    assert ctx.json()["items"][0]["in_corpus"] is False

    save = client.post("/api/manual-search/save-video", json={"video_id": "api-vid-1"})
    assert save.status_code == 200
    assert save.json()["created"] is True

    ctx2 = client.post("/api/manual-search/video-context", json={"video_ids": ["api-vid-1"]})
    body = ctx2.json()["items"][0]
    assert body["in_corpus"] is True
    assert body["saved_video_id"] is not None


def main() -> None:
    test_save_without_attention_winner()
    test_save_idempotent()
    test_new_video_not_in_monitoring_selectors()
    test_no_keyword_discovery_hit_on_save()
    test_search_uses_external_client_not_db_bulk_persist()
    test_manual_search_api_save_and_context()
    print("OK: manual search v1 tests passed")


if __name__ == "__main__":
    main()
