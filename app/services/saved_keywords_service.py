"""CRUD operations for saved keywords."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import SavedKeyword
from app.models.schemas import SavedKeywordCreate


class SavedKeywordsService:
    """Persist and manage saved keyword records."""

    def upsert(self, db: Session, payload: SavedKeywordCreate) -> SavedKeyword:
        normalized_keyword = payload.keyword.strip()
        existing = db.scalar(
            select(SavedKeyword).where(SavedKeyword.keyword == normalized_keyword),
        )

        if existing is None:
            record = SavedKeyword(
                keyword=normalized_keyword,
                volume=payload.volume,
                competition=payload.competition,
                score=payload.score,
                category=payload.category.strip(),
            )
            db.add(record)
        else:
            existing.volume = payload.volume
            existing.competition = payload.competition
            existing.score = payload.score
            existing.category = payload.category.strip()
            record = existing

        db.commit()
        db.refresh(record)
        return record

    def list_all(self, db: Session) -> list[SavedKeyword]:
        return list(
            db.scalars(
                select(SavedKeyword).order_by(SavedKeyword.score.desc(), SavedKeyword.id.desc()),
            ).all(),
        )

    def delete(self, db: Session, keyword_id: int) -> bool:
        record = db.get(SavedKeyword, keyword_id)
        if record is None:
            return False
        db.delete(record)
        db.commit()
        return True
