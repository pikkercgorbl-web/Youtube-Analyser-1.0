from sqlalchemy.orm import Session

from app.models.orm import Keyword
from app.models.schemas import KeywordCreate, KeywordUpdate


class KeywordService:
    """Business logic for search keywords."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def search(self, query: str, *, limit: int = 20) -> list[Keyword]:
        # TODO: full-text or prefix search on keyword text
        raise NotImplementedError

    def create(self, payload: KeywordCreate) -> Keyword:
        # TODO: deduplicate by text, persist keyword
        raise NotImplementedError

    def update(self, keyword_id: int, payload: KeywordUpdate) -> Keyword | None:
        # TODO: partial update
        raise NotImplementedError
