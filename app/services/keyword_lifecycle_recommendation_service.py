"""Conservative advisory lifecycle recommendations (Stage 1.20D). Evidence-only; no lifecycle writes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.keyword_evidence_service import get_keyword_evidence, list_keyword_evidence
from app.services.keyword_evidence_types import KeywordEvidence
from app.services.keyword_lifecycle_recommendation_types import (
    KeywordLifecycleRecommendation,
    KeywordLifecycleRecommendationListResult,
    LifecycleRecommendationKind,
    RecommendationConfidence,
)
from app.services.keyword_performance_evaluation import AttributionMode
from app.services.keyword_scheduling_policy import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_PROBATION,
    LIFECYCLE_WEAK,
    PROBATION_READY_SCAN_COUNT,
)
# Stage 1.20A: strong transitions requiring calibrated thresholds stay disabled until 1.20E+.
_CALIBRATED_PROMOTE_PROBATION_TO_ACTIVE = False
_CALIBRATED_DEMOTE_PROBATION_TO_WEAK = False
_CALIBRATED_DEMOTE_ACTIVE_TO_WEAK = False
_CALIBRATED_PROMOTE_WEAK_TO_ACTIVE = False
_CALIBRATED_ARCHIVE = False
_CALIBRATED_RESTORE_ARCHIVED = False


def _fact(evidence: KeywordEvidence, line: str) -> str:
    return line


def _scan_ready(evidence: KeywordEvidence) -> bool:
    if evidence.scan.meta.availability == "unavailable":
        return False
    return evidence.scan.successful_scan_count >= PROBATION_READY_SCAN_COUNT


def _has_phase1_yield_signal(evidence: KeywordEvidence) -> bool:
    if evidence.discovery.meta.availability == "unavailable":
        return False
    return (
        evidence.discovery.new_to_database_video_count > 0
        or evidence.discovery.persisted_for_monitoring_count > 0
        or evidence.discovery.unique_discovered_video_count > 0
    )


def _insufficient(reason_code: str, human: str, evidence: KeywordEvidence) -> KeywordLifecycleRecommendation:
    return KeywordLifecycleRecommendation(
        keyword_id=evidence.keyword_id,
        keyword=evidence.keyword,
        lifecycle_status=evidence.lifecycle_status,
        recommendation="insufficient_evidence",
        confidence="none",
        reason_code=reason_code,
        human_reason=human,
        calibration_required=False,
        suggested_transition=None,
        evidence_facts=(),
        evaluated_at=evidence.evaluated_at,
    )


def _keep(
    evidence: KeywordEvidence,
    *,
    reason_code: str,
    human_reason: str,
    calibration_required: bool = False,
    facts: tuple[str, ...] = (),
) -> KeywordLifecycleRecommendation:
    return KeywordLifecycleRecommendation(
        keyword_id=evidence.keyword_id,
        keyword=evidence.keyword,
        lifecycle_status=evidence.lifecycle_status,
        recommendation="keep",
        confidence="none",
        reason_code=reason_code,
        human_reason=human_reason,
        calibration_required=calibration_required,
        suggested_transition=None,
        evidence_facts=facts,
        evaluated_at=evidence.evaluated_at,
    )


def _preliminary(
    evidence: KeywordEvidence,
    *,
    reason_code: str,
    human_reason: str,
    suggested_transition: str | None,
    calibration_required: bool,
    facts: tuple[str, ...],
) -> KeywordLifecycleRecommendation:
    return KeywordLifecycleRecommendation(
        keyword_id=evidence.keyword_id,
        keyword=evidence.keyword,
        lifecycle_status=evidence.lifecycle_status,
        recommendation="preliminary_review",
        confidence="preliminary",
        reason_code=reason_code,
        human_reason=human_reason,
        calibration_required=calibration_required,
        suggested_transition=suggested_transition,
        evidence_facts=facts,
        evaluated_at=evidence.evaluated_at,
    )


def _strong(
    evidence: KeywordEvidence,
    *,
    recommendation: LifecycleRecommendationKind,
    reason_code: str,
    human_reason: str,
    suggested_transition: str,
    facts: tuple[str, ...],
) -> KeywordLifecycleRecommendation:
    return KeywordLifecycleRecommendation(
        keyword_id=evidence.keyword_id,
        keyword=evidence.keyword,
        lifecycle_status=evidence.lifecycle_status,
        recommendation=recommendation,
        confidence="preliminary",
        reason_code=reason_code,
        human_reason=human_reason,
        calibration_required=False,
        suggested_transition=suggested_transition,
        evidence_facts=facts,
        evaluated_at=evidence.evaluated_at,
    )


def evaluate_lifecycle_recommendation(evidence: KeywordEvidence) -> KeywordLifecycleRecommendation:
    """
    Map Stage 1.20B evidence to a single advisory recommendation.
    Does not mutate lifecycle. Strong actions require calibrated rules (mostly disabled in 1.20D).
    """
    status = evidence.lifecycle_status
    ok_scans = evidence.scan.successful_scan_count
    facts: list[str] = [
        _fact(evidence, f"successful_scan_count={ok_scans}"),
        _fact(
            evidence,
            f"new_to_database_video_count={evidence.discovery.new_to_database_video_count}",
        ),
        _fact(
            evidence,
            f"persisted_for_monitoring_count={evidence.discovery.persisted_for_monitoring_count}",
        ),
    ]

    if status == LIFECYCLE_ARCHIVED:
        if _CALIBRATED_RESTORE_ARCHIVED:
            pass  # future calibrated restore
        return _keep(
            evidence,
            reason_code="archived_manual_restore",
            human_reason="Archived keywords stay archived unless operator restores manually (Stage 1.20A).",
            facts=tuple(facts),
        )

    if status == LIFECYCLE_ACTIVE:
        if _CALIBRATED_DEMOTE_ACTIVE_TO_WEAK and _scan_ready(evidence):
            return _strong(
                evidence,
                recommendation="move_weak",
                reason_code="active_to_weak_calibrated",
                human_reason="Calibrated yield demotion rule matched.",
                suggested_transition=f"{LIFECYCLE_ACTIVE}->{LIFECYCLE_WEAK}",
                facts=tuple(facts),
            )
        return _keep(
            evidence,
            reason_code="active_keep_calibration_pending",
            human_reason="Active scheduling retained; demotion thresholds are not calibrated for production (Stage 1.20A).",
            calibration_required=True,
            facts=tuple(facts),
        )

    if status == LIFECYCLE_WEAK:
        if _CALIBRATED_PROMOTE_WEAK_TO_ACTIVE and _scan_ready(evidence):
            return _strong(
                evidence,
                recommendation="promote_active",
                reason_code="weak_to_active_calibrated",
                human_reason="Calibrated recovery rule matched.",
                suggested_transition=f"{LIFECYCLE_WEAK}->{LIFECYCLE_ACTIVE}",
                facts=tuple(facts),
            )
        return _keep(
            evidence,
            reason_code="weak_keep_calibration_pending",
            human_reason="Weak scheduling retained; promotion thresholds are not calibrated (Stage 1.20A).",
            calibration_required=True,
            facts=tuple(facts),
        )

    if status == LIFECYCLE_PROBATION:
        if evidence.scan.meta.availability in ("unavailable", "insufficient") and ok_scans == 0:
            return _insufficient(
                "scan_evidence_missing",
                "Not enough scan observations to advise probation lifecycle.",
                evidence,
            )
        if ok_scans < PROBATION_READY_SCAN_COUNT:
            return _insufficient(
                "probation_min_scans",
                f"Fewer than {PROBATION_READY_SCAN_COUNT} successful scans; lifecycle advisory not ready.",
                evidence,
            )

        has_yield = _has_phase1_yield_signal(evidence)

        if _CALIBRATED_PROMOTE_PROBATION_TO_ACTIVE and has_yield:
            return _strong(
                evidence,
                recommendation="promote_active",
                reason_code="probation_to_active_calibrated",
                human_reason="Calibrated sustained-yield promotion rule matched.",
                suggested_transition=f"{LIFECYCLE_PROBATION}->{LIFECYCLE_ACTIVE}",
                facts=tuple(facts),
            )

        if _CALIBRATED_DEMOTE_PROBATION_TO_WEAK and not has_yield:
            return _strong(
                evidence,
                recommendation="move_weak",
                reason_code="probation_to_weak_calibrated",
                human_reason="Calibrated repeated zero-yield demotion rule matched.",
                suggested_transition=f"{LIFECYCLE_PROBATION}->{LIFECYCLE_WEAK}",
                facts=tuple(facts),
            )

        if has_yield:
            return _preliminary(
                evidence,
                reason_code="probation_yield_preliminary",
                human_reason=(
                    "Minimum successful scans met and Phase-1 yield signal present, but sustained-yield "
                    "promotion thresholds are CALIBRATION_REQUIRED (Stage 1.20A). Review only — no auto-promote."
                ),
                suggested_transition=f"{LIFECYCLE_PROBATION}->{LIFECYCLE_ACTIVE}",
                calibration_required=True,
                facts=tuple(facts),
            )

        return _preliminary(
            evidence,
            reason_code="probation_zero_yield_preliminary",
            human_reason=(
                "Minimum successful scans met but incremental yield is zero; consecutive zero-scan demotion "
                "rules are CALIBRATION_REQUIRED. Review only — no auto-demote."
            ),
            suggested_transition=f"{LIFECYCLE_PROBATION}->{LIFECYCLE_WEAK}",
            calibration_required=True,
            facts=tuple(facts),
        )

    if _CALIBRATED_ARCHIVE:
        pass

    return _keep(
        evidence,
        reason_code="unknown_status_keep",
        human_reason=f"No advisory rule for lifecycle status {status!r}; default keep.",
        facts=tuple(facts),
    )


def list_lifecycle_recommendations(
    session: Session,
    *,
    lifecycle_status: str | None = None,
    attribution_mode: AttributionMode = "all_hits",
    limit: int = 100,
) -> KeywordLifecycleRecommendationListResult:
    evidence_result = list_keyword_evidence(
        session,
        lifecycle_status=lifecycle_status,
        attribution_mode=attribution_mode,
        include_breakout=False,
        include_delayed=False,
        limit=limit,
    )
    items = tuple(evaluate_lifecycle_recommendation(ev) for ev in evidence_result.items)
    return KeywordLifecycleRecommendationListResult(
        evaluated_at=evidence_result.evaluated_at,
        attribution_mode=evidence_result.attribution_mode,
        items=items,
    )


def get_lifecycle_recommendation(
    session: Session,
    keyword_id: int,
    *,
    attribution_mode: AttributionMode = "all_hits",
) -> KeywordLifecycleRecommendation | None:
    evidence = get_keyword_evidence(
        session,
        keyword_id,
        attribution_mode=attribution_mode,
        include_breakout=False,
        include_delayed=False,
    )
    if evidence is None:
        return None
    return evaluate_lifecycle_recommendation(evidence)
