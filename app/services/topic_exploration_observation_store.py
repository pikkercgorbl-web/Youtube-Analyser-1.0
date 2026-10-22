"""In-memory phrase observation history for novelty (Stage 6 — no prod schema change)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PhrasePassObservation:
    fingerprint: str
    distinct_video_count: int
    distinct_channel_count: int
    recorded_at: datetime


@dataclass
class TopicExplorationObservationStore:
    """Tracks prior pass stats per normalized phrase (optional persistence later)."""

    by_phrase: dict[str, list[PhrasePassObservation]] = field(default_factory=dict)

    def record_pass(
        self,
        normalized_phrase: str,
        *,
        fingerprint: str,
        distinct_video_count: int,
        distinct_channel_count: int,
        recorded_at: datetime,
    ) -> None:
        key = normalized_phrase.casefold()
        self.by_phrase.setdefault(key, []).append(
            PhrasePassObservation(
                fingerprint=fingerprint,
                distinct_video_count=distinct_video_count,
                distinct_channel_count=distinct_channel_count,
                recorded_at=recorded_at,
            ),
        )

    def latest_comparable(
        self,
        normalized_phrase: str,
        *,
        fingerprint: str,
    ) -> PhrasePassObservation | None:
        key = normalized_phrase.casefold()
        rows = self.by_phrase.get(key) or []
        for row in reversed(rows):
            if row.fingerprint == fingerprint:
                return row
        return None

    def ever_seen(self, normalized_phrase: str) -> bool:
        return normalized_phrase.casefold() in self.by_phrase

    def ever_seen_exploration(self, normalized_phrase: str) -> bool:
        return self.ever_seen(normalized_phrase)

    def latest_comparable_ok_pass(
        self,
        normalized_phrase: str,
        *,
        pass_fingerprint: str,
    ) -> PhrasePassObservation | None:
        return self.latest_comparable(normalized_phrase, fingerprint=pass_fingerprint)
