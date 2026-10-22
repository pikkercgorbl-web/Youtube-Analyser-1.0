#!/usr/bin/env python3
"""Verify keyword expansion + topic exploration settings (no YouTube HTTP)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from migrate import load_dotenv


def main() -> int:
    load_dotenv(ROOT / ".env")
    from app.services.discovery_worker_runtime import DiscoveryWorkerConfig
    from app.services.keyword_expansion_runtime_config import keyword_expansion_runtime_settings
    from app.services.topic_exploration_batch_split import split_discovery_batch_slots
    from app.services.topic_exploration_cycle import build_topic_exploration_cycle_plan
    from app.services.topic_exploration_queries import load_topic_exploration_queries
    from app.services.topic_exploration_runtime_config import topic_exploration_runtime_settings

    db_url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(db_url) if db_url else None
    batch_size = max(1, DiscoveryWorkerConfig().keyword_batch_size)
    plan = build_topic_exploration_cycle_plan(topic_exploration_runtime_settings)
    seed_slots, exploration_slots = split_discovery_batch_slots(
        batch_size,
        exploration_enabled=plan.enabled,
        exploration_fraction=plan.batch_fraction,
    )
    queries_path = topic_exploration_runtime_settings.topic_exploration_queries_file
    loaded = []
    load_error = None
    if queries_path:
        try:
            qpath = Path(queries_path)
            if not qpath.is_absolute():
                qpath = ROOT / qpath
            loaded = list(load_topic_exploration_queries(qpath))
        except OSError as exc:
            load_error = str(exc)

    enabled_queries = [q for q in loaded if q.enabled]

    report = {
        "database": {
            "host": parsed.hostname if parsed else None,
            "port": parsed.port if parsed else None,
            "name": parsed.path.lstrip("/") if parsed and parsed.path else None,
        },
        "keyword_expansion_after_discovery": keyword_expansion_runtime_settings.keyword_expansion_after_discovery,
        "topic_exploration": {
            "in_discovery": topic_exploration_runtime_settings.topic_exploration_in_discovery,
            "queries_file": queries_path,
            "batch_fraction": topic_exploration_runtime_settings.topic_exploration_batch_fraction,
            "max_pages_per_query": topic_exploration_runtime_settings.topic_exploration_max_pages_per_query,
            "auto_admit": topic_exploration_runtime_settings.topic_exploration_auto_admit,
            "enabled_query_count": len(enabled_queries),
            "enabled_query_ids": [q.query_id for q in enabled_queries],
            "load_error": load_error,
        },
        "discovery_batch_plan": {
            "default_worker_batch_size": batch_size,
            "seed_keyword_slots": seed_slots,
            "exploration_query_slots": exploration_slots,
        },
        "note": "Read-only; secrets not printed.",
    }
    out = ROOT / "artifacts" / "stage6_local_enable_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if load_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
