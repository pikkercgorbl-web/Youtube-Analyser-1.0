"""DTOs for topic exploration (Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

NoveltySignal = Literal[
    "first_seen_exploration",
    "recurring_independent_channels",
    "frequency_up_comparable_pass",
    "insufficient_history",
    "scan_volume_not_comparable",
    "pass_not_comparable",
    "no_growth_signal",
]


@dataclass(frozen=True, slots=True)
class TopicExplorationTitleHit:
    video_id: str
    channel_id: str | None
    title: str
    exploration_query_id: str
    exploration_query_text: str
    discovery_run_id: str
    discovered_at: datetime
    video_topic: str | None = None


@dataclass(frozen=True, slots=True)
class TopicExplorationScanSummary:
    query_id: str
    query_text: str
    discovery_run_id: str
    started_at: datetime
    finished_at: datetime
    max_pages: int
    title_hits: tuple[TopicExplorationTitleHit, ...] = ()
    status: Literal["ok", "failed"] = "ok"
    errors: tuple[str, ...] = ()
    pages_requested: int = 0
    pages_scanned: int = 0
    settings_version: str = ""
    pass_fingerprint: str = ""
    pass_id: int | None = None


@dataclass(frozen=True, slots=True)
class TopicExplorationPhraseEvidence:
    phrase: str
    normalized_phrase: str
    distinct_video_ids: tuple[str, ...]
    distinct_channel_ids: tuple[str, ...]
    source_titles: tuple[str, ...]
    exploration_query_ids: tuple[str, ...]
    discovery_run_ids: tuple[str, ...]
    observation_window_start: datetime
    observation_window_end: datetime
    support_video_count: int
    support_channel_count: int
    novelty_signals: tuple[NoveltySignal, ...] = ()
    novelty_detail: str | None = None
    prior_pass_video_count: int | None = None
    current_pass_video_count: int | None = None


@dataclass(frozen=True, slots=True)
class TopicExplorationRejectedPhrase:
    phrase: str
    normalized_phrase: str
    reason_code: str
    human_reason: str
    evidence: TopicExplorationPhraseEvidence | None = None


@dataclass
class TopicExplorationPreview:
    discovery_run_id: str
    generated_at: datetime
    observation_window_hours: int
    proposed: tuple[TopicExplorationPhraseEvidence, ...] = ()
    rejected: tuple[TopicExplorationRejectedPhrase, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TopicExplorationPassContext:
    discovery_run_id: str
    exploration_scans: tuple[TopicExplorationScanSummary, ...] = ()
    comparable_pass_fingerprint: str | None = None


@dataclass
class TopicExplorationPassReport:
    discovery_run_id: str
    preview: TopicExplorationPreview | None = None
    admitted_count: int = 0
    errors: tuple[str, ...] = ()
