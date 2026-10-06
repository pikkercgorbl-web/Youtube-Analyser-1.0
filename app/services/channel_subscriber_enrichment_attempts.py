"""Persist channels.list subscriber check attempts (Stage 2.5)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.orm import ChannelSubscriberEnrichmentAttempt


def record_channel_subscriber_attempt(
    session: Session,
    *,
    channel_id: str,
    outcome: str,
    attempted_at: datetime | None = None,
) -> None:
    stamp = attempted_at or datetime.now(timezone.utc)
    row = session.get(ChannelSubscriberEnrichmentAttempt, channel_id)
    if row is None:
        session.add(
            ChannelSubscriberEnrichmentAttempt(
                channel_id=channel_id,
                last_attempt_at=stamp,
                last_outcome=outcome,
            ),
        )
    else:
        row.last_attempt_at = stamp
        row.last_outcome = outcome
    session.flush()
