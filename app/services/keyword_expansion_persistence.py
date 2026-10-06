"""Persist keyword expansion outcomes (Stage 1.16C)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.orm import KeywordExpansionEvent, TargetKeyword
from app.services.keyword_admission_types import KeywordAdmissionDecision
from app.services.keyword_expansion_types import KeywordExpansionCandidate
from app.services.keyword_lifecycle_service import create_keyword, find_keyword_by_normalized, normalize_keyword_text
from app.services.keyword_scheduling_policy import LIFECYCLE_PROBATION
from app.services.metrics import utc_now


@dataclass(frozen=True, slots=True)
class ExpansionPersistOutcome:
    outcome: str
    keyword_id: int | None = None


def record_expansion_event(
    session: Session,
    *,
    parent_keyword_id: int,
    candidate: KeywordExpansionCandidate,
    outcome: str,
    created_keyword_id: int | None = None,
    rejection_reason: str | None = None,
    discovery_run_id: str | None = None,
    discovered_at: datetime | None = None,
) -> None:
    """Outcome: created | existing | rejected | deferred (Stage 1.20C). rejection_reason stores machine reason_code."""
    session.add(
        KeywordExpansionEvent(
            parent_keyword_id=parent_keyword_id,
            candidate_text=candidate.keyword,
            normalized_candidate=candidate.normalized_keyword,
            source_type=candidate.source_type,
            discovered_at=discovered_at or candidate.discovered_at or utc_now(),
            outcome=outcome,
            created_keyword_id=created_keyword_id,
            rejection_reason=rejection_reason,
            discovery_run_id=discovery_run_id,
        ),
    )
    session.flush()


def persist_expansion_candidate(
    session: Session,
    candidate: KeywordExpansionCandidate,
    *,
    parent_keyword: str,
    discovery_run_id: str | None = None,
    dry_run: bool = False,
) -> ExpansionPersistOutcome:
    normalized = normalize_keyword_text(candidate.keyword)
    existing = find_keyword_by_normalized(session, normalized)
    if existing is not None:
        if not dry_run:
            record_expansion_event(
                session,
                parent_keyword_id=candidate.parent_keyword_id,
                candidate=candidate,
                outcome="existing",
                created_keyword_id=existing.id,
                discovery_run_id=discovery_run_id,
            )
        return ExpansionPersistOutcome(outcome="existing", keyword_id=existing.id)

    if dry_run:
        return ExpansionPersistOutcome(outcome="created", keyword_id=None)

    reason = f"discovered via {candidate.source_type} from keyword {parent_keyword!r}"
    created = create_keyword(
        session,
        normalized,
        source_type=candidate.source_type,
        parent_keyword_id=candidate.parent_keyword_id,
        lifecycle_status=LIFECYCLE_PROBATION,
        status_reason=reason,
    )
    record_expansion_event(
        session,
        parent_keyword_id=candidate.parent_keyword_id,
        candidate=candidate,
        outcome="created",
        created_keyword_id=created.id,
        discovery_run_id=discovery_run_id,
    )
    return ExpansionPersistOutcome(outcome="created", keyword_id=created.id)


def persist_admission_decision(
    session: Session,
    decision: KeywordAdmissionDecision,
    candidate: KeywordExpansionCandidate,
    *,
    parent_keyword: str,
    discovery_run_id: str | None = None,
    dry_run: bool = False,
) -> ExpansionPersistOutcome:
    """Apply admission decision: write audit row; create keyword only on accept."""
    if decision.decision == "accept":
        if dry_run:
            return ExpansionPersistOutcome(outcome="created", keyword_id=None)
        reason = f"discovered via {candidate.source_type} from keyword {parent_keyword!r}"
        created = create_keyword(
            session,
            decision.normalized_keyword,
            source_type=candidate.source_type,
            parent_keyword_id=candidate.parent_keyword_id,
            lifecycle_status=LIFECYCLE_PROBATION,
            status_reason=reason,
        )
        record_expansion_event(
            session,
            parent_keyword_id=candidate.parent_keyword_id,
            candidate=candidate,
            outcome="created",
            created_keyword_id=created.id,
            rejection_reason=decision.reason_code,
            discovery_run_id=discovery_run_id,
        )
        return ExpansionPersistOutcome(outcome="created", keyword_id=created.id)

    if decision.decision == "existing":
        if not dry_run:
            record_expansion_event(
                session,
                parent_keyword_id=candidate.parent_keyword_id,
                candidate=candidate,
                outcome="existing",
                created_keyword_id=decision.existing_keyword_id,
                rejection_reason=decision.reason_code,
                discovery_run_id=discovery_run_id,
            )
        return ExpansionPersistOutcome(outcome="existing", keyword_id=decision.existing_keyword_id)

    if decision.decision == "defer":
        if not dry_run:
            record_expansion_event(
                session,
                parent_keyword_id=candidate.parent_keyword_id,
                candidate=candidate,
                outcome="deferred",
                rejection_reason=decision.reason_code,
                discovery_run_id=discovery_run_id,
            )
        return ExpansionPersistOutcome(outcome="deferred", keyword_id=None)

    if not dry_run:
        record_expansion_event(
            session,
            parent_keyword_id=candidate.parent_keyword_id,
            candidate=candidate,
            outcome="rejected",
            rejection_reason=decision.reason_code,
            discovery_run_id=discovery_run_id,
        )
    return ExpansionPersistOutcome(outcome="rejected", keyword_id=None)
