"""Load shared radar qualification settings once per discovery scan (Stage 1.20E.6)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.explosive_channels_service import (
    ExplosiveChannelsService,
    RadarQualificationContext,
)

__all__ = ["RadarQualificationContext", "load_radar_qualification_context"]


def load_radar_qualification_context(
    session: Session,
    *,
    upload_period: str | None = None,
) -> RadarQualificationContext:
    return ExplosiveChannelsService().get_radar_qualification_context(
        session,
        upload_period=upload_period,
    )
