"""CRUD and due-queue selection for radar target keywords."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import RadarWorkerState, TargetKeyword
from app.models.schemas import RadarStatsResponse, TargetKeywordCreate
from app.services.metrics import utc_now

DEFAULT_BATCH_SIZE = 5
WORKER_STATE_ROW_ID = 1


class TargetKeywordsService:
    """Manage keywords scanned by the explosive-channels background worker."""

    def create(self, db: Session, payload: TargetKeywordCreate) -> TargetKeyword:
        normalized = payload.keyword.strip()
        record = TargetKeyword(keyword=normalized)
        db.add(record)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            msg = f"Keyword already exists: {normalized!r}"
            raise ValueError(msg) from exc
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
        """Return keywords that were checked longest ago; never-checked go first."""
        total = db.scalar(select(func.count()).select_from(TargetKeyword)) or 0
        if total == 0:
            return []

        limit = max(1, min(batch_size, total))
        return list(
            db.scalars(
                select(TargetKeyword)
                .order_by(
                    TargetKeyword.last_checked.is_(None).desc(),
                    TargetKeyword.last_checked.asc(),
                    TargetKeyword.id.asc(),
                )
                .limit(limit),
            ).all(),
        )

    def mark_checked(self, db: Session, keyword_ids: list[int]) -> None:
        """Stamp last_checked for keywords processed by the radar worker."""
        if not keyword_ids:
            return

        now = utc_now()
        db.execute(
            update(TargetKeyword)
            .where(TargetKeyword.id.in_(keyword_ids))
            .values(last_checked=now),
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
                ),
            )
        else:
            state.last_target_keyword_id = 0

        db.commit()
        return total_keywords
