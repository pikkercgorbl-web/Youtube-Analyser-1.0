"""Atomic UTC-day API budget reservation for Radar enrichment (Stage 2.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import RadarApiBudgetDay

BUDGET_KIND_CHANNELS_LIST = "channels_list"
BUDGET_KIND_VIDEOS_LIST = "videos_list"


def utc_calendar_day(now: datetime | None = None) -> date:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.date()


def _get_or_create_row(session: Session, *, budget_kind: str, utc_day: date) -> RadarApiBudgetDay:
    row = session.get(RadarApiBudgetDay, {"budget_kind": budget_kind, "utc_day": utc_day})
    if row is None:
        row = RadarApiBudgetDay(
            budget_kind=budget_kind,
            utc_day=utc_day,
            id_units_reserved=0,
            http_requests=0,
        )
        session.add(row)
        session.flush()
    return row


@dataclass(frozen=True, slots=True)
class BudgetReservationResult:
    budget_kind: str
    utc_day: date
    requested: int
    reserved: int
    daily_limit: int
    reserved_after: int


def try_reserve_id_units(
    session: Session,
    *,
    budget_kind: str,
    unit_count: int,
    daily_limit: int,
    now: datetime | None = None,
) -> BudgetReservationResult:
    """Atomically reserve up to unit_count ID slots for the UTC day (per-process flush)."""
    if unit_count <= 0 or daily_limit <= 0:
        day = utc_calendar_day(now)
        row = _get_or_create_row(session, budget_kind=budget_kind, utc_day=day)
        return BudgetReservationResult(
            budget_kind=budget_kind,
            utc_day=day,
            requested=unit_count,
            reserved=0,
            daily_limit=daily_limit,
            reserved_after=row.id_units_reserved,
        )

    day = utc_calendar_day(now)
    row = _get_or_create_row(session, budget_kind=budget_kind, utc_day=day)
    remaining = max(0, daily_limit - int(row.id_units_reserved))
    reserved = min(unit_count, remaining)
    if reserved > 0:
        row.id_units_reserved = int(row.id_units_reserved) + reserved
        session.flush()
    return BudgetReservationResult(
        budget_kind=budget_kind,
        utc_day=day,
        requested=unit_count,
        reserved=reserved,
        daily_limit=daily_limit,
        reserved_after=int(row.id_units_reserved),
    )


def record_http_requests(
    session: Session,
    *,
    budget_kind: str,
    request_count: int = 1,
    now: datetime | None = None,
) -> None:
    if request_count <= 0:
        return
    day = utc_calendar_day(now)
    row = _get_or_create_row(session, budget_kind=budget_kind, utc_day=day)
    row.http_requests = int(row.http_requests) + int(request_count)
    session.flush()


def budget_day_status(
    session: Session,
    *,
    budget_kind: str,
    now: datetime | None = None,
) -> RadarApiBudgetDay:
    day = utc_calendar_day(now)
    return _get_or_create_row(session, budget_kind=budget_kind, utc_day=day)


def remaining_id_units(session: Session, *, budget_kind: str, daily_limit: int, now: datetime | None = None) -> int:
    row = budget_day_status(session, budget_kind=budget_kind, now=now)
    return max(0, daily_limit - int(row.id_units_reserved))


def enrichment_daily_budget_summary(session: Session, *, now: datetime | None = None) -> dict[str, object]:
    """Effective UTC-day limits, ledger reserved units, HTTP attempts, and remaining headroom."""
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    stamp = now or datetime.now(timezone.utc)
    ch_daily = radar_enrichment_settings.channel_subscriber_enrichment_daily_limit
    vid_daily = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    ch_row = budget_day_status(session, budget_kind=BUDGET_KIND_CHANNELS_LIST, now=stamp)
    vid_row = budget_day_status(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=stamp)
    return {
        "utc_day": utc_calendar_day(stamp).isoformat(),
        "channels_list": {
            "daily_limit": ch_daily,
            "pass_limit": radar_enrichment_settings.channel_subscriber_enrichment_pass_limit,
            "id_units_reserved": int(ch_row.id_units_reserved),
            "http_requests": int(ch_row.http_requests),
            "remaining_id_units": remaining_id_units(
                session,
                budget_kind=BUDGET_KIND_CHANNELS_LIST,
                daily_limit=ch_daily,
                now=stamp,
            ),
        },
        "videos_list": {
            "daily_limit": vid_daily,
            "pass_limit": radar_enrichment_settings.video_format_enrichment_pass_limit,
            "id_units_reserved": int(vid_row.id_units_reserved),
            "http_requests": int(vid_row.http_requests),
            "remaining_id_units": remaining_id_units(
                session,
                budget_kind=BUDGET_KIND_VIDEOS_LIST,
                daily_limit=vid_daily,
                now=stamp,
            ),
        },
    }
