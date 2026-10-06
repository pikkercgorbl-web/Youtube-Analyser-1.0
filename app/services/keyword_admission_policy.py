"""Keyword admission policy (Stage 1.20C). Structural and budget gates — not performance quality."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.orm import TargetKeyword
from app.services.keyword_admission_types import AdmissionContext, KeywordAdmissionDecision
from app.services.keyword_expansion_filter import reject_reason
from app.services.keyword_expansion_types import KeywordExpansionCandidate
from app.services.keyword_lifecycle_service import find_keyword_by_normalized, normalize_keyword_text
from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED

FILTER_REASON_TO_CODE: dict[str, str] = {
    "empty": "invalid_empty",
    "too_short": "filtered_noise",
    "too_long": "filtered_noise",
    "same_as_parent": "same_as_parent",
    "url_like": "filtered_noise",
    "numeric_only": "filtered_noise",
    "duplicate_in_batch": "duplicate_in_batch",
}


@dataclass(frozen=True, slots=True)
class AdmissionBudgetSnapshot:
    """Resource counters for defer-vs-reject (not evidence quality)."""

    global_accepted_this_run: int
    global_run_cap: int
    parent_accepted_this_run: int
    parent_run_cap: int
    non_archived_pool_count: int
    max_non_archived_pool_size: int | None
    probation_pool_count: int
    max_probation_pool_size: int | None


def _reject(
    candidate: KeywordExpansionCandidate,
    *,
    normalized: str,
    reason_code: str,
    human_reason: str,
    ctx: AdmissionContext | None = None,
) -> KeywordAdmissionDecision:
    return KeywordAdmissionDecision(
        normalized_keyword=normalized,
        decision="reject",
        reason_code=reason_code,
        human_reason=human_reason,
        source_type=candidate.source_type,
        parent_keyword_id=candidate.parent_keyword_id,
        admission_context=ctx or AdmissionContext(),
    )


def _defer(
    candidate: KeywordExpansionCandidate,
    *,
    normalized: str,
    reason_code: str,
    human_reason: str,
    ctx: AdmissionContext,
) -> KeywordAdmissionDecision:
    return KeywordAdmissionDecision(
        normalized_keyword=normalized,
        decision="defer",
        reason_code=reason_code,
        human_reason=human_reason,
        source_type=candidate.source_type,
        parent_keyword_id=candidate.parent_keyword_id,
        admission_context=ctx,
    )


def _existing(
    candidate: KeywordExpansionCandidate,
    *,
    normalized: str,
    existing: TargetKeyword,
    reason_code: str,
    human_reason: str,
) -> KeywordAdmissionDecision:
    return KeywordAdmissionDecision(
        normalized_keyword=normalized,
        decision="existing",
        reason_code=reason_code,
        human_reason=human_reason,
        source_type=candidate.source_type,
        parent_keyword_id=candidate.parent_keyword_id,
        existing_keyword_id=existing.id,
        admission_context=AdmissionContext(existing_lifecycle_status=existing.lifecycle_status),
    )


def _accept(candidate: KeywordExpansionCandidate, *, normalized: str) -> KeywordAdmissionDecision:
    return KeywordAdmissionDecision(
        normalized_keyword=normalized,
        decision="accept",
        reason_code="accepted",
        human_reason="Candidate passed admission checks",
        source_type=candidate.source_type,
        parent_keyword_id=candidate.parent_keyword_id,
    )


def evaluate_keyword_admission(
    session: Session,
    candidate: KeywordExpansionCandidate,
    *,
    parent_keyword: str,
    budgets: AdmissionBudgetSnapshot | None = None,
) -> KeywordAdmissionDecision:
    """
    Candidate-level admission (no expansion source I/O).
    Budget exhaustion yields defer, not reject.
    """
    normalized = normalize_keyword_text(candidate.keyword)
    parent_norm = normalize_keyword_text(parent_keyword).casefold()

    filter_candidate = candidate
    if candidate.normalized_keyword != normalized:
        filter_candidate = KeywordExpansionCandidate(
            keyword=candidate.keyword,
            normalized_keyword=normalized,
            source_type=candidate.source_type,
            parent_keyword_id=candidate.parent_keyword_id,
            parent_keyword=candidate.parent_keyword,
            source_reference=candidate.source_reference,
            discovered_at=candidate.discovered_at,
            confidence_hint=candidate.confidence_hint,
            metadata=candidate.metadata,
        )

    reason = reject_reason(filter_candidate, parent_normalized=parent_norm)
    if reason:
        code = FILTER_REASON_TO_CODE.get(reason, "filtered_noise")
        return _reject(
            candidate,
            normalized=normalized,
            reason_code=code,
            human_reason=f"Filter rejected candidate: {reason}",
            ctx=AdmissionContext(filter_reason=reason),
        )

    existing = find_keyword_by_normalized(session, normalized)
    if existing is not None:
        if existing.lifecycle_status == LIFECYCLE_ARCHIVED:
            return _existing(
                candidate,
                normalized=normalized,
                existing=existing,
                reason_code="existing_archived",
                human_reason="Keyword already exists in archived state; no automatic reactivation",
            )
        return _existing(
            candidate,
            normalized=normalized,
            existing=existing,
            reason_code="existing_keyword",
            human_reason="Keyword already exists in pool",
        )

    if budgets is not None:
        ctx = AdmissionContext(
            pool_non_archived_count=budgets.non_archived_pool_count,
            pool_probation_count=budgets.probation_pool_count,
            parent_accepted_this_run=budgets.parent_accepted_this_run,
            global_accepted_this_run=budgets.global_accepted_this_run,
        )
        if budgets.global_accepted_this_run >= budgets.global_run_cap:
            return _defer(
                candidate,
                normalized=normalized,
                reason_code="global_budget_exhausted",
                human_reason="Global expansion run acceptance cap reached",
                ctx=ctx,
            )
        if budgets.parent_accepted_this_run >= budgets.parent_run_cap:
            return _defer(
                candidate,
                normalized=normalized,
                reason_code="parent_budget_exhausted",
                human_reason="Per-parent acceptance cap reached for this run",
                ctx=ctx,
            )
        if (
            budgets.max_non_archived_pool_size is not None
            and budgets.non_archived_pool_count >= budgets.max_non_archived_pool_size
        ):
            return _defer(
                candidate,
                normalized=normalized,
                reason_code="pool_budget_exhausted",
                human_reason="Non-archived pool size cap reached",
                ctx=ctx,
            )
        if (
            budgets.max_probation_pool_size is not None
            and budgets.probation_pool_count >= budgets.max_probation_pool_size
        ):
            return _defer(
                candidate,
                normalized=normalized,
                reason_code="probation_budget_exhausted",
                human_reason="Probation pool size cap reached",
                ctx=ctx,
            )

    return _accept(candidate, normalized=normalized)
