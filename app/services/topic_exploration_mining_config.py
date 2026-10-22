"""Mining thresholds — starting hypotheses for calibration (Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TopicExplorationMiningConfig:
    """
    Starting values (hypotheses):
    - min_distinct_videos=2: phrase must appear in at least two different videos.
    - min_distinct_channels=2: those videos must span at least two channels (one channel cannot inflate support).
    - observation_window_hours=168: one week window for novelty comparisons.
    """

    min_distinct_videos: int = 2
    min_distinct_channels: int = 2
    observation_window_hours: int = 168
    min_ngram: int = 1
    max_ngram: int = 4


GENERIC_EXPLORATION_PHRASES = frozenset(
    {
        "how to",
        "how to play",
        "gameplay",
        "walkthrough",
        "let s play",
        "lets play",
        "full game",
        "no commentary",
        "part 1",
        "episode 1",
        "official trailer",
        "new update",
        "best settings",
        "tips and tricks",
        "review",
        "gaming",
        "video game",
        "playthrough",
    },
)
