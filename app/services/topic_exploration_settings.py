"""Version hash for exploration pass comparability (Stage 6)."""

from __future__ import annotations

import hashlib
import json

from app.services.topic_exploration_mining_config import TopicExplorationMiningConfig


def compute_exploration_settings_version(
    *,
    mining_config: TopicExplorationMiningConfig,
    max_pages_per_query: int,
    exploration_batch_fraction: float,
    register_explosive_channels: bool,
) -> str:
    payload = {
        "mining": {
            "min_distinct_videos": mining_config.min_distinct_videos,
            "min_distinct_channels": mining_config.min_distinct_channels,
            "observation_window_hours": mining_config.observation_window_hours,
            "min_ngram": mining_config.min_ngram,
            "max_ngram": mining_config.max_ngram,
        },
        "max_pages_per_query": max_pages_per_query,
        "exploration_batch_fraction": exploration_batch_fraction,
        "register_explosive_channels": register_explosive_channels,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
