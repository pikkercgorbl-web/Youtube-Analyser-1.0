"""Novelty and frequency signals for exploration phrases (Stage 6)."""

from __future__ import annotations

from typing import Protocol

from app.services.topic_exploration_pass_fingerprint import exploration_pass_fingerprint_from_summaries
from app.services.topic_exploration_types import (
    TopicExplorationPhraseEvidence,
    TopicExplorationScanSummary,
)


class ExplorationObservationStore(Protocol):
    def ever_seen_exploration(self, normalized_phrase: str) -> bool: ...

    def latest_comparable_ok_pass(
        self,
        normalized_phrase: str,
        *,
        pass_fingerprint: str,
    ): ...


def exploration_pass_fingerprint(scans: tuple[TopicExplorationScanSummary, ...]) -> str:
    return exploration_pass_fingerprint_from_summaries(scans)


def attach_novelty_signals(
    evidence: TopicExplorationPhraseEvidence,
    *,
    store: ExplorationObservationStore,
    pass_fingerprint: str,
    cycle_fingerprint: str | None = None,
) -> TopicExplorationPhraseEvidence:
    """
    first_seen_exploration: first phrase stat in exploration tables (not global Radar).
    Frequency compare uses pass_fingerprint (query text, pages, settings, pass status).
    """
    signals: list[str] = []
    detail_parts: list[str] = []
    prior = store.latest_comparable_ok_pass(
        evidence.normalized_phrase,
        pass_fingerprint=pass_fingerprint,
    )
    current_v = evidence.support_video_count
    current_c = evidence.support_channel_count

    if not store.ever_seen_exploration(evidence.normalized_phrase):
        signals.append("first_seen_exploration")
        detail_parts.append("No prior phrase stat in exploration evidence (scope: exploration only).")

    if current_c >= 2:
        if prior is not None and prior.distinct_channel_count >= 2:
            signals.append("recurring_independent_channels")
        elif prior is not None and prior.distinct_channel_count < 2:
            detail_parts.append("Prior comparable pass had fewer than 2 channels.")

    prior_v: int | None = None
    if cycle_fingerprint and pass_fingerprint and cycle_fingerprint != pass_fingerprint:
        # cycle-level batch changed vs single-pass key — still compare on pass_fingerprint
        pass

    if prior is None:
        if store.ever_seen_exploration(evidence.normalized_phrase):
            signals.append("pass_not_comparable")
            detail_parts.append(
                f"No prior ok pass with fingerprint {pass_fingerprint!r}; "
                f"counts this pass: videos={current_v}, channels={current_c}."
            )
        else:
            signals.append("insufficient_history")
            detail_parts.append(
                f"No exploration history for comparable pass; videos={current_v}, channels={current_c}."
            )
    else:
        prior_v = prior.distinct_video_count
        if current_v > prior_v:
            signals.append("frequency_up_comparable_pass")
            detail_parts.append(f"Distinct videos up from {prior_v} to {current_v} (same pass fingerprint).")
        else:
            signals.append("no_growth_signal")
            detail_parts.append(f"Distinct videos {current_v} vs prior comparable {prior_v}.")

    detail = " ".join(detail_parts) if detail_parts else None
    return TopicExplorationPhraseEvidence(
        phrase=evidence.phrase,
        normalized_phrase=evidence.normalized_phrase,
        distinct_video_ids=evidence.distinct_video_ids,
        distinct_channel_ids=evidence.distinct_channel_ids,
        source_titles=evidence.source_titles,
        exploration_query_ids=evidence.exploration_query_ids,
        discovery_run_ids=evidence.discovery_run_ids,
        observation_window_start=evidence.observation_window_start,
        observation_window_end=evidence.observation_window_end,
        support_video_count=evidence.support_video_count,
        support_channel_count=evidence.support_channel_count,
        novelty_signals=tuple(signals),
        novelty_detail=detail,
        prior_pass_video_count=prior_v,
        current_pass_video_count=current_v,
    )
