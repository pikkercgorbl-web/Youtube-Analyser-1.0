from sqlalchemy.orm import Session

from app.models.orm import Channel
from app.models.schemas import ChannelCreate, ChannelUpdate


class ChannelService:
    """Business logic for YouTube channels."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, channel_id: str) -> Channel | None:
        # TODO: fetch channel from database
        raise NotImplementedError

    def create(self, payload: ChannelCreate) -> Channel:
        # TODO: validate uniqueness, persist channel
        raise NotImplementedError

    def update(self, channel_id: str, payload: ChannelUpdate) -> Channel | None:
        # TODO: partial update with optimistic locking
        raise NotImplementedError

    def delete(self, channel_id: str) -> bool:
        # TODO: soft or hard delete
        raise NotImplementedError
