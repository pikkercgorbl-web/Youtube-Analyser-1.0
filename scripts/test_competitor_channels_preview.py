"""Competitor channel preview (read-only, no DB)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.schemas import (
    ChannelSingleAnalysisPublication,
    ChannelSingleAnalysisShelfResponse,
    CompetitorChannelPreviewRequest,
)
from app.services.competitor_channels_preview import run_competitor_channel_preview


async def test_preview_partial_on_enrich_error() -> None:
    fetched_at = datetime.now(timezone.utc)
    shelf = ChannelSingleAnalysisShelfResponse(
        channel_id="UC1",
        channel_title="Channel One",
        subscribers_count=1000,
        channel_avatar_url="",
        feed_loaded_count=1,
        publications=[
            ChannelSingleAnalysisPublication(
                video_id="v1",
                channel_id="UC1",
                title="Title",
                views_count=100,
                in_feed=True,
            ),
        ],
        fetched_at=fetched_at,
    )

    with (
        patch(
            "app.services.competitor_channels_preview.run_channel_single_shelf",
            new=AsyncMock(return_value=shelf),
        ),
        patch(
            "app.services.competitor_channels_preview.enrich_publications_for_channel",
            new=AsyncMock(return_value=(shelf.publications, 0, "YouTube Data API недоступна")),
        ),
    ):
        result = await run_competitor_channel_preview(
            None,  # type: ignore[arg-type]
            CompetitorChannelPreviewRequest(input_ref="@one", channel_ref="@one"),
        )

    assert result.load_status == "partial"
    assert result.enrichment_error
    assert len(result.publications) == 1


def main() -> None:
    asyncio.run(test_preview_partial_on_enrich_error())
    print("OK: competitor channels preview tests")


if __name__ == "__main__":
    main()
