"""Admission path for exploration proposals (Stage 6 — auto off by default)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.keyword_admission_policy import AdmissionBudgetSnapshot, evaluate_keyword_admission
from app.services.keyword_expansion_persistence import persist_admission_decision
from app.services.keyword_expansion_types import KeywordExpansionCandidate
from app.services.keyword_scheduling_policy import SOURCE_EXPLORATION
from app.services.topic_exploration_types import TopicExplorationPhraseEvidence, TopicExplorationPreview


@dataclass(frozen=True, slots=True)
class TopicExplorationAdmitConfig:
    global_run_cap: int = 10
    parent_run_cap: int = 5


def _candidate_from_evidence(
    evidence: TopicExplorationPhraseEvidence,
    *,
    parent_keyword_id: int,
    parent_keyword: str,
) -> KeywordExpansionCandidate:
    return KeywordExpansionCandidate(
        keyword=evidence.phrase,
        normalized_keyword=evidence.normalized_phrase,
        source_type=SOURCE_EXPLORATION,
        parent_keyword_id=parent_keyword_id,
        parent_keyword=parent_keyword,
        source_reference=evidence.exploration_query_ids[0] if evidence.exploration_query_ids else None,
        metadata={
            "discovery_run_ids": list(evidence.discovery_run_ids),
            "video_ids": list(evidence.distinct_video_ids),
            "channel_ids": list(evidence.distinct_channel_ids),
        },
    )


def admit_topic_exploration_preview(
    session: Session,
    preview: TopicExplorationPreview,
    *,
    exploration_parent_by_query_id: dict[str, tuple[int, str]],
    config: TopicExplorationAdmitConfig | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """
    exploration_parent_by_query_id: maps exploration query_id -> (parent_keyword_id, parent_keyword text).
    Parent must exist in DB (operator anchor — example file is not auto-imported).
    """
    cfg = config or TopicExplorationAdmitConfig()
    admitted = 0
    errors: list[str] = []

    global_accepted = 0
    parent_accepted: dict[int, int] = {}

    from sqlalchemy import func, select

    from app.models.orm import TargetKeyword
    from app.services.keyword_scheduling_policy import LIFECYCLE_ARCHIVED, LIFECYCLE_PROBATION

    non_archived = (
        session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(TargetKeyword.lifecycle_status != LIFECYCLE_ARCHIVED),
        )
        or 0
    )
    probation = (
        session.scalar(
            select(func.count())
            .select_from(TargetKeyword)
            .where(TargetKeyword.lifecycle_status == LIFECYCLE_PROBATION),
        )
        or 0
    )

    for evidence in preview.proposed:
        query_id = evidence.exploration_query_ids[0] if evidence.exploration_query_ids else ""
        parent = exploration_parent_by_query_id.get(query_id)
        if parent is None:
            errors.append(f"no_parent_anchor_for_query:{query_id}")
            continue
        parent_id, parent_text = parent
        candidate = _candidate_from_evidence(
            evidence,
            parent_keyword_id=parent_id,
            parent_keyword=parent_text,
        )
        budgets = AdmissionBudgetSnapshot(
            global_accepted_this_run=global_accepted,
            global_run_cap=cfg.global_run_cap,
            parent_accepted_this_run=parent_accepted.get(parent_id, 0),
            parent_run_cap=cfg.parent_run_cap,
            non_archived_pool_count=int(non_archived),
            max_non_archived_pool_size=None,
            probation_pool_count=int(probation),
            max_probation_pool_size=None,
        )
        decision = evaluate_keyword_admission(
            session,
            candidate,
            parent_keyword=parent_text,
            budgets=budgets,
        )
        outcome = persist_admission_decision(
            session,
            decision,
            candidate,
            parent_keyword=parent_text,
            discovery_run_id=preview.discovery_run_id,
            dry_run=dry_run,
        )
        if outcome.outcome == "created":
            admitted += 1
            global_accepted += 1
            parent_accepted[parent_id] = parent_accepted.get(parent_id, 0) + 1
            if outcome.keyword_id is not None and evidence.discovery_run_ids:
                from app.services.topic_exploration_evidence_storage import link_phrase_stat_admission

                for run_id in evidence.discovery_run_ids:
                    link_phrase_stat_admission(
                        session,
                        pass_discovery_run_id=run_id,
                        normalized_phrase=evidence.normalized_phrase,
                        admitted_keyword_id=outcome.keyword_id,
                    )

    return admitted, errors
