"""Build exploration preview (read-only — no keywords/events)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.services.metrics import utc_now
from app.services.topic_exploration_mining import mine_phrases_from_hits
from app.services.topic_exploration_mining_config import TopicExplorationMiningConfig
from app.services.topic_exploration_novelty import attach_novelty_signals, exploration_pass_fingerprint
from app.services.topic_exploration_persisted_store import PersistedTopicExplorationObservationStore
from app.services.topic_exploration_types import (
    TopicExplorationPreview,
    TopicExplorationScanSummary,
)


def build_topic_exploration_preview(
    session: Session,
    *,
    discovery_run_id: str,
    exploration_scans: tuple[TopicExplorationScanSummary, ...],
    mining_config: TopicExplorationMiningConfig | None = None,
    record_phrase_stats: bool = False,
) -> TopicExplorationPreview:
    cfg = mining_config or TopicExplorationMiningConfig()
    store = PersistedTopicExplorationObservationStore(session)
    now = utc_now()
    window_end = now
    window_start = now - timedelta(hours=cfg.observation_window_hours)

    hits = [hit for scan in exploration_scans for hit in scan.title_hits]

    proposed, rejected = mine_phrases_from_hits(
        session,
        tuple(hits),
        window_start=window_start,
        window_end=window_end,
        config=cfg,
    )

    cycle_fp = exploration_pass_fingerprint(exploration_scans)
    enriched: list = []
    for row in proposed:
        pass_fp = row.discovery_run_ids[0] if row.discovery_run_ids else cycle_fp
        scan_for_phrase = next(
            (s for s in exploration_scans if s.discovery_run_id in row.discovery_run_ids),
            exploration_scans[0] if exploration_scans else None,
        )
        single_fp = scan_for_phrase.pass_fingerprint if scan_for_phrase and scan_for_phrase.pass_fingerprint else cycle_fp
        enriched.append(
            attach_novelty_signals(
                row,
                store=store,
                pass_fingerprint=single_fp,
                cycle_fingerprint=cycle_fp,
            ),
        )
        if record_phrase_stats and scan_for_phrase and scan_for_phrase.pass_id is not None:
            store.record_phrase_stat(
                pass_id=scan_for_phrase.pass_id,
                normalized_phrase=row.normalized_phrase,
                distinct_video_count=row.support_video_count,
                distinct_channel_count=row.support_channel_count,
                pass_fingerprint=single_fp,
                cycle_fingerprint=cycle_fp,
                exploration_query_id=scan_for_phrase.query_id,
                pass_discovery_run_id=scan_for_phrase.discovery_run_id,
                recorded_at=now,
                source_video_ids=list(row.distinct_video_ids),
                source_channel_ids=list(row.distinct_channel_ids),
            )

    return TopicExplorationPreview(
        discovery_run_id=discovery_run_id,
        generated_at=now,
        observation_window_hours=cfg.observation_window_hours,
        proposed=tuple(enriched),
        rejected=tuple(rejected),
        metadata={
            "cycle_fingerprint": cycle_fp,
            "exploration_scan_count": len(exploration_scans),
            "title_hit_count": len(hits),
            "first_seen_scope": "exploration_phrase_pass_stats",
        },
    )
