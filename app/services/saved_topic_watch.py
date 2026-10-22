"""Saved topic observation timeline helpers (SAV-F-01/02/08)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import AttentionRun, SavedTopic, SavedTopicObservation
from app.services.metrics import ensure_utc

AnalysisLifecycle = Literal[
    "present_in_latest",
    "absent_in_latest",
    "no_new_attention_run",
    "awaiting_first_follow_up",
    "no_observations",
]

MilestoneKind = Literal["saved", "detected_again", "not_detected"]


@dataclass(frozen=True, slots=True)
class WatchMilestone:
    kind: MilestoneKind
    occurred_at: datetime
    attention_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class WatchSummary:
    headline: str
    observation_count: int
    saved_at: datetime
    last_observation_at: datetime | None
    last_present_at: datetime | None
    last_absent_at: datetime | None
    latest_attention_run_at: datetime | None
    present_in_latest_snapshot: bool | None
    analysis_lifecycle: AnalysisLifecycle
    stale_message: str | None
    milestones: list[WatchMilestone]

    def as_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "observation_count": self.observation_count,
            "saved_at": self.saved_at,
            "last_observation_at": self.last_observation_at,
            "last_present_at": self.last_present_at,
            "last_absent_at": self.last_absent_at,
            "latest_attention_run_at": self.latest_attention_run_at,
            "present_in_latest_snapshot": self.present_in_latest_snapshot,
            "analysis_lifecycle": self.analysis_lifecycle,
            "stale_message": self.stale_message,
            "milestones": [
                {
                    "kind": m.kind,
                    "occurred_at": m.occurred_at,
                    "attention_run_id": m.attention_run_id,
                }
                for m in self.milestones
            ],
        }


def latest_attention_run_at(session: Session) -> datetime | None:
    row = session.scalar(
        select(AttentionRun.computed_at).order_by(AttentionRun.computed_at.desc()).limit(1),
    )
    return ensure_utc(row) if row is not None else None


def observation_rollups(
    session: Session,
    topic_id: int,
) -> tuple[int, datetime | None, datetime | None, datetime | None]:
    rows = session.scalars(
        select(SavedTopicObservation)
        .where(SavedTopicObservation.saved_topic_id == topic_id)
        .order_by(SavedTopicObservation.captured_at.asc(), SavedTopicObservation.id.asc()),
    ).all()
    if not rows:
        return 0, None, None, None
    import json

    last_present: datetime | None = None
    last_absent: datetime | None = None
    last_any = ensure_utc(rows[-1].captured_at)
    for row in rows:
        at = ensure_utc(row.captured_at)
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if payload.get("present_in_snapshot"):
            last_present = at
        else:
            last_absent = at
    return len(rows), last_any, last_present, last_absent


def _milestones_from_observations(
    topic: SavedTopic,
    observations: list[SavedTopicObservation],
) -> list[WatchMilestone]:
    import json

    saved_at = ensure_utc(topic.created_at)
    out: list[WatchMilestone] = [WatchMilestone(kind="saved", occurred_at=saved_at)]
    seen_present_after_save = False
    for row in observations:
        at = ensure_utc(row.captured_at)
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        present = bool(payload.get("present_in_snapshot"))
        if present:
            if at - saved_at <= timedelta(seconds=2) and not seen_present_after_save:
                continue
            out.append(
                WatchMilestone(
                    kind="detected_again",
                    occurred_at=at,
                    attention_run_id=row.attention_run_id,
                ),
            )
            seen_present_after_save = True
        else:
            out.append(
                WatchMilestone(
                    kind="not_detected",
                    occurred_at=at,
                    attention_run_id=row.attention_run_id,
                ),
            )
    return out


def build_watch_summary(
    session: Session,
    topic: SavedTopic,
    *,
    live: SavedTopicObservation | None,
    observation_count: int | None = None,
) -> WatchSummary:
    import json

    saved_at = ensure_utc(topic.created_at)
    if observation_count is None:
        observation_count, last_obs_at, last_present, last_absent = observation_rollups(
            session,
            topic.id,
        )
    else:
        _, last_obs_at, last_present, last_absent = observation_rollups(session, topic.id)

    latest_run_at = latest_attention_run_at(session)

    present: bool | None = None
    if live is not None:
        try:
            payload = json.loads(live.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        present = bool(payload.get("present_in_snapshot"))
        if last_obs_at is None:
            last_obs_at = ensure_utc(live.captured_at)

    obs_rows = list(
        session.scalars(
            select(SavedTopicObservation)
            .where(SavedTopicObservation.saved_topic_id == topic.id)
            .order_by(SavedTopicObservation.captured_at.asc(), SavedTopicObservation.id.asc()),
        ).all(),
    )
    milestones = _milestones_from_observations(topic, obs_rows)

    lifecycle: AnalysisLifecycle
    stale_message: str | None = None
    headline: str

    if observation_count == 0:
        lifecycle = "no_observations"
        headline = "Тема сохранена; автоматических наблюдений пока нет."
        stale_message = "Нет новых наблюдений с момента сохранения."
    elif observation_count == 1 and (
        latest_run_at is None
        or last_obs_at is not None
        and latest_run_at <= last_obs_at + timedelta(seconds=1)
    ):
        lifecycle = "awaiting_first_follow_up"
        headline = "Сохранена; ждём следующий завершённый анализ Attention для продолжения истории."
        stale_message = _stale_since(last_obs_at or saved_at)
    elif latest_run_at is not None and last_obs_at is not None and latest_run_at > last_obs_at + timedelta(
        seconds=1,
    ):
        lifecycle = "no_new_attention_run"
        headline = "Новых анализов Attention после последнего наблюдения не было."
        stale_message = _stale_since(last_obs_at)
    elif present is True:
        lifecycle = "present_in_latest"
        headline = "Тема снова представлена в последней выборке Attention."
        if last_present:
            stale_message = None
    elif present is False:
        lifecycle = "absent_in_latest"
        headline = "Тема не обнаружена в последней выборке Attention."
        stale_message = _stale_since(last_obs_at)
    else:
        lifecycle = "no_observations"
        headline = "Нет данных о последнем наблюдении."
        stale_message = _stale_since(saved_at)

    return WatchSummary(
        headline=headline,
        observation_count=observation_count,
        saved_at=saved_at,
        last_observation_at=last_obs_at,
        last_present_at=last_present,
        last_absent_at=last_absent,
        latest_attention_run_at=latest_run_at,
        present_in_latest_snapshot=present,
        analysis_lifecycle=lifecycle,
        stale_message=stale_message,
        milestones=milestones,
    )


def _stale_since(when: datetime | None) -> str | None:
    if when is None:
        return None
    return f"Нет новых наблюдений с {ensure_utc(when).strftime('%d.%m.%Y %H:%M UTC')}."
