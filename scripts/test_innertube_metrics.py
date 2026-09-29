"""Smoke tests for InnerTube request metrics (Stage 0)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiError
from app.integrations.youtube.innertube_metrics import (
    InnerTubeMetrics,
    innertube_endpoint_key,
)
from app.integrations.youtube.key_manager import YouTubeApiKeyManager


def _mock_httpx_post(*, status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError("no json")

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=response)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_client_ctx


async def test_innertube_request_success_records_metrics() -> None:
    metrics = InnerTubeMetrics.empty()
    client = YouTubeApiClient(
        YouTubeApiKeyManager(["unused"]),
        innertube_metrics=metrics,
    )
    mock_client_ctx = _mock_httpx_post(status_code=200, json_data={"ok": True})

    with patch("app.integrations.youtube.client.httpx.AsyncClient", return_value=mock_client_ctx):
        with patch("app.integrations.youtube.client._persist_innertube_debug_response"):
            with patch("app.integrations.youtube.client._warn_innertube_response_blockers"):
                result = await client._innertube_request(
                    {"context": {}},
                    url=YouTubeApiClient.INNERTUBE_SEARCH_URL,
                )

    assert result == {"ok": True}
    assert metrics.request_count == 1
    assert metrics.error_count == 0
    assert metrics.by_endpoint["search"].count == 1
    assert metrics.by_endpoint["search"].error_count == 0


async def test_innertube_request_http_error_records_metrics() -> None:
    metrics = InnerTubeMetrics.empty()
    client = YouTubeApiClient(
        YouTubeApiKeyManager(["unused"]),
        innertube_metrics=metrics,
    )
    mock_client_ctx = _mock_httpx_post(status_code=503, text="service unavailable")

    with patch("app.integrations.youtube.client.httpx.AsyncClient", return_value=mock_client_ctx):
        try:
            await client._innertube_request(
                {"context": {}},
                url=YouTubeApiClient.INNERTUBE_SEARCH_URL,
            )
        except YouTubeApiError as exc:
            assert "503" in str(exc)
        else:
            raise AssertionError("expected YouTubeApiError")

    assert metrics.request_count == 1
    assert metrics.error_count == 1
    assert metrics.by_endpoint["search"].error_count == 1


async def test_innertube_request_without_metrics_collector() -> None:
    client = YouTubeApiClient(YouTubeApiKeyManager(["unused"]))
    mock_client_ctx = _mock_httpx_post(status_code=200, json_data={"ok": True})

    with patch("app.integrations.youtube.client.httpx.AsyncClient", return_value=mock_client_ctx):
        with patch("app.integrations.youtube.client._persist_innertube_debug_response"):
            with patch("app.integrations.youtube.client._warn_innertube_response_blockers"):
                result = await client._innertube_request(
                    {"context": {}},
                    url=YouTubeApiClient.INNERTUBE_PLAYER_URL,
                )

    assert result == {"ok": True}


def test_innertube_endpoint_key_classification() -> None:
    assert innertube_endpoint_key(YouTubeApiClient.INNERTUBE_SEARCH_URL) == "search"
    assert innertube_endpoint_key(YouTubeApiClient.INNERTUBE_PLAYER_URL) == "player"
    assert innertube_endpoint_key(YouTubeApiClient.INNERTUBE_BROWSE_URL) == "browse"
    assert innertube_endpoint_key(YouTubeApiClient.INNERTUBE_RESOLVE_URL) == "resolve_url"
    assert (
        innertube_endpoint_key(YouTubeApiClient.INNERTUBE_SEARCH_SUGGESTIONS_URL)
        == "suggestions"
    )
    assert innertube_endpoint_key("https://example.com/unknown") == "other"


async def main() -> None:
    failed = 0

    try:
        await test_innertube_request_success_records_metrics()
        print("OK test_innertube_request_success_records_metrics")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_innertube_request_success_records_metrics: {exc}")

    try:
        await test_innertube_request_http_error_records_metrics()
        print("OK test_innertube_request_http_error_records_metrics")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_innertube_request_http_error_records_metrics: {exc}")

    try:
        await test_innertube_request_without_metrics_collector()
        print("OK test_innertube_request_without_metrics_collector")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_innertube_request_without_metrics_collector: {exc}")

    try:
        test_innertube_endpoint_key_classification()
        print("OK test_innertube_endpoint_key_classification")
    except Exception as exc:
        failed += 1
        print(f"FAIL test_innertube_endpoint_key_classification: {exc}")

    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print("All innertube metrics tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
