"""Persist exploration pass and video observations (Stage 6)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.orm import (
    TopicExplorationPass,
    TopicExplorationPhrasePassStat,
    TopicExplorationVideoObservation,
)
from app.services.metrics import utc_now
from app.services.topic_exploration_pass_fingerprint import single_pass_comparable_key
from app.services.topic_exploration_types import TopicExplorationScanSummary, TopicExplorationTitleHit


def persist_exploration_pass_evidence(
    session: Session,
    *,
    cycle_discovery_run_id: str,
    scan_summary: TopicExplorationScanSummary,
    settings_version: str,
    pages_requested: int,
) -> TopicExplorationPass:
    pages_scanned = int(scan_summary.max_pages)
    fingerprint = single_pass_comparable_key(
        query_id=scan_summary.query_id,
        query_text=scan_summary.query_text,
        pages_requested=pages_requested,
        pages_scanned=pages_scanned,
        settings_version=settings_version,
        status=scan_summary.status,
    )
    row = TopicExplorationPass(
        cycle_discovery_run_id=cycle_discovery_run_id,
        pass_discovery_run_id=scan_summary.discovery_run_id,
        exploration_query_id=scan_summary.query_id,
        exploration_query_text=scan_summary.query_text,
        observed_at=scan_summary.started_at,
        finished_at=scan_summary.finished_at,
        status=scan_summary.status,
        pages_requested=pages_requested,
        pages_scanned=pages_scanned,
        unique_videos_observed=len({h.video_id for h in scan_summary.title_hits}),
        settings_version=settings_version,
        pass_fingerprint=fingerprint,
        error_summary=scan_summary.errors[0] if scan_summary.errors else None,
    )
    session.add(row)
    session.flush()

    seen_videos: set[str] = set()
    for hit in scan_summary.title_hits:
        if hit.video_id in seen_videos:
            continue
        seen_videos.add(hit.video_id)
        session.add(
            TopicExplorationVideoObservation(
                pass_id=row.id,
                video_id=hit.video_id,
                channel_id=hit.channel_id,
                title=(hit.title or "")[:512],
                observed_at=hit.discovered_at,
            ),
        )
    session.flush()
    return row


def persist_phrase_pass_stats(
    session: Session,
    *,
    pass_row: TopicExplorationPass,
    cycle_fingerprint: str,
    proposed: tuple,
) -> None:
    now = utc_now()
    for evidence in proposed:
        session.add(
            TopicExplorationPhrasePassStat(
                pass_id=pass_row.id,
                normalized_phrase=evidence.normalized_phrase,
                distinct_video_count=evidence.support_video_count,
                distinct_channel_count=evidence.support_channel_count,
                pass_fingerprint=pass_row.pass_fingerprint,
                cycle_fingerprint=cycle_fingerprint,
                exploration_query_id=pass_row.exploration_query_id,
                recorded_at=now,
                source_video_ids_json=json.dumps(list(evidence.distinct_video_ids)),
                source_channel_ids_json=json.dumps(list(evidence.distinct_channel_ids)),
                pass_discovery_run_id=pass_row.pass_discovery_run_id,
            ),
        )
    session.flush()


def link_phrase_stat_admission(
    session: Session,
    *,
    pass_discovery_run_id: str,
    normalized_phrase: str,
    admitted_keyword_id: int,
) -> None:
    from sqlalchemy import select

    row = session.scalar(
        select(TopicExplorationPhrasePassStat)
        .where(
            TopicExplorationPhrasePassStat.pass_discovery_run_id == pass_discovery_run_id,
            TopicExplorationPhrasePassStat.normalized_phrase == normalized_phrase,
        )
        .order_by(TopicExplorationPhrasePassStat.id.desc())
        .limit(1),
    )
    if row is not None:
        row.admitted_keyword_id = admitted_keyword_id
        session.flush()
