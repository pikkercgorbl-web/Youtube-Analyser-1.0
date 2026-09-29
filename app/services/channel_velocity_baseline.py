"""Age-aligned channel velocity baseline from persisted VideoSnapshots (Stage 1.12A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from sqlalchemy.orm import Session

from app.models.orm import VideoSnapshot
from app.services.metrics import ensure_utc
from app.services.radar_candidate_analysis import _percentile
from app.services.video_snapshot_storage import get_snapshots_for_channel

BaselineStatus = Literal["ok", "partial", "insufficient_history", "unavailable"]
BaselineQuality = Literal["production_ready", "diagnostic", "none"]

DEFAULT_MIN_ABSOLUTE_TOLERANCE_HOURS = 3.0
DEFAULT_RELATIVE_TOLERANCE_FRACTION = 0.20
DEFAULT_OK_MIN_COMPARABLE = 10
DEFAULT_PARTIAL_MIN_COMPARABLE = 5


@dataclass(frozen=True, slots=True)
class ChannelVelocityBaselineConfig:
    min_absolute_tolerance_hours: float = DEFAULT_MIN_ABSOLUTE_TOLERANCE_HOURS
    relative_tolerance_fraction: float = DEFAULT_RELATIVE_TOLERANCE_FRACTION
    ok_min_comparable_videos: int = DEFAULT_OK_MIN_COMPARABLE
    partial_min_comparable_videos: int = DEFAULT_PARTIAL_MIN_COMPARABLE


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    """Minimal snapshot fields for baseline computation (ORM or tests)."""

    video_id: str
    channel_id: str
    captured_at: datetime
    published_at: datetime | None
    age_hours: float | None
    vph: float | None
    content_format: str | None = None
    is_short: bool | None = None
    is_live: bool | None = None


@dataclass(frozen=True, slots=True)
class ChannelVelocityBaselineCandidateInput:
    channel_id: str
    candidate_video_id: str
    candidate_age_hours: float | None
    candidate_vph: float | None
    candidate_published_at: datetime | None
    candidate_captured_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChannelVelocityBaselineResult:
    channel_id: str
    candidate_video_id: str
    candidate_age_hours: float | None
    candidate_vph: float | None
    historical_video_count: int
    historical_snapshot_count: int
    comparable_video_count: int
    comparable_snapshot_count: int
    target_age_hours: float | None
    age_window_hours: float | None
    min_age_hours: float | None
    max_age_hours: float | None
    median_vph: float | None
    p75_vph: float | None
    p90_vph: float | None
    mean_vph: float | None
    min_vph: float | None
    max_vph: float | None
    vph_vs_channel_median: float | None
    vph_vs_channel_p75: float | None
    vph_percentile_within_channel_history: float | None
    baseline_status: BaselineStatus
    baseline_quality: BaselineQuality
    exclusion_counts: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


def snapshot_record_from_orm(row: VideoSnapshot) -> SnapshotRecord:
    return SnapshotRecord(
        video_id=row.video_id,
        channel_id=row.channel_id,
        captured_at=row.captured_at,
        published_at=row.published_at,
        age_hours=row.age_hours,
        vph=row.vph,
        content_format=row.content_format,
        is_short=row.is_short,
        is_live=row.is_live,
    )


def compute_age_tolerance_hours(
    candidate_age_hours: float,
    config: ChannelVelocityBaselineConfig,
) -> float:
    return max(
        config.min_absolute_tolerance_hours,
        config.relative_tolerance_fraction * candidate_age_hours,
    )


def compute_age_window(
    candidate_age_hours: float,
    config: ChannelVelocityBaselineConfig,
) -> tuple[float, float, float]:
    """
    Return (tolerance_hours, min_age_hours, max_age_hours).

    Inclusive window: min_age_hours <= snapshot.age_hours <= max_age_hours.
    """
    tolerance = compute_age_tolerance_hours(candidate_age_hours, config)
    lower = max(0.0, candidate_age_hours - tolerance)
    upper = candidate_age_hours + tolerance
    return tolerance, lower, upper


def candidate_observation_cutoff(
    *,
    candidate_published_at: datetime | None,
    candidate_captured_at: datetime | None,
) -> datetime | None:
    """
    Leakage cutoff for historical uploads (aligned with T0 baseline semantics).

    Prefer candidate publish time; if missing, use capture/observation time.
    Historical videos must have published_at strictly before this cutoff.
    """
    if candidate_published_at is not None:
        return ensure_utc(candidate_published_at)
    if candidate_captured_at is not None:
        return ensure_utc(candidate_captured_at)
    return None


def _is_non_regular(snapshot: SnapshotRecord) -> str | None:
    if snapshot.is_short is True:
        return "short"
    if snapshot.is_live is True:
        return "live"
    if snapshot.content_format == "short":
        return "short"
    if snapshot.content_format == "live":
        return "live"
    if snapshot.content_format is not None and snapshot.content_format not in ("regular",):
        return "non_regular"
    return None


def _chronology_invalid(snapshot: SnapshotRecord) -> bool:
    if snapshot.published_at is None:
        return False
    published = ensure_utc(snapshot.published_at)
    captured = ensure_utc(snapshot.captured_at)
    return captured < published


def _increment(counts: dict[str, int], reason: str, amount: int = 1) -> None:
    counts[reason] = counts.get(reason, 0) + amount


def select_nearest_snapshot_for_video(
    snapshots: Sequence[SnapshotRecord],
    target_age_hours: float,
) -> SnapshotRecord | None:
    """One snapshot per video: smallest |age - target|; tie → earlier captured_at."""
    eligible = [row for row in snapshots if row.age_hours is not None]
    if not eligible:
        return None

    def sort_key(row: SnapshotRecord) -> tuple[float, float]:
        age = float(row.age_hours)  # type: ignore[arg-type]
        return (abs(age - target_age_hours), ensure_utc(row.captured_at).timestamp())

    return min(eligible, key=sort_key)


def empirical_percentile_rank(value: float, population: Sequence[float]) -> float | None:
    if not population:
        return None
    rank = sum(1 for item in population if item <= value)
    return round(rank / len(population), 4)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _resolve_status(
    comparable_count: int,
    config: ChannelVelocityBaselineConfig,
) -> tuple[BaselineStatus, BaselineQuality]:
    if comparable_count >= config.ok_min_comparable_videos:
        return "ok", "production_ready"
    if comparable_count >= config.partial_min_comparable_videos:
        return "partial", "production_ready"
    if comparable_count >= 1:
        return "insufficient_history", "diagnostic"
    return "unavailable", "none"


def compute_channel_velocity_baseline_from_snapshots(
    *,
    channel_id: str,
    candidate_video_id: str,
    candidate_age_hours: float | None,
    candidate_vph: float | None,
    candidate_published_at: datetime | None,
    candidate_captured_at: datetime | None = None,
    channel_snapshots: Sequence[SnapshotRecord],
    config: ChannelVelocityBaselineConfig | None = None,
) -> ChannelVelocityBaselineResult:
    cfg = config or ChannelVelocityBaselineConfig()
    exclusions: dict[str, int] = {}
    notes: list[str] = []

    same_channel = [row for row in channel_snapshots if row.channel_id == channel_id]
    historical = [row for row in same_channel if row.video_id != candidate_video_id]
    historical_video_ids = {row.video_id for row in historical}

    if candidate_age_hours is None or candidate_age_hours <= 0:
        status, quality = "unavailable", "none"
        notes.append("candidate_age_hours missing or non-positive")
        return ChannelVelocityBaselineResult(
            channel_id=channel_id,
            candidate_video_id=candidate_video_id,
            candidate_age_hours=candidate_age_hours,
            candidate_vph=candidate_vph,
            historical_video_count=len(historical_video_ids),
            historical_snapshot_count=len(historical),
            comparable_video_count=0,
            comparable_snapshot_count=0,
            target_age_hours=candidate_age_hours,
            age_window_hours=None,
            min_age_hours=None,
            max_age_hours=None,
            median_vph=None,
            p75_vph=None,
            p90_vph=None,
            mean_vph=None,
            min_vph=None,
            max_vph=None,
            vph_vs_channel_median=None,
            vph_vs_channel_p75=None,
            vph_percentile_within_channel_history=None,
            baseline_status=status,
            baseline_quality=quality,
            exclusion_counts=exclusions,
            notes=tuple(notes),
        )

    tolerance, min_age, max_age = compute_age_window(float(candidate_age_hours), cfg)
    cutoff = candidate_observation_cutoff(
        candidate_published_at=candidate_published_at,
        candidate_captured_at=candidate_captured_at,
    )
    if cutoff is None:
        notes.append("no candidate publish/capture cutoff; future_publication filter skipped")

    filtered_by_video: dict[str, list[SnapshotRecord]] = {}
    for snapshot in historical:
        non_regular = _is_non_regular(snapshot)
        if non_regular == "short":
            _increment(exclusions, "short")
            continue
        if non_regular == "live":
            _increment(exclusions, "live")
            continue
        if non_regular == "non_regular":
            _increment(exclusions, "non_regular")
            continue

        if snapshot.age_hours is None:
            _increment(exclusions, "missing_age_hours")
            continue
        if snapshot.age_hours <= 0:
            _increment(exclusions, "invalid_age_hours")
            continue
        if snapshot.vph is None:
            _increment(exclusions, "missing_vph")
            continue
        if snapshot.vph < 0:
            _increment(exclusions, "invalid_vph")
            continue

        if _chronology_invalid(snapshot):
            _increment(exclusions, "chronology_invalid")
            continue

        if cutoff is not None:
            if snapshot.published_at is None:
                _increment(exclusions, "missing_published_at_for_cutoff")
                continue
            if ensure_utc(snapshot.published_at) >= cutoff:
                _increment(exclusions, "future_publication")
                continue

        if not (min_age <= float(snapshot.age_hours) <= max_age):
            _increment(exclusions, "outside_age_window")
            continue

        filtered_by_video.setdefault(snapshot.video_id, []).append(snapshot)

    comparable_vph: list[float] = []
    comparable_snapshot_count = 0
    for video_id, snapshots in filtered_by_video.items():
        chosen = select_nearest_snapshot_for_video(snapshots, float(candidate_age_hours))
        if chosen is None or chosen.vph is None:
            _increment(exclusions, "no_snapshot_in_window")
            continue
        comparable_vph.append(float(chosen.vph))
        comparable_snapshot_count += 1

    comparable_count = len(comparable_vph)
    status, quality = _resolve_status(comparable_count, cfg)

    median_vph: float | None = None
    p75_vph: float | None = None
    p90_vph: float | None = None
    mean_vph: float | None = None
    min_vph: float | None = None
    max_vph: float | None = None
    vph_vs_median: float | None = None
    vph_vs_p75: float | None = None
    percentile: float | None = None

    if comparable_count == 0:
        notes.append("no comparable historical videos in age window")
    else:
        sorted_vph = sorted(comparable_vph)
        median_vph = round(_percentile(sorted_vph, 50), 4)
        p75_vph = round(_percentile(sorted_vph, 75), 4)
        p90_vph = round(_percentile(sorted_vph, 90), 4)
        mean_vph = round(sum(sorted_vph) / len(sorted_vph), 4)
        min_vph = sorted_vph[0]
        max_vph = sorted_vph[-1]

        if median_vph == 0:
            notes.append("median_vph is zero; relative ratios suppressed")

        if status in ("ok", "partial"):
            vph_vs_median = _ratio(candidate_vph, median_vph)
            vph_vs_p75 = _ratio(candidate_vph, p75_vph)
            if candidate_vph is not None:
                percentile = empirical_percentile_rank(float(candidate_vph), sorted_vph)
        else:
            notes.append("insufficient comparable history; relative ratios suppressed")

    if status == "unavailable":
        median_vph = p75_vph = p90_vph = mean_vph = min_vph = max_vph = None

    return ChannelVelocityBaselineResult(
        channel_id=channel_id,
        candidate_video_id=candidate_video_id,
        candidate_age_hours=candidate_age_hours,
        candidate_vph=candidate_vph,
        historical_video_count=len(historical_video_ids),
        historical_snapshot_count=len(historical),
        comparable_video_count=comparable_count,
        comparable_snapshot_count=comparable_snapshot_count,
        target_age_hours=float(candidate_age_hours),
        age_window_hours=round(tolerance, 4),
        min_age_hours=round(min_age, 4),
        max_age_hours=round(max_age, 4),
        median_vph=median_vph,
        p75_vph=p75_vph,
        p90_vph=p90_vph,
        mean_vph=mean_vph,
        min_vph=min_vph,
        max_vph=max_vph,
        vph_vs_channel_median=vph_vs_median,
        vph_vs_channel_p75=vph_vs_p75,
        vph_percentile_within_channel_history=percentile,
        baseline_status=status,
        baseline_quality=quality,
        exclusion_counts=exclusions,
        notes=tuple(notes),
    )


def compute_channel_velocity_baseline(
    session: Session,
    *,
    channel_id: str,
    candidate_video_id: str,
    candidate_age_hours: float | None,
    candidate_vph: float | None,
    candidate_published_at: datetime | None,
    candidate_captured_at: datetime | None = None,
    config: ChannelVelocityBaselineConfig | None = None,
) -> ChannelVelocityBaselineResult:
    rows = get_snapshots_for_channel(session, channel_id)
    records = [snapshot_record_from_orm(row) for row in rows]
    return compute_channel_velocity_baseline_from_snapshots(
        channel_id=channel_id,
        candidate_video_id=candidate_video_id,
        candidate_age_hours=candidate_age_hours,
        candidate_vph=candidate_vph,
        candidate_published_at=candidate_published_at,
        candidate_captured_at=candidate_captured_at,
        channel_snapshots=records,
        config=config,
    )


def compute_channel_velocity_baselines(
    session: Session,
    candidates: Sequence[ChannelVelocityBaselineCandidateInput],
    config: ChannelVelocityBaselineConfig | None = None,
) -> list[ChannelVelocityBaselineResult]:
    if not candidates:
        return []

    channel_ids = {item.channel_id for item in candidates}
    snapshots_by_channel: dict[str, list[SnapshotRecord]] = {}
    for channel_id in channel_ids:
        rows = get_snapshots_for_channel(session, channel_id)
        snapshots_by_channel[channel_id] = [snapshot_record_from_orm(row) for row in rows]

    results: list[ChannelVelocityBaselineResult] = []
    for item in candidates:
        results.append(
            compute_channel_velocity_baseline_from_snapshots(
                channel_id=item.channel_id,
                candidate_video_id=item.candidate_video_id,
                candidate_age_hours=item.candidate_age_hours,
                candidate_vph=item.candidate_vph,
                candidate_published_at=item.candidate_published_at,
                candidate_captured_at=item.candidate_captured_at,
                channel_snapshots=snapshots_by_channel.get(item.channel_id, []),
                config=config,
            ),
        )
    return results


def result_to_dict(result: ChannelVelocityBaselineResult) -> dict[str, Any]:
    """JSON-friendly summary without raw snapshot payloads."""
    return {
        "channel_id": result.channel_id,
        "candidate_video_id": result.candidate_video_id,
        "candidate_age_hours": result.candidate_age_hours,
        "candidate_vph": result.candidate_vph,
        "historical_video_count": result.historical_video_count,
        "historical_snapshot_count": result.historical_snapshot_count,
        "comparable_video_count": result.comparable_video_count,
        "comparable_snapshot_count": result.comparable_snapshot_count,
        "target_age_hours": result.target_age_hours,
        "age_window_hours": result.age_window_hours,
        "min_age_hours": result.min_age_hours,
        "max_age_hours": result.max_age_hours,
        "median_vph": result.median_vph,
        "p75_vph": result.p75_vph,
        "p90_vph": result.p90_vph,
        "mean_vph": result.mean_vph,
        "min_vph": result.min_vph,
        "max_vph": result.max_vph,
        "vph_vs_channel_median": result.vph_vs_channel_median,
        "vph_vs_channel_p75": result.vph_vs_channel_p75,
        "vph_percentile_within_channel_history": result.vph_percentile_within_channel_history,
        "baseline_status": result.baseline_status,
        "baseline_quality": result.baseline_quality,
        "exclusion_counts": dict(result.exclusion_counts),
        "notes": list(result.notes),
    }
