"""Verification for keyword analysis scoring logic."""

from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.youtube.client import YouTubeChannelDetails, YouTubeSearchHit, YouTubeVideoDetails
from app.models.orm import CompetitionLevel
from app.services.keyword_analysis_service import KeywordAnalysisService, _competition_level


class FakeYouTubeClient:
    """Minimal stub for KeywordAnalysisService tests."""

    def __init__(self) -> None:
        self._subscribers: dict[str, int] = {}

    def search_videos_relevance(self, query: str, *, max_results: int = 20) -> list[YouTubeSearchHit]:
        now = datetime.now(timezone.utc)
        return [
            YouTubeSearchHit(
                video_id=f"vid{i}",
                channel_id=f"ch{i}",
                title=f"{query} tutorial part {i}",
                published_at=now,
            )
            for i in range(1, max_results + 1)
        ]

    def get_videos(self, video_ids: list[str]) -> list[YouTubeVideoDetails]:
        now = datetime.now(timezone.utc)
        videos: list[YouTubeVideoDetails] = []
        for index, video_id in enumerate(video_ids, start=1):
            channel_index = index
            if index <= 6:
                self._subscribers[f"ch{channel_index}"] = 12_000
            else:
                self._subscribers[f"ch{channel_index}"] = 2_000_000
            videos.append(
                YouTubeVideoDetails(
                    video_id=video_id,
                    channel_id=f"ch{channel_index}",
                    title=f"python tutorial tips {index}",
                    published_at=now,
                    views_count=100_000 * index,
                    likes_count=1_000,
                    comments_count=100,
                    duration_seconds=600,
                    tags=("python tutorial", "coding", "life hack"),
                ),
            )
        return videos

    def get_channels(self, channel_ids: list[str]) -> dict[str, YouTubeChannelDetails]:
        return {
            channel_id: YouTubeChannelDetails(
                channel_id=channel_id,
                title=f"Channel {channel_id}",
                subscribers_count=self._subscribers.get(channel_id, 100_000),
                subscribers_known=True,
            )
            for channel_id in channel_ids
        }


def test_opportunity_score_bounds() -> None:
    service = KeywordAnalysisService(FakeYouTubeClient())  # type: ignore[arg-type]
    assert service._calc_opportunity_score(90, 20) == 86
    assert service._calc_opportunity_score(10, 90) == 10
    assert service._calc_opportunity_score(50, 50) == 50


def test_competition_levels() -> None:
    assert _competition_level(80) == CompetitionLevel.HIGH
    assert _competition_level(55) == CompetitionLevel.MEDIUM
    assert _competition_level(25) == CompetitionLevel.LOW


def test_analyze_report_shape() -> None:
    service = KeywordAnalysisService(FakeYouTubeClient())  # type: ignore[arg-type]
    report = service.analyze("python tutorial")

    assert report.keyword == "python tutorial"
    assert 1 <= report.opportunity_score <= 100
    assert report.analyzed_videos == 20
    assert report.volume.total_views > 0
    assert report.competition.competition_level in CompetitionLevel
    assert report.similar_tags
    assert len(report.top_results) == 20
    assert report.recommendation


def main() -> None:
    test_opportunity_score_bounds()
    test_competition_levels()
    test_analyze_report_shape()
    print("Keyword analysis checks passed.")


if __name__ == "__main__":
    main()
