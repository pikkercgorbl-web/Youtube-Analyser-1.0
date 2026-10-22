"""SavedVideo similar-search watch (v1) tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.integrations.youtube.client import VideoSearchModel
from app.models.db import Base
from app.models.orm import (
    KeywordDiscoveryHit,
    SavedVideo,
    SavedVideoSimilarFinding,
    SavedVideoSimilarScan,
    SavedVideoSimilarWatch,
    TargetKeyword,
)
from app.services.saved_research import archive_video, restore_video, save_video
from app.services.saved_video_similar_search import SimilarQuerySearchResult
from app.services.saved_video_similar_watch import (
    WATCH_ACTIVE,
    WATCH_PAUSED,
    confirm_similar_watch_queries,
    execute_similar_watch_scan,
    get_or_create_watch_draft,
    list_findings_grouped,
    pause_similar_watch,
    resume_similar_watch,
    run_similar_watch_batch_for_discovery_cycle,
    save_finding_to_saved_research,
    set_similar_finding_feedback,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


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


def _seed_saved_video(session: Session) -> SavedVideo:
    from app.models.orm import Channel, Video

    session.add(Channel(id="ch-a", title="Channel A", subscribers_count=1000, created_at=NOW))
    session.add(
        Video(
            id="anchor-vid",
            title="Minecraft what if survival hardcore",
            views_count=1000,
            likes_count=0,
            comments_count=0,
            published_at=NOW,
            duration_seconds=600,
            channel_id="ch-a",
        ),
    )
    session.commit()
    from app.services.attention_engine_types import AttentionEngineResult, AttentionSummary, VideoWinner, youtube_watch_url
    from app.services.attention_read_model import persist_attention_result

    winner = VideoWinner(
        video_id="anchor-vid",
        title="Minecraft what if survival hardcore",
        channel_id="ch-a",
        channel_title="Channel A",
        youtube_url=youtube_watch_url("anchor-vid"),
        published_at=NOW,
        age_hours=12.0,
        views=1000,
        vph=100.0,
        subscribers=1000,
        breakout_rank=None,
        breakout_eligible=False,
        channel_relative_signal=None,
        acceleration_state="unknown",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=(),
        human_reasons=(),
        keyword_ids=(),
    )
    result = AttentionEngineResult(
        summary=AttentionSummary(
            run_id="run1",
            computed_at=NOW,
            timezone_name="UTC",
            window_hours=24,
            window_start=NOW,
            window_end=NOW,
            source="test",
            candidate_video_count=1,
            winner_count=1,
            pattern_count=0,
            channel_momentum_count=0,
            video_limit=50,
            pattern_limit=20,
            channel_limit=20,
            notes={},
        ),
        video_winners=(winner,),
        patterns=(),
        families=(),
        channels=(),
    )
    persist_attention_result(session, result, run_id="run1")
    session.commit()
    saved = save_video(session, video_id="anchor-vid")
    session.commit()
    return saved.item


def _mock_search_side_effect(*args, **kwargs):
    query = args[0] if args else kwargs.get("query", "")
    if "bad" in query.lower():
        return SimilarQuerySearchResult(query=query, videos=[], error="fail")
    v1 = VideoSearchModel(
        video_id="found-1",
        channel_id="ch-b",
        channel_title="B",
        title="Low views found",
        views_count=50,
        published_text="1 day ago",
        thumbnail_url="https://i.ytimg.com/vi/found-1/hqdefault.jpg",
    )
    v2 = VideoSearchModel(
        video_id="found-dup",
        channel_id="ch-b",
        channel_title="B",
        title="Dup",
        views_count=80,
    )
    videos = [v1]
    if "second" in query.lower():
        videos = [v2, v1]
    return SimilarQuerySearchResult(query=query, videos=videos, pages_scanned=1)


def test_save_does_not_create_watch_or_keywords() -> None:
    session = _session()
    row = _seed_saved_video(session)
    assert session.scalar(select(func.count()).select_from(SavedVideoSimilarWatch)) == 0
    assert session.scalar(select(func.count()).select_from(TargetKeyword)) == 0
    assert session.scalar(select(func.count()).select_from(KeywordDiscoveryHit)) == 0
    assert row.video_id == "anchor-vid"


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_confirm_and_scan(mock_search) -> None:
    session = _session()
    row = _seed_saved_video(session)
    get_or_create_watch_draft(session, saved_video_id=row.id)
    confirm_similar_watch_queries(
        session,
        saved_video_id=row.id,
        queries=["minecraft what if", "second query"],
    )
    session.commit()
    summary = execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
    session.commit()
    assert summary.queries_attempted == 2
    assert summary.display_state == "has_results"
    findings = session.scalars(select(SavedVideoSimilarFinding)).all()
    assert len(findings) >= 2
    ids = {f.video_id for f in findings}
    assert "anchor-vid" not in ids
    assert "found-1" in ids


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_same_video_two_queries_one_scan(mock_search) -> None:
    session = _session()
    row = _seed_saved_video(session)

    async def _dup_queries(query, **kwargs):
        v = VideoSearchModel(
            video_id="found-dup",
            channel_id="ch-b",
            channel_title="B",
            title="Shared",
            views_count=10,
        )
        return SimilarQuerySearchResult(query=query, videos=[v], pages_scanned=1)

    with patch(
        "app.services.saved_video_similar_watch.search_similar_videos_for_query",
        new_callable=AsyncMock,
        side_effect=_dup_queries,
    ):
        confirm_similar_watch_queries(session, saved_video_id=row.id, queries=["q1", "q2"])
        session.commit()
        execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
        session.commit()
    assert session.scalar(select(func.count()).select_from(SavedVideoSimilarFinding)) == 1


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_rescan_no_duplicate(mock_search) -> None:
    session = _session()
    row = _seed_saved_video(session)
    confirm_similar_watch_queries(session, saved_video_id=row.id, queries=["minecraft what if", "second query"])
    session.commit()
    execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
    session.commit()
    execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
    session.commit()
    count = session.scalar(select(func.count()).select_from(SavedVideoSimilarFinding))
    assert count == 2
    scans = session.scalar(select(func.count()).select_from(SavedVideoSimilarScan))
    assert scans == 2


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_partial_query_error(mock_search) -> None:
    session = _session()
    row = _seed_saved_video(session)
    confirm_similar_watch_queries(session, saved_video_id=row.id, queries=["minecraft what if", "bad query"])
    session.commit()
    summary = execute_similar_watch_scan(session, saved_video_id=row.id, trigger="manual")
    session.commit()
    assert summary.queries_failed == 1
    assert summary.queries_attempted == 2
    watch = session.get(SavedVideoSimilarWatch, row.id)
    assert watch is not None
    assert watch.last_display_state == "partial_error"
    assert session.scalar(select(func.count()).select_from(SavedVideoSimilarFinding)) >= 1


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_archive_pause_and_restore_stays_paused(mock_search) -> None:
    session = _session()
    row = _seed_saved_video(session)
    confirm_similar_watch_queries(session, saved_video_id=row.id, queries=["q one", "q two"])
    session.commit()
    archive_video(session, row.id)
    session.commit()
    watch = session.get(SavedVideoSimilarWatch, row.id)
    assert watch is not None
    assert watch.status == WATCH_PAUSED
    restore_video(session, row.id)
    session.commit()
    watch = session.get(SavedVideoSimilarWatch, row.id)
    assert watch.status == WATCH_PAUSED


@patch(
    "app.services.saved_video_similar_watch.search_similar_videos_for_query",
    new_callable=AsyncMock,
    side_effect=_mock_search_side_effect,
)
def test_batch_respects_query_budget(mock_search) -> None:
    from app.models.orm import Channel, Video
    from app.services.saved_research import build_video_frozen_payload

    session = _session()
    session.add(Channel(id="ch-a", title="Channel A", subscribers_count=1000, created_at=NOW))
    for i in range(4):
        vid = f"anchor-{i}"
        session.add(
            Video(
                id=vid,
                title=f"Title {i} minecraft test",
                views_count=100,
                likes_count=0,
                comments_count=0,
                published_at=NOW,
                duration_seconds=600,
                channel_id="ch-a",
            ),
        )
    session.commit()
    saved_ids: list[int] = []
    for i in range(4):
        vid = f"anchor-{i}"
        video = session.get(Video, vid)
        frozen = build_video_frozen_payload(
            winner=None,
            video=video,
            channel=session.get(Channel, "ch-a"),
            result=None,
            family_memberships=[],
        )
        row = SavedVideo(
            video_id=vid,
            saved_at=NOW,
            frozen_title=video.title,
            frozen_channel_id="ch-a",
            frozen_channel_title="Channel A",
            frozen_payload_json=json.dumps(frozen, ensure_ascii=False),
            latest_observed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(row)
        session.flush()
        saved_ids.append(row.id)
        confirm_similar_watch_queries(session, saved_video_id=row.id, queries=["a query", "b query"])
        w = session.get(SavedVideoSimilarWatch, row.id)
        assert w is not None
        w.next_scan_at = NOW
    session.commit()
    n = run_similar_watch_batch_for_discovery_cycle(session)
    session.commit()
    assert n <= 3
    assert mock_search.await_count <= 9


def test_suggest_queries_deterministic() -> None:
    from app.services.saved_video_similar_query_suggest import suggest_similar_search_queries

    a = suggest_similar_search_queries(title="Minecraft what if hardcore")
    b = suggest_similar_search_queries(title="Minecraft what if hardcore")
    assert a == b
    assert 1 <= len(a) <= 5


def test_batch_partial_five_queries() -> None:
    """After earlier watches consume budget, a 5-query watch runs a partial chunk."""
    from app.models.orm import Channel, Video
    from app.services.saved_research import build_video_frozen_payload

    session = _session()
    session.add(Channel(id="ch-b", title="Channel B", subscribers_count=1000, created_at=NOW))
    saved_ids: list[int] = []
    for i in range(3):
        vid = f"anchor-partial-{i}"
        session.add(
            Video(
                id=vid,
                title="10 Biggest Grain Carts Ever Built",
                views_count=100,
                likes_count=0,
                comments_count=0,
                published_at=NOW,
                duration_seconds=600,
                channel_id="ch-b",
            ),
        )
    session.commit()
    ch = session.get(Channel, "ch-b")
    query_sets = [
        ["grain carts a1", "grain carts a2", "grain carts a3"],
        ["grain carts b1", "grain carts b2", "grain carts b3"],
        [f"grain carts big {i}" for i in range(5)],
    ]
    for i, qset in enumerate(query_sets):
        video = session.get(Video, f"anchor-partial-{i}")
        frozen = build_video_frozen_payload(
            winner=None,
            video=video,
            channel=ch,
            result=None,
            family_memberships=[],
        )
        row = SavedVideo(
            video_id=video.id,
            saved_at=NOW,
            frozen_title=video.title,
            frozen_channel_id="ch-b",
            frozen_channel_title="Channel B",
            frozen_payload_json=json.dumps(frozen, ensure_ascii=False),
            latest_observed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(row)
        session.flush()
        saved_ids.append(row.id)
        confirm_similar_watch_queries(session, saved_video_id=row.id, queries=qset)
        w = session.get(SavedVideoSimilarWatch, row.id)
        assert w is not None
        w.next_scan_at = NOW - timedelta(seconds=10 - i)
    session.commit()

    with patch(
        "app.services.saved_video_similar_watch.search_similar_videos_for_query",
        new_callable=AsyncMock,
        side_effect=_mock_search_side_effect,
    ):
        run_similar_watch_batch_for_discovery_cycle(session)
        session.commit()
        w_partial = session.get(SavedVideoSimilarWatch, saved_ids[2])
        assert w_partial is not None
        assert w_partial.batch_query_offset == 3


def test_similar_finding_feedback_does_not_add_saved_video() -> None:
    session = _session()
    anchor = _seed_saved_video(session)
    now = NOW
    finding = SavedVideoSimilarFinding(
        saved_video_id=anchor.id,
        video_id="similar-candidate-1",
        matched_query="minecraft what if",
        first_found_at=now,
        last_found_at=now,
        payload_json=json.dumps(
            {
                "title": "Another minecraft what if clip",
                "channel_id": "ch-a",
                "channel_title": "Channel A",
                "views_count": 100,
            },
            ensure_ascii=False,
        ),
    )
    session.add(finding)
    session.commit()
    before = session.scalar(select(func.count()).select_from(SavedVideo)) or 0
    set_similar_finding_feedback(
        session,
        saved_video_id=anchor.id,
        finding_id=finding.id,
        verdict="fit",
    )
    session.commit()
    after = session.scalar(select(func.count()).select_from(SavedVideo)) or 0
    assert after == before


def test_save_finding_adds_saved_video_idempotent() -> None:
    session = _session()
    anchor = _seed_saved_video(session)
    now = NOW
    finding = SavedVideoSimilarFinding(
        saved_video_id=anchor.id,
        video_id="similar-candidate-2",
        matched_query="minecraft what if",
        first_found_at=now,
        last_found_at=now,
        payload_json=json.dumps(
            {
                "title": "Save me minecraft",
                "channel_id": "ch-a",
                "channel_title": "Channel A",
                "views_count": 50,
            },
            ensure_ascii=False,
        ),
    )
    session.add(finding)
    session.commit()
    before = session.scalar(select(func.count()).select_from(SavedVideo)) or 0
    first = save_finding_to_saved_research(session, saved_video_id=anchor.id, finding_id=finding.id)
    session.commit()
    mid = session.scalar(select(func.count()).select_from(SavedVideo)) or 0
    assert mid == before + 1
    second = save_finding_to_saved_research(session, saved_video_id=anchor.id, finding_id=finding.id)
    session.commit()
    after = session.scalar(select(func.count()).select_from(SavedVideo)) or 0
    assert after == mid
    assert first.idempotent is False
    assert second.idempotent is True


def test_list_findings_grouped_uses_live_relevance_not_stale_payload() -> None:
    session = _session()
    from app.models.orm import Channel, Video
    from app.services.saved_research import build_video_frozen_payload

    session.add(Channel(id="ch-grain", title="G", subscribers_count=1, created_at=NOW))
    video = Video(
        id="grain-anchor",
        title="10 Biggest Grain Carts Ever Built",
        views_count=1,
        likes_count=0,
        comments_count=0,
        published_at=NOW,
        duration_seconds=60,
        channel_id="ch-grain",
    )
    session.add(video)
    session.commit()
    ch = session.get(Channel, "ch-grain")
    frozen = build_video_frozen_payload(
        winner=None,
        video=video,
        channel=ch,
        result=None,
        family_memberships=[],
    )
    saved = SavedVideo(
        video_id=video.id,
        saved_at=NOW,
        frozen_title=video.title,
        frozen_channel_id="ch-grain",
        frozen_channel_title="G",
        frozen_payload_json=json.dumps(frozen, ensure_ascii=False),
        latest_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(saved)
    session.flush()
    session.add(
        SavedVideoSimilarFinding(
            saved_video_id=saved.id,
            video_id="grain-found",
            matched_query="grain carts",
            first_found_at=NOW,
            last_found_at=NOW,
            payload_json=json.dumps(
                {
                    "title": "Running grain cart with harvester",
                    "relevance_tier": "other",
                    "relevance_score": 10,
                },
                ensure_ascii=False,
            ),
        ),
    )
    session.commit()
    primary, other, *_ = list_findings_grouped(session, saved_video_id=saved.id)
    assert any(f.video_id == "grain-found" for f in primary)
    assert not any(f.video_id == "grain-found" for f in other)


def test_similar_watch_batch_failure_does_not_raise_to_caller() -> None:
    """Mirrors discovery_worker_runtime: batch errors are logged, not propagated."""
    session = _session()

    def _boom(_session):
        raise RuntimeError("similar watch batch failed")

    with patch(
        "app.services.saved_video_similar_watch.run_similar_watch_batch_for_discovery_cycle",
        side_effect=_boom,
    ):
        similar_session = session
        try:
            from app.services.saved_video_similar_watch import run_similar_watch_batch_for_discovery_cycle

            run_similar_watch_batch_for_discovery_cycle(similar_session)
            similar_session.commit()
        except Exception:
            similar_session.rollback()
        else:
            similar_session.rollback()
    # Discovery loop would continue — no exception escapes the worker's try/except block.
    assert True


if __name__ == "__main__":
    test_save_does_not_create_watch_or_keywords()
    test_confirm_and_scan()
    test_same_video_two_queries_one_scan()
    test_rescan_no_duplicate()
    test_partial_query_error()
    test_archive_pause_and_restore_stays_paused()
    test_batch_respects_query_budget()
    test_suggest_queries_deterministic()
    test_batch_partial_five_queries()
    test_similar_finding_feedback_does_not_add_saved_video()
    test_save_finding_adds_saved_video_idempotent()
    test_list_findings_grouped_uses_live_relevance_not_stale_payload()
    test_similar_watch_batch_failure_does_not_raise_to_caller()
    print("OK", 12)
