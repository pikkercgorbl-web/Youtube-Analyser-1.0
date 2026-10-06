"""Shared keyword expansion configuration and helpers (Stage 1.16C / 1.20C)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import KeywordExpansionEvent
from app.services.metrics import ensure_utc, utc_now
from app.services.keyword_scheduling_policy import SOURCE_CHANNEL, SOURCE_RELATED, SOURCE_SUGGESTION


@dataclass
class KeywordExpansionConfig:
    max_candidates_per_source_per_seed: int = 20
    max_new_keywords_per_seed_per_run: int = 10
    max_new_keywords_per_expansion_run: int = 50
    cooldown_days: float = 7.0
    expand_weak: bool = False
    max_seeds_per_batch: int = 10
    source_types: tuple[str, ...] = (SOURCE_SUGGESTION, SOURCE_RELATED, SOURCE_CHANNEL)


def generate_expansion_run_id(*, now: datetime | None = None) -> str:
    reference = now or utc_now()
    stamp = reference.strftime("%Y%m%dT%H%M%SZ")
    return f"expansion_{stamp}_{secrets.token_hex(4)}"


def is_source_on_cooldown(
    session: Session,
    *,
    parent_keyword_id: int,
    source_type: str,
    cooldown_days: float,
    now: datetime | None = None,
) -> bool:
    reference = now or utc_now()
    cutoff = reference - timedelta(days=cooldown_days)
    last_at = session.scalar(
        select(func.max(KeywordExpansionEvent.discovered_at)).where(
            KeywordExpansionEvent.parent_keyword_id == parent_keyword_id,
            KeywordExpansionEvent.source_type == source_type,
        ),
    )
    if last_at is None:
        return False
    return ensure_utc(last_at) > ensure_utc(cutoff)
