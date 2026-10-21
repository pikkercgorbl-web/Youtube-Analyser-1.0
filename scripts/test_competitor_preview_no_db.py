"""Ensure competitor preview path performs no SQL writes."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.db import engine
from app.models.schemas import (
    ChannelSingleAnalysisPublication,
    ChannelSingleAnalysisShelfResponse,
    CompetitorChannelPreviewRequest,
)
from app.services.competitor_channels_preview import run_competitor_channel_preview


def test_preview_issues_no_insert_update_delete() -> None:
    mutating: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        head = statement.lstrip().upper()
        if head.startswith("INSERT") or head.startswith("UPDATE") or head.startswith("DELETE"):
            mutating.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        fetched_at = datetime.now(timezone.utc)
        shelf = ChannelSingleAnalysisShelfResponse(
            channel_id="UC_PREVIEW_TEST",
            channel_title="Preview Test",
            subscribers_count=1,
            channel_avatar_url="",
            feed_loaded_count=0,
            publications=[],
            fetched_at=fetched_at,
        )

        async def _run() -> None:
            with (
                patch(
                    "app.services.competitor_channels_preview.run_channel_single_shelf",
                    new=AsyncMock(return_value=shelf),
                ),
                patch(
                    "app.services.competitor_channels_preview.enrich_publications_for_channel",
                    new=AsyncMock(return_value=([], 0, None)),
                ),
            ):
                await run_competitor_channel_preview(
                    None,  # type: ignore[arg-type]
                    CompetitorChannelPreviewRequest(channel_ref="@preview_test"),
                )

        asyncio.run(_run())
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert mutating == [], f"Unexpected mutating SQL during preview: {mutating[:3]}"


def main() -> None:
    test_preview_issues_no_insert_update_delete()
    print("OK: competitor preview no DB writes")


if __name__ == "__main__":
    main()
