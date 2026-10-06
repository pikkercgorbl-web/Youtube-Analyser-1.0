"""Attention Engine persist FK ordering (Stage 1.22A fix)."""

from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.orm  # noqa: F401
from app.models.db import Base
from app.models.orm import (
    AttentionChannelMomentumRow,
    AttentionPatternRow,
    AttentionPatternVideoRow,
    AttentionRun,
    AttentionVideoWinnerRow,
)
from app.services.attention_engine_types import (
    AttentionEngineResult,
    AttentionSummary,
    ChannelMomentum,
    PatternCandidate,
    VideoWinner,
    youtube_watch_url,
)
from app.services.attention_read_model import persist_attention_result, refresh_attention_engine

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _session():
    return sessionmaker(bind=_engine())()


def _winner(video_id: str = "vid-a") -> VideoWinner:
    return VideoWinner(
        video_id=video_id,
        title="Title",
        channel_id="ch-a",
        channel_title="Channel A",
        youtube_url=youtube_watch_url(video_id),
        published_at=NOW,
        age_hours=12.0,
        views=1000,
        vph=80.0,
        subscribers=None,
        breakout_rank=1,
        breakout_eligible=True,
        channel_relative_signal=None,
        acceleration_state="unavailable",
        delayed_outcome_state="pending",
        delayed_outcome_growth=None,
        reason_codes=("breakout_high_rank",),
        human_reasons=("breakout_v1 rank 1",),
        keyword_ids=(1,),
    )


def _pattern() -> PatternCandidate:
    return PatternCandidate(
        pattern_key="phrase:abcd",
        kind="title_phrase",
        label="ai npc",
        video_count=2,
        channel_count=2,
        keyword_count=1,
        breakout_video_count=1,
        small_channel_winner_count=0,
        first_seen_at=NOW,
        latest_seen_at=NOW,
        videos_last_24h=2,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        participating_video_ids=("vid-a", "vid-b"),
        participating_channel_ids=("ch-a", "ch-b"),
        participating_keyword_ids=(1,),
        reason_codes=("multi_video_evidence", "channel_diversity"),
        human_reasons=("2 related videos", "2 independent channels"),
    )


def _channel() -> ChannelMomentum:
    return ChannelMomentum(
        channel_id="ch-a",
        channel_title="Channel A",
        subscriber_count_latest=None,
        observed_video_count=4,
        recent_video_count=2,
        previous_video_count=2,
        breakout_video_count=2,
        confirmed_72h_count=0,
        recent_median_vph=10.0,
        previous_median_vph=4.0,
        recent_median_vph_vs_previous=2.5,
        subscriber_growth_absolute=None,
        subscriber_growth_pct=None,
        subscriber_growth_available=False,
        first_observed_at=NOW,
        latest_observed_at=NOW,
        representative_video_ids=("vid-a",),
        reason_codes=("content_momentum",),
        human_reasons=("recent median VPH above previous",),
        recent_window_days=7,
        previous_window_days=7,
    )


def _result(*, run_id: str, stamp: datetime = NOW) -> AttentionEngineResult:
    winners = (_winner(),)
    patterns = (_pattern(),)
    channels = (_channel(),)
    return AttentionEngineResult(
        summary=AttentionSummary(
            run_id=run_id,
            computed_at=stamp,
            timezone_name="UTC",
            window_hours=24,
            window_start=stamp,
            window_end=stamp,
            source="snapshot",
            candidate_video_count=2,
            winner_count=1,
            pattern_count=1,
            channel_momentum_count=1,
            video_limit=50,
            pattern_limit=20,
            channel_limit=20,
            notes={},
        ),
        video_winners=winners,
        patterns=patterns,
        channels=channels,
    )


def _insert_order(session) -> list[str]:
    order: list[str] = []
    engine = session.get_bind()

    def before(_conn, _cursor, statement, *_a, **_k) -> None:
        text = " ".join(str(statement).split()).lower()
        if not text.startswith("insert"):
            return
        for table in (
            "attention_runs",
            "attention_video_winners",
            "attention_patterns",
            "attention_pattern_videos",
            "attention_channel_momentum",
        ):
            if f"insert into {table}" in text:
                order.append(table)

    event.listen(engine, "before_cursor_execute", before)
    return order


def test_parent_insert_before_pattern_children() -> None:
    session = _session()
    order = _insert_order(session)
    persist_attention_result(session, _result(run_id="attention_a"), run_id="attention_a")
    session.commit()
    assert "attention_runs" in order
    assert "attention_patterns" in order
    assert order.index("attention_runs") < order.index("attention_patterns")
    assert order.index("attention_runs") < order.index("attention_video_winners")
    assert order.index("attention_runs") < order.index("attention_pattern_videos")
    assert order.index("attention_runs") < order.index("attention_channel_momentum")


def test_winners_patterns_videos_channels_fk() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="attention_fk"), run_id="attention_fk")
    session.commit()
    run = session.get(AttentionRun, "attention_fk")
    assert run is not None
    winners = list(session.scalars(select(AttentionVideoWinnerRow)).all())
    patterns = list(session.scalars(select(AttentionPatternRow)).all())
    members = list(session.scalars(select(AttentionPatternVideoRow)).all())
    channels = list(session.scalars(select(AttentionChannelMomentumRow)).all())
    assert winners and all(row.run_id == "attention_fk" for row in winners)
    assert patterns and all(row.run_id == "attention_fk" for row in patterns)
    assert members and all(row.run_id == "attention_fk" for row in members)
    assert channels and all(row.run_id == "attention_fk" for row in channels)


def test_refresh_all_families_succeeds() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="attention_all"), run_id="attention_all")
    session.commit()
    assert session.get(AttentionRun, "attention_all") is not None
    assert session.scalar(select(AttentionVideoWinnerRow).limit(1)) is not None
    assert session.scalar(select(AttentionPatternRow).limit(1)) is not None
    assert session.scalar(select(AttentionPatternVideoRow).limit(1)) is not None
    assert session.scalar(select(AttentionChannelMomentumRow).limit(1)) is not None


def test_child_failure_rolls_back_new_snapshot() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="attention_keep"), run_id="attention_keep")
    session.commit()

    flushes = {"n": 0}
    original = session.flush

    def boom() -> None:
        flushes["n"] += 1
        if flushes["n"] >= 3:
            raise RuntimeError("child persist failed")
        original()

    with patch.object(session, "flush", boom):
        try:
            persist_attention_result(
                session,
                _result(run_id="attention_new", stamp=datetime(2026, 10, 2, tzinfo=UTC)),
                run_id="attention_new",
            )
            raise AssertionError("expected child failure")
        except RuntimeError:
            session.rollback()

    assert session.get(AttentionRun, "attention_keep") is not None
    assert session.get(AttentionRun, "attention_new") is None
    assert session.scalar(select(AttentionPatternRow)).run_id == "attention_keep"


def test_second_refresh_replaces_snapshot() -> None:
    session = _session()
    persist_attention_result(session, _result(run_id="attention_old"), run_id="attention_old")
    session.commit()
    persist_attention_result(
        session,
        _result(run_id="attention_new", stamp=datetime(2026, 10, 2, tzinfo=UTC)),
        run_id="attention_new",
    )
    session.commit()
    runs = list(session.scalars(select(AttentionRun)).all())
    assert [row.run_id for row in runs] == ["attention_new"]
    assert session.scalar(select(AttentionVideoWinnerRow)).run_id == "attention_new"
    assert session.scalar(select(AttentionPatternRow)).run_id == "attention_new"


def test_helper_does_not_commit_or_rollback() -> None:
    persist_src = inspect.getsource(persist_attention_result)
    refresh_src = inspect.getsource(refresh_attention_engine)
    assert "commit(" not in persist_src
    assert "rollback(" not in persist_src
    assert "commit(" not in refresh_src
    assert "rollback(" not in refresh_src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("Passed FK persist tests")
