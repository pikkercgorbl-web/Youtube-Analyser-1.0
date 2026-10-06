"""Persist and read Attention Engine snapshots (Stage 1.22A)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.orm import (
    AttentionChannelMomentumRow,
    AttentionPatternFamilyMemberRow,
    AttentionPatternFamilyRow,
    AttentionPatternFamilyVideoRow,
    AttentionPatternRow,
    AttentionPatternVideoRow,
    AttentionRun,
    AttentionVideoWinnerRow,
)
from app.services.attention_engine_service import compute_attention_engine
from app.services.attention_engine_types import (
    AttentionEngineConfig,
    AttentionEngineResult,
    AttentionSummary,
    ChannelMomentum,
    PatternCandidate,
    PatternFamily,
    VideoWinner,
    attention_result_to_dict,
    channel_momentum_to_dict,
    pattern_family_to_dict,
    pattern_to_dict,
    video_winner_to_dict,
)
from app.services.attention_pattern_families import upsert_family_identity
from app.services.metrics import ensure_utc, utc_now

AttentionReadSource = Literal["snapshot", "live_compute", "unavailable"]


def _run_id(reference: datetime) -> str:
    return f"attention_{ensure_utc(reference).strftime('%Y%m%dT%H%M%SZ')}"


def get_latest_attention_run(session: Session) -> AttentionRun | None:
    return session.scalar(
        select(AttentionRun).order_by(AttentionRun.computed_at.desc(), AttentionRun.run_id.desc()).limit(1),
    )


def persist_attention_result(session: Session, result: AttentionEngineResult, *, run_id: str) -> None:
    """
    Replace the Attention snapshot.

    Caller owns commit/rollback. This helper only add/flush.

    Parent ``attention_runs`` is flushed before any child INSERT. Child mappers
    have no relationship() to AttentionRun, so a single mixed flush can INSERT
    patterns before the parent row exists (Postgres FK violation).
    """
    session.execute(delete(AttentionPatternFamilyVideoRow))
    session.execute(delete(AttentionPatternFamilyMemberRow))
    session.execute(delete(AttentionPatternFamilyRow))
    session.execute(delete(AttentionPatternVideoRow))
    session.execute(delete(AttentionVideoWinnerRow))
    session.execute(delete(AttentionPatternRow))
    session.execute(delete(AttentionChannelMomentumRow))
    session.execute(delete(AttentionRun))
    session.flush()

    summary = result.summary
    session.add(
        AttentionRun(
            run_id=run_id,
            computed_at=summary.computed_at,
            timezone_name=summary.timezone_name,
            window_hours=summary.window_hours,
            window_start=summary.window_start,
            window_end=summary.window_end,
            candidate_video_count=summary.candidate_video_count,
            winner_count=summary.winner_count,
            pattern_count=summary.pattern_count,
            channel_momentum_count=summary.channel_momentum_count,
            video_limit=summary.video_limit,
            pattern_limit=summary.pattern_limit,
            channel_limit=summary.channel_limit,
            notes_json=json.dumps(summary.notes),
        ),
    )
    session.flush()

    for rank, row in enumerate(result.video_winners, start=1):
        session.add(
            AttentionVideoWinnerRow(
                run_id=run_id,
                rank=rank,
                video_id=row.video_id,
                payload_json=json.dumps(video_winner_to_dict(row)),
            ),
        )
    for rank, row in enumerate(result.patterns, start=1):
        session.add(
            AttentionPatternRow(
                run_id=run_id,
                rank=rank,
                pattern_key=row.pattern_key,
                payload_json=json.dumps(pattern_to_dict(row)),
            ),
        )
        for video_id in row.participating_video_ids:
            session.add(
                AttentionPatternVideoRow(
                    run_id=run_id,
                    pattern_key=row.pattern_key,
                    video_id=video_id,
                ),
            )
    for rank, row in enumerate(result.channels, start=1):
        session.add(
            AttentionChannelMomentumRow(
                run_id=run_id,
                rank=rank,
                channel_id=row.channel_id,
                payload_json=json.dumps(channel_momentum_to_dict(row)),
            ),
        )
    for rank, row in enumerate(result.families, start=1):
        session.add(
            AttentionPatternFamilyRow(
                run_id=run_id,
                rank=rank,
                family_key=row.family_key,
                payload_json=json.dumps(pattern_family_to_dict(row)),
            ),
        )
        for pattern_key in row.member_pattern_keys:
            session.add(
                AttentionPatternFamilyMemberRow(
                    run_id=run_id,
                    family_key=row.family_key,
                    pattern_key=pattern_key,
                ),
            )
        for video_id in row.video_ids:
            session.add(
                AttentionPatternFamilyVideoRow(
                    run_id=run_id,
                    family_key=row.family_key,
                    video_id=video_id,
                ),
            )
    session.flush()
    mapping = {
        pattern_key: row.family_key
        for row in result.families
        for pattern_key in row.member_pattern_keys
    }
    if mapping:
        upsert_family_identity(session, mapping, now=summary.computed_at)


def refresh_attention_engine(
    session: Session,
    *,
    config: AttentionEngineConfig | None = None,
    now: datetime | None = None,
) -> AttentionEngineResult:
    cfg = config or AttentionEngineConfig()
    computed_at = ensure_utc(now or utc_now())
    run_id = _run_id(computed_at)
    result = compute_attention_engine(
        session,
        config=cfg,
        now=computed_at,
        source="snapshot",
        run_id=run_id,
    )
    persist_attention_result(session, result, run_id=run_id)
    return result


def _summary_from_run(row: AttentionRun, *, source: str) -> AttentionSummary:
    notes = json.loads(row.notes_json or "{}")
    return AttentionSummary(
        run_id=row.run_id,
        computed_at=ensure_utc(row.computed_at),
        timezone_name=row.timezone_name,
        window_hours=row.window_hours,
        window_start=ensure_utc(row.window_start),
        window_end=ensure_utc(row.window_end),
        source=source,
        candidate_video_count=row.candidate_video_count,
        winner_count=row.winner_count,
        pattern_count=row.pattern_count,
        channel_momentum_count=row.channel_momentum_count,
        video_limit=row.video_limit,
        pattern_limit=row.pattern_limit,
        channel_limit=row.channel_limit,
        notes=notes,
    )


def load_attention_snapshot(session: Session) -> AttentionEngineResult | None:
    run = get_latest_attention_run(session)
    if run is None:
        return None
    winners = session.scalars(
        select(AttentionVideoWinnerRow)
        .where(AttentionVideoWinnerRow.run_id == run.run_id)
        .order_by(AttentionVideoWinnerRow.rank.asc()),
    ).all()
    patterns = session.scalars(
        select(AttentionPatternRow)
        .where(AttentionPatternRow.run_id == run.run_id)
        .order_by(AttentionPatternRow.rank.asc()),
    ).all()
    channels = session.scalars(
        select(AttentionChannelMomentumRow)
        .where(AttentionChannelMomentumRow.run_id == run.run_id)
        .order_by(AttentionChannelMomentumRow.rank.asc()),
    ).all()
    families = session.scalars(
        select(AttentionPatternFamilyRow)
        .where(AttentionPatternFamilyRow.run_id == run.run_id)
        .order_by(AttentionPatternFamilyRow.rank.asc()),
    ).all()
    family_rows = tuple(_family_from_json(json.loads(row.payload_json)) for row in families)
    if not family_rows and patterns:
        from app.services.attention_pattern_families import build_pattern_families

        family_rows, _ = build_pattern_families(
            tuple(_pattern_from_json(json.loads(row.payload_json)) for row in patterns),
            now=ensure_utc(run.computed_at),
        )
        family_rows = tuple(family_rows)
    return AttentionEngineResult(
        summary=_summary_from_run(run, source="snapshot"),
        video_winners=tuple(_winner_from_json(json.loads(row.payload_json)) for row in winners),
        patterns=tuple(_pattern_from_json(json.loads(row.payload_json)) for row in patterns),
        channels=tuple(_channel_from_json(json.loads(row.payload_json)) for row in channels),
        families=family_rows,
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _family_from_json(payload: dict) -> PatternFamily:
    return PatternFamily(
        family_key=payload["family_key"],
        label=payload["label"],
        family_kind=payload["family_kind"],
        member_pattern_keys=tuple(payload.get("member_pattern_keys") or ()),
        member_labels=tuple(payload.get("member_labels") or ()),
        video_ids=tuple(payload.get("video_ids") or ()),
        channel_ids=tuple(payload.get("channel_ids") or ()),
        keyword_ids=tuple(int(x) for x in (payload.get("keyword_ids") or ())),
        video_count=int(payload["video_count"]),
        channel_count=int(payload["channel_count"]),
        keyword_count=int(payload["keyword_count"]),
        breakout_eligible_count=int(payload.get("breakout_eligible_count") or 0),
        videos_last_24h=int(payload.get("videos_last_24h") or 0),
        videos_previous_24h=int(payload.get("videos_previous_24h") or 0),
        videos_previous_48_24h=int(payload.get("videos_previous_48_24h") or 0),
        grouping_reasons=tuple(payload.get("grouping_reasons") or ()),
        quality_flags=tuple(payload.get("quality_flags") or ()),
        support_sources=tuple(payload.get("support_sources") or ()),
        first_seen_at=_parse_dt(payload.get("first_seen_at")),
        latest_seen_at=_parse_dt(payload.get("latest_seen_at")),
    )


def _winner_from_json(payload: dict) -> VideoWinner:
    from app.services.attention_engine_types import ChannelRelativeSignal

    rel = payload.get("channel_relative_signal")
    relative = None
    if rel:
        relative = ChannelRelativeSignal(
            status=rel["status"],
            baseline_quality=rel["baseline_quality"],
            comparable_video_count=int(rel["comparable_video_count"]),
            vph_vs_channel_median=rel.get("vph_vs_channel_median"),
            notes=tuple(rel.get("notes") or ()),
        )
    return VideoWinner(
        video_id=payload["video_id"],
        title=payload["title"],
        channel_id=payload["channel_id"],
        channel_title=payload["channel_title"],
        youtube_url=payload["youtube_url"],
        published_at=_parse_dt(payload.get("published_at")),
        age_hours=payload.get("age_hours"),
        views=payload.get("views"),
        vph=payload.get("vph"),
        subscribers=payload.get("subscribers"),
        breakout_rank=payload.get("breakout_rank"),
        breakout_eligible=bool(payload.get("breakout_eligible")),
        channel_relative_signal=relative,
        acceleration_state=payload["acceleration_state"],
        delayed_outcome_state=payload["delayed_outcome_state"],
        delayed_outcome_growth=payload.get("delayed_outcome_growth"),
        reason_codes=tuple(payload.get("reason_codes") or ()),
        human_reasons=tuple(payload.get("human_reasons") or ()),
        keyword_ids=tuple(payload.get("keyword_ids") or ()),
    )


def _pattern_from_json(payload: dict) -> PatternCandidate:
    return PatternCandidate(
        pattern_key=payload["pattern_key"],
        kind=payload["kind"],
        label=payload["label"],
        video_count=int(payload["video_count"]),
        channel_count=int(payload["channel_count"]),
        keyword_count=int(payload["keyword_count"]),
        breakout_video_count=int(payload["breakout_video_count"]),
        small_channel_winner_count=int(payload["small_channel_winner_count"]),
        first_seen_at=_parse_dt(payload.get("first_seen_at")),
        latest_seen_at=_parse_dt(payload.get("latest_seen_at")),
        videos_last_24h=int(payload["videos_last_24h"]),
        videos_previous_24h=int(payload["videos_previous_24h"]),
        videos_previous_48_24h=int(payload["videos_previous_48_24h"]),
        participating_video_ids=tuple(payload.get("participating_video_ids") or ()),
        participating_channel_ids=tuple(payload.get("participating_channel_ids") or ()),
        participating_keyword_ids=tuple(payload.get("participating_keyword_ids") or ()),
        reason_codes=tuple(payload.get("reason_codes") or ()),
        human_reasons=tuple(payload.get("human_reasons") or ()),
    )


def _channel_from_json(payload: dict) -> ChannelMomentum:
    return ChannelMomentum(
        channel_id=payload["channel_id"],
        channel_title=payload["channel_title"],
        subscriber_count_latest=payload.get("subscriber_count_latest"),
        observed_video_count=int(payload["observed_video_count"]),
        recent_video_count=int(payload["recent_video_count"]),
        previous_video_count=int(payload["previous_video_count"]),
        breakout_video_count=int(payload["breakout_video_count"]),
        confirmed_72h_count=int(payload["confirmed_72h_count"]),
        recent_median_vph=payload.get("recent_median_vph"),
        previous_median_vph=payload.get("previous_median_vph"),
        recent_median_vph_vs_previous=payload.get("recent_median_vph_vs_previous"),
        subscriber_growth_absolute=payload.get("subscriber_growth_absolute"),
        subscriber_growth_pct=payload.get("subscriber_growth_pct"),
        subscriber_growth_available=bool(payload.get("subscriber_growth_available")),
        first_observed_at=_parse_dt(payload.get("first_observed_at")),
        latest_observed_at=_parse_dt(payload.get("latest_observed_at")),
        representative_video_ids=tuple(payload.get("representative_video_ids") or ()),
        reason_codes=tuple(payload.get("reason_codes") or ()),
        human_reasons=tuple(payload.get("human_reasons") or ()),
        recent_window_days=int(payload["recent_window_days"]),
        previous_window_days=int(payload["previous_window_days"]),
    )


def snapshot_as_dict(session: Session) -> dict | None:
    result = load_attention_snapshot(session)
    if result is None:
        return None
    return attention_result_to_dict(result)
