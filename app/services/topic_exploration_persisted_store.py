"""DB-backed exploration phrase history for novelty (Stage 6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import TopicExplorationPass, TopicExplorationPhrasePassStat
from app.services.topic_exploration_observation_store import PhrasePassObservation


class PersistedTopicExplorationObservationStore:
    """
    Scope: exploration phrase pass stats only (not whole Radar, not TargetKeyword pool).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def ever_seen_exploration(self, normalized_phrase: str) -> bool:
        key = normalized_phrase.casefold()
        row = self._session.scalar(
            select(TopicExplorationPhrasePassStat.id)
            .where(TopicExplorationPhrasePassStat.normalized_phrase == key)
            .limit(1),
        )
        return row is not None

    def latest_comparable_ok_pass(
        self,
        normalized_phrase: str,
        *,
        pass_fingerprint: str,
    ) -> PhrasePassObservation | None:
        key = normalized_phrase.casefold()
        row = self._session.execute(
            select(
                TopicExplorationPhrasePassStat,
                TopicExplorationPass.status,
            )
            .join(TopicExplorationPass, TopicExplorationPass.id == TopicExplorationPhrasePassStat.pass_id)
            .where(
                TopicExplorationPhrasePassStat.normalized_phrase == key,
                TopicExplorationPhrasePassStat.pass_fingerprint == pass_fingerprint,
                TopicExplorationPass.status == "ok",
            )
            .order_by(TopicExplorationPhrasePassStat.recorded_at.desc())
            .limit(1),
        ).first()
        if row is None:
            return None
        stat, _status = row
        return PhrasePassObservation(
            fingerprint=stat.pass_fingerprint,
            distinct_video_count=stat.distinct_video_count,
            distinct_channel_count=stat.distinct_channel_count,
            recorded_at=stat.recorded_at,
        )

    def record_phrase_stat(
        self,
        *,
        pass_id: int,
        normalized_phrase: str,
        distinct_video_count: int,
        distinct_channel_count: int,
        pass_fingerprint: str,
        cycle_fingerprint: str,
        exploration_query_id: str,
        pass_discovery_run_id: str,
        recorded_at: datetime,
        source_video_ids: list[str],
        source_channel_ids: list[str],
    ) -> None:
        import json

        self._session.add(
            TopicExplorationPhrasePassStat(
                pass_id=pass_id,
                normalized_phrase=normalized_phrase.casefold(),
                distinct_video_count=distinct_video_count,
                distinct_channel_count=distinct_channel_count,
                pass_fingerprint=pass_fingerprint,
                cycle_fingerprint=cycle_fingerprint,
                exploration_query_id=exploration_query_id,
                recorded_at=recorded_at,
                source_video_ids_json=json.dumps(source_video_ids),
                source_channel_ids_json=json.dumps(source_channel_ids),
                pass_discovery_run_id=pass_discovery_run_id,
            ),
        )
        self._session.flush()
