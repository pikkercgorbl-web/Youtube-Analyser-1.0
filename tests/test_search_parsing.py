"""Smoke tests for InnerTube search JSON parsing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import (
    YouTubeApiClient,
    YouTubeApiKeyManager,
    _build_innertube_context,
    _extract_search_continuation,
    _parse_search_videos,
)


async def _fetch_page(client: YouTubeApiClient, query: str, *, continuation: str | None = None):
    payload: dict = {"context": _build_innertube_context(query)}
    if continuation:
        payload["continuation"] = continuation
    else:
        payload["query"] = query
        payload["params"] = "EgQIAhAB"
    return await client._innertube_request(payload, url=client.INNERTUBE_SEARCH_URL)


async def main() -> None:
    client = YouTubeApiClient(YouTubeApiKeyManager(["unused"]))
    query = "python tutorial"

    page1 = await _fetch_page(client, query)
    videos1, skipped1, counts1 = _parse_search_videos(page1)
    token = _extract_search_continuation(page1)

    print(f"Page 1: videoRenderer={counts1.get('videoRenderer', 0)}, parsed={len(videos1)}")
    if counts1.get("videoRenderer", 0) < 5:
        print("FAIL: expected at least 5 videoRenderer nodes on page 1")
        sys.exit(1)
    if len(videos1) < 5:
        print("FAIL: expected at least 5 parsed videos on page 1")
        sys.exit(1)
    if not token:
        print("FAIL: continuation token missing on page 1")
        sys.exit(1)

    page2 = await _fetch_page(client, query, continuation=token)
    videos2, skipped2, counts2 = _parse_search_videos(page2)
    token2 = _extract_search_continuation(page2)

    print(f"Page 2: videoRenderer={counts2.get('videoRenderer', 0)}, parsed={len(videos2)}")
    if counts2.get("videoRenderer", 0) < 5:
        print("FAIL: expected at least 5 videoRenderer nodes on page 2")
        sys.exit(1)
    if len(videos2) < 5:
        print("FAIL: expected at least 5 parsed videos on page 2")
        sys.exit(1)
    if not token2:
        print("FAIL: continuation token missing on page 2")
        sys.exit(1)

    print(
        f"OK: search parsing works (skipped page1={skipped1}, page2={skipped2}, "
        f"lockup page1={counts1.get('lockupViewModel', 0)})",
    )


if __name__ == "__main__":
    asyncio.run(main())
