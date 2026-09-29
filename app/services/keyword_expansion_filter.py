"""Shared filtering for keyword expansion candidates (Stage 1.16C)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.services.keyword_expansion_types import KeywordExpansionCandidate
from app.services.keyword_lifecycle_service import find_keyword_by_normalized, normalize_keyword_text

_URL_LIKE = re.compile(r"^https?://|^www\.", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class KeywordExpansionFilterConfig:
    min_length: int = 3
    max_length: int = 120


def reject_reason(
    candidate: KeywordExpansionCandidate,
    *,
    parent_normalized: str,
    config: KeywordExpansionFilterConfig | None = None,
) -> str | None:
    cfg = config or KeywordExpansionFilterConfig()
    text = candidate.normalized_keyword
    if not text:
        return "empty"
    if len(text) < cfg.min_length:
        return "too_short"
    if len(text) > cfg.max_length:
        return "too_long"
    if text.casefold() == parent_normalized.casefold():
        return "same_as_parent"
    if _URL_LIKE.search(candidate.keyword.strip()):
        return "url_like"
    if text.isdigit():
        return "numeric_only"
    return None


def filter_candidates(
    candidates: list[KeywordExpansionCandidate],
    *,
    parent_keyword: str,
    config: KeywordExpansionFilterConfig | None = None,
) -> tuple[list[KeywordExpansionCandidate], list[tuple[KeywordExpansionCandidate, str]]]:
    parent_norm = normalize_keyword_text(parent_keyword).casefold()
    seen: set[str] = set()
    accepted: list[KeywordExpansionCandidate] = []
    rejected: list[tuple[KeywordExpansionCandidate, str]] = []

    for candidate in candidates:
        norm = normalize_keyword_text(candidate.keyword).casefold()
        if norm in seen:
            rejected.append((candidate, "duplicate_in_batch"))
            continue
        seen.add(norm)
        reason = reject_reason(
            KeywordExpansionCandidate(
                keyword=candidate.keyword,
                normalized_keyword=normalize_keyword_text(candidate.keyword),
                source_type=candidate.source_type,
                parent_keyword_id=candidate.parent_keyword_id,
                parent_keyword=candidate.parent_keyword,
                source_reference=candidate.source_reference,
                discovered_at=candidate.discovered_at,
                confidence_hint=candidate.confidence_hint,
                metadata=candidate.metadata,
            ),
            parent_normalized=parent_norm,
            config=config,
        )
        if reason:
            rejected.append((candidate, reason))
            continue
        accepted.append(candidate)
    return accepted, rejected


def is_existing_keyword(session: Session, normalized: str) -> bool:
    return find_keyword_by_normalized(session, normalized) is not None
