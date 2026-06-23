"""Full InnerTube search pipeline demo.

Run from project root:
    python -m scripts.run_enriched_search
    python -m scripts.run_enriched_search "python tutorial"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.integrations.youtube.client import YouTubeApiClient, YouTubeApiKeyManager, get_enriched_search_results
from app.services.video_filter_service import VideoFilterService
from app.utils.enriched_formatter import (
    format_enriched_results,
    render_enriched_results_text,
)


async def run_pipeline(
    query: str,
    *,
    max_results: int = 10,
    sort_by: str = "virality",
    show_suggestions: bool = True,
) -> None:
    client = YouTubeApiClient(YouTubeApiKeyManager(["unused-for-innertube"]))
    filter_service = VideoFilterService()

    if show_suggestions:
        suggestions = await client.get_search_suggestions(query)
        print("Подсказки YouTube:")
        for index, suggestion in enumerate(suggestions, start=1):
            print(f"  {index}. {suggestion}")
        print()

    print(f"Поиск: {query!r} (до {max_results} видео)...")
    enriched = await get_enriched_search_results(query, max_results=max_results)
    print(f"Получено видео: {len(enriched)}")

    filters_config = {
        "hide_shorts": False,
        "hide_hieroglyphs": False,
        "virality_only_above_one": False,
        "virality_min": 0.0,
        "plus_words": [],
        "minus_words": [],
    }
    filtered = filter_service.apply_filters(enriched, filters_config)
    sorted_videos = filter_service.sort_results(filtered, sort_by)
    print(f"После фильтров: {len(sorted_videos)} | сортировка: {sort_by}")
    print()

    print(render_enriched_results_text(sorted_videos))
    print()
    print("JSON-отчёт:")
    print(format_enriched_results(sorted_videos, output_format="json"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="InnerTube enriched search with filters, sorting and formatting.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="python tutorial",
        help='Search query (default: "python tutorial")',
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum videos to fetch (default: 10)",
    )
    parser.add_argument(
        "--sort-by",
        choices=["views", "date", "virality", "relevance"],
        default="virality",
        help="Sort mode (default: virality)",
    )
    parser.add_argument(
        "--no-suggestions",
        action="store_true",
        help="Skip autocomplete suggestions request",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run_pipeline(
                args.query,
                max_results=max(1, min(args.max_results, 50)),
                sort_by=args.sort_by,
                show_suggestions=not args.no_suggestions,
            ),
        )
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
