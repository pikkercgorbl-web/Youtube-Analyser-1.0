"""CRUD and due-queue selection for radar target keywords."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.orm import RadarWorkerState, TargetKeyword
from app.models.schemas import RadarStatsResponse, TargetKeywordCreate
from app.services.discovery_keyword_selection import select_discovery_keywords
from app.services.keyword_lifecycle_service import create_keyword, normalize_keyword_text
from app.services.keyword_scheduling_policy import LIFECYCLE_ACTIVE, SOURCE_SEED
from app.services.metrics import utc_now

DEFAULT_BATCH_SIZE = 5
WORKER_STATE_ROW_ID = 1
WORKER_STATUS_IDLE = "idle"
WORKER_STATUS_RUNNING = "running"
WORKER_STATUS_STOPPED = "stopped"


class TargetKeywordsService:
    """Manage keywords scanned by the explosive-channels background worker."""

    def create(self, db: Session, payload: TargetKeywordCreate) -> TargetKeyword:
        normalized = normalize_keyword_text(payload.keyword)
        record = create_keyword(
            db,
            normalized,
            source_type=SOURCE_SEED,
            lifecycle_status=LIFECYCLE_ACTIVE,
        )
        db.commit()
        db.refresh(record)
        return record

    def list_all(self, db: Session) -> list[TargetKeyword]:
        return list(
            db.scalars(
                select(TargetKeyword).order_by(TargetKeyword.id.asc()),
            ).all(),
        )

    def pick_due_batch(
        self,
        db: Session,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> list[TargetKeyword]:
        """Return lifecycle-due keywords (Stage 1.16B scheduling)."""
        return select_discovery_keywords(db, batch_size=batch_size)

    def mark_checked(self, db: Session, keyword_ids: list[int]) -> None:
        """Stamp last_checked and next_scan_at after successful processing."""
        if not keyword_ids:
            return

        from app.services.keyword_lifecycle_service import apply_post_scan_schedule

        now = utc_now()
        for keyword_id in keyword_ids:
            apply_post_scan_schedule(
                db,
                keyword_id,
                finished_at=now,
                scan_succeeded=True,
            )
        db.commit()

    def get_radar_stats(self, db: Session) -> RadarStatsResponse:
        total_keywords = db.scalar(select(func.count()).select_from(TargetKeyword)) or 0
        cutoff = utc_now() - timedelta(hours=24)
        checked_today = (
            db.scalar(
                select(func.count())
                .select_from(TargetKeyword)
                .where(TargetKeyword.last_checked.is_not(None))
                .where(TargetKeyword.last_checked >= cutoff),
            )
            or 0
        )
        return RadarStatsResponse(
            total_keywords=total_keywords,
            checked_today=checked_today,
        )

    def reset_radar_queue(self, db: Session) -> int:
        """Reset radar cursor and clear last_checked so the next batch starts from id=1."""
        total_keywords = db.scalar(select(func.count()).select_from(TargetKeyword)) or 0

        db.execute(update(TargetKeyword).values(last_checked=None))

        state = db.get(RadarWorkerState, WORKER_STATE_ROW_ID)
        if state is None:
            db.add(
                RadarWorkerState(
                    id=WORKER_STATE_ROW_ID,
                    last_target_keyword_id=0,
                    status=WORKER_STATUS_IDLE,
                ),
            )
        else:
            state.last_target_keyword_id = 0
            state.status = WORKER_STATUS_IDLE

        db.commit()
        return total_keywords

    def get_worker_status(self, db: Session) -> str:
        state = self._get_or_create_worker_state(db)
        return state.status or WORKER_STATUS_IDLE

    def set_worker_status(self, db: Session, status: str) -> str:
        state = self._get_or_create_worker_state(db)
        state.status = status
        state.updated_at = utc_now()
        db.commit()
        db.refresh(state)
        return state.status

    def is_worker_stopped(self, db: Session) -> bool:
        return self.get_worker_status(db) == WORKER_STATUS_STOPPED

    def _get_or_create_worker_state(self, db: Session) -> RadarWorkerState:
        state = db.get(RadarWorkerState, WORKER_STATE_ROW_ID)
        if state is not None:
            return state

        state = RadarWorkerState(
            id=WORKER_STATE_ROW_ID,
            last_target_keyword_id=0,
            status=WORKER_STATUS_IDLE,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
        return state
