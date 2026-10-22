"""Atomic UTC-day API budget reservation for Radar enrichment (Stage 2.5 / Stage 2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.orm import RadarApiBudgetDay

BUDGET_KIND_CHANNELS_LIST = "channels_list"
BUDGET_KIND_VIDEOS_LIST = "videos_list"

# Ledger counts reserved ID units (channels.list / videos.list batch sizes), not YouTube quota units.
# http_requests counts outbound batch invocations (one per get_channels / get_videos call), not per-ID HTTP.


def utc_calendar_day(now: datetime | None = None) -> date:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.date()


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


@dataclass(frozen=True, slots=True)
class BudgetDaySnapshot:
    budget_kind: str
    utc_day: date
    id_units_reserved: int = 0
    http_requests: int = 0


def read_budget_day(
    session: Session,
    *,
    budget_kind: str,
    now: datetime | None = None,
) -> BudgetDaySnapshot:
    """Read-only: missing UTC day → zeros, no INSERT."""
    day = utc_calendar_day(now)
    row = session.get(RadarApiBudgetDay, {"budget_kind": budget_kind, "utc_day": day})
    if row is None:
        return BudgetDaySnapshot(budget_kind=budget_kind, utc_day=day, id_units_reserved=0, http_requests=0)
    return BudgetDaySnapshot(
        budget_kind=budget_kind,
        utc_day=day,
        id_units_reserved=int(row.id_units_reserved),
        http_requests=int(row.http_requests),
    )


def budget_day_status(
    session: Session,
    *,
    budget_kind: str,
    now: datetime | None = None,
) -> BudgetDaySnapshot:
    """Alias for read-only day status (no side effects)."""
    return read_budget_day(session, budget_kind=budget_kind, now=now)


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


def _ensure_budget_day_row_postgres(session: Session, *, budget_kind: str, utc_day: date) -> None:
    session.execute(
        text(
            """
            INSERT INTO radar_api_budget_daily (budget_kind, utc_day, id_units_reserved, http_requests)
            VALUES (:kind, :day, 0, 0)
            ON CONFLICT (budget_kind, utc_day) DO NOTHING
            """,
        ),
        {"kind": budget_kind, "day": utc_day},
    )


_RESERVE_SQL = text(
    """
    WITH locked AS (
        SELECT id_units_reserved
        FROM radar_api_budget_daily
        WHERE budget_kind = :kind AND utc_day = :day
        FOR UPDATE
    ),
    grant_calc AS (
        SELECT LEAST(
            :unit_count,
            GREATEST(0, :daily_limit - locked.id_units_reserved)
        ) AS grant_n
        FROM locked
    )
    UPDATE radar_api_budget_daily AS d
    SET id_units_reserved = d.id_units_reserved + grant_calc.grant_n
    FROM grant_calc
    WHERE d.budget_kind = :kind AND d.utc_day = :day
    RETURNING d.id_units_reserved AS reserved_after, grant_calc.grant_n AS granted
    """,
)


_INCREMENT_HTTP_SQL = text(
    """
    UPDATE radar_api_budget_daily
    SET http_requests = http_requests + :request_count
    WHERE budget_kind = :kind AND utc_day = :day
    RETURNING http_requests
    """,
)


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
    """
    Atomically reserve up to unit_count ID slots for the UTC day.

    On PostgreSQL uses row lock + single UPDATE (safe across processes).
    Reserved units are not auto-refunded on downstream failure (request may have reached YouTube).
    """
    day = utc_calendar_day(now)
    if unit_count <= 0 or daily_limit <= 0:
        snap = read_budget_day(session, budget_kind=budget_kind, now=now)
        return BudgetReservationResult(
            budget_kind=budget_kind,
            utc_day=day,
            requested=unit_count,
            reserved=0,
            daily_limit=daily_limit,
            reserved_after=snap.id_units_reserved,
        )

    if _dialect_name(session) == "postgresql":
        _ensure_budget_day_row_postgres(session, budget_kind=budget_kind, utc_day=day)
        row = session.execute(
            _RESERVE_SQL,
            {
                "kind": budget_kind,
                "day": day,
                "unit_count": int(unit_count),
                "daily_limit": int(daily_limit),
            },
        ).one()
        session.flush()
        granted = int(row.granted or 0)
        reserved_after = int(row.reserved_after or 0)
        return BudgetReservationResult(
            budget_kind=budget_kind,
            utc_day=day,
            requested=unit_count,
            reserved=granted,
            daily_limit=daily_limit,
            reserved_after=reserved_after,
        )

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
    """Increment batch HTTP attempt counter (one per API batch call, not per ID)."""
    if request_count <= 0:
        return
    day = utc_calendar_day(now)
    if _dialect_name(session) == "postgresql":
        _ensure_budget_day_row_postgres(session, budget_kind=budget_kind, utc_day=day)
        session.execute(
            _INCREMENT_HTTP_SQL,
            {"kind": budget_kind, "day": day, "request_count": int(request_count)},
        )
        session.flush()
        return
    row = _get_or_create_row(session, budget_kind=budget_kind, utc_day=day)
    row.http_requests = int(row.http_requests) + int(request_count)
    session.flush()


def remaining_id_units(session: Session, *, budget_kind: str, daily_limit: int, now: datetime | None = None) -> int:
    row = read_budget_day(session, budget_kind=budget_kind, now=now)
    return max(0, daily_limit - int(row.id_units_reserved))


def enrichment_daily_budget_summary(session: Session, *, now: datetime | None = None) -> dict[str, object]:
    """Effective UTC-day limits, ledger reserved units, HTTP batch attempts, and remaining headroom."""
    from app.services.radar_enrichment_config import radar_enrichment_settings
    from app.services.unknown_format_enrichment_config import unknown_format_enrichment_settings

    stamp = now or datetime.now(timezone.utc)
    ch_daily = radar_enrichment_settings.channel_subscriber_enrichment_daily_limit
    vid_daily = unknown_format_enrichment_settings.unknown_format_enrichment_daily_video_limit
    ch_row = read_budget_day(session, budget_kind=BUDGET_KIND_CHANNELS_LIST, now=stamp)
    vid_row = read_budget_day(session, budget_kind=BUDGET_KIND_VIDEOS_LIST, now=stamp)
    return {
        "utc_day": utc_calendar_day(stamp).isoformat(),
        "http_requests_semantics": "batch_api_calls_not_youtube_quota_units",
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


def count_budget_rows(session: Session) -> int:
    from sqlalchemy import func

    return int(session.scalar(select(func.count()).select_from(RadarApiBudgetDay)) or 0)
