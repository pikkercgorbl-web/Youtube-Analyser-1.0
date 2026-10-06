"""Deterministic Pattern v1 grouping (Stage 1.22A). No embeddings or LLM."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.services.attention_engine_types import (
    REASON_BREAKOUT_MEMBERS,
    REASON_CHANNEL_DIVERSITY,
    REASON_KEYWORD_PROVENANCE,
    REASON_MULTI_VIDEO,
    REASON_RECENT_ACTIVITY,
    REASON_TITLE_PHRASE,
    REASON_VIDEO_TOPIC,
    AttentionEngineConfig,
    PatternCandidate,
    VideoWinner,
)
from app.services.attention_evidence import AttentionEvidenceBundle, AttentionVideoRecord
from app.services.attention_title_normalization import (
    keyword_pattern_key,
    normalize_title,
    phrase_pattern_key,
    title_ngrams,
    topic_pattern_key,
)
from app.services.metrics import ensure_utc

_PHRASE_JACCARD_MERGE = 0.8


def _first_seen(rec: AttentionVideoRecord) -> datetime | None:
    times: list[datetime] = []
    if rec.video.published_at is not None:
        times.append(ensure_utc(rec.video.published_at))
    for hit in rec.hits:
        times.append(ensure_utc(hit.discovered_at))
    if not times:
        return None
    return min(times)


def _window_counts(
    recs: list[AttentionVideoRecord],
    *,
    now: datetime,
) -> tuple[int, int, int]:
    end = ensure_utc(now)
    last_24 = end - timedelta(hours=24)
    prev_24 = end - timedelta(hours=48)
    prev_48 = end - timedelta(hours=72)
    c_last = c_prev = c_older = 0
    for rec in recs:
        seen = _first_seen(rec)
        if seen is None:
            continue
        if last_24 < seen <= end:
            c_last += 1
        elif prev_24 < seen <= last_24:
            c_prev += 1
        elif prev_48 < seen <= prev_24:
            c_older += 1
    return c_last, c_prev, c_older


def _small_channel_ids(winners: list[VideoWinner]) -> set[str]:
    return {
        row.video_id
        for row in winners
        if "small_channel_in_observed_universe" in row.reason_codes
    }


def _build_pattern(
    *,
    pattern_key: str,
    kind: str,
    label: str,
    recs: list[AttentionVideoRecord],
    extra_reason: str,
    extra_human: str,
    small_ids: set[str],
    now: datetime,
) -> PatternCandidate | None:
    video_ids = tuple(sorted({rec.video.id for rec in recs}))
    channel_ids = tuple(sorted({rec.video.channel_id for rec in recs if rec.video.channel_id}))
    keyword_ids = tuple(sorted({hit.keyword_id for rec in recs for hit in rec.hits}))
    if len(video_ids) < 2 or len(channel_ids) < 2:
        return None
    breakout_n = sum(1 for rec in recs if rec.breakout_eligible)
    small_n = sum(1 for rec in recs if rec.video.id in small_ids)
    seen_times = [t for rec in recs if (t := _first_seen(rec)) is not None]
    last_24, prev_24, prev_48 = _window_counts(recs, now=now)
    codes: list[str] = [REASON_MULTI_VIDEO, REASON_CHANNEL_DIVERSITY, extra_reason]
    humans: list[str] = [
        f"{len(video_ids)} related videos",
        f"{len(channel_ids)} independent channels",
        extra_human,
    ]
    if breakout_n:
        codes.append(REASON_BREAKOUT_MEMBERS)
        humans.append(f"{breakout_n} breakout-eligible videos")
    if last_24:
        codes.append(REASON_RECENT_ACTIVITY)
        humans.append(f"{last_24} videos first seen in the last 24h")
    return PatternCandidate(
        pattern_key=pattern_key,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        video_count=len(video_ids),
        channel_count=len(channel_ids),
        keyword_count=len(keyword_ids),
        breakout_video_count=breakout_n,
        small_channel_winner_count=small_n,
        first_seen_at=min(seen_times) if seen_times else None,
        latest_seen_at=max(seen_times) if seen_times else None,
        videos_last_24h=last_24,
        videos_previous_24h=prev_24,
        videos_previous_48_24h=prev_48,
        participating_video_ids=video_ids,
        participating_channel_ids=channel_ids,
        participating_keyword_ids=keyword_ids,
        reason_codes=tuple(dict.fromkeys(codes)),
        human_reasons=tuple(humans),
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def _phrase_token_set(phrase: str) -> frozenset[str]:
    return frozenset(phrase.split())


def _should_skip_phrase(phrase: str, vids: set[str], kept: list[tuple[str, set[str]]]) -> bool:
    tokens = _phrase_token_set(phrase)
    for other_phrase, other_vids in kept:
        other_tokens = _phrase_token_set(other_phrase)
        if tokens <= other_tokens or other_tokens <= tokens:
            return True
        if _jaccard(vids, other_vids) >= _PHRASE_JACCARD_MERGE:
            return True
    return False


def build_pattern_candidates(
    bundle: AttentionEvidenceBundle,
    config: AttentionEngineConfig,
    *,
    winners: list[VideoWinner],
    now: datetime,
) -> list[PatternCandidate]:
    """
    Conservative grouping: keyword provenance, then title ngrams, then Video.topic.

    Prefers false negatives. Requires ≥2 videos and ≥2 channels.
    Title phrases are merged when token-subset or Jaccard ≥ 0.8.
    """
    records = bundle.records
    small_ids = _small_channel_ids(winners)
    patterns: list[PatternCandidate] = []
    used_keys: set[str] = set()

    for keyword_id, hits in bundle.hits_by_keyword.items():
        recs = [
            records[hit.video_id]
            for hit in hits
            if hit.video_id in records
        ]
        recs = list({rec.video.id: rec for rec in recs}.values())
        if len(recs) > config.max_keyword_pattern_videos:
            continue
        label = bundle.keyword_text.get(keyword_id, f"keyword {keyword_id}")
        row = _build_pattern(
            pattern_key=keyword_pattern_key(keyword_id),
            kind="keyword_provenance",
            label=label,
            recs=recs,
            extra_reason=REASON_KEYWORD_PROVENANCE,
            extra_human=f"shared TargetKeyword provenance: {label}",
            small_ids=small_ids,
            now=now,
        )
        if row is not None:
            patterns.append(row)
            used_keys.add(row.pattern_key)

    phrase_videos: dict[str, set[str]] = defaultdict(set)
    for rec in records.values():
        for phrase in title_ngrams(rec.video.title, min_n=2, max_n=4):
            phrase_videos[phrase].add(rec.video.id)

    phrase_rows: list[tuple[str, set[str]]] = []
    for phrase, vids in phrase_videos.items():
        channels = {records[vid].video.channel_id for vid in vids if vid in records}
        if len(vids) < config.min_pattern_videos or len(channels) < config.min_pattern_channels:
            continue
        phrase_rows.append((phrase, vids))
    phrase_rows.sort(key=lambda item: (-len(item[0].split()), -len(item[1]), item[0]))

    kept_phrases: list[tuple[str, set[str]]] = []
    for phrase, vids in phrase_rows:
        if _should_skip_phrase(phrase, vids, kept_phrases):
            continue
        kept_phrases.append((phrase, vids))

    kept_video_sets = [vids for _, vids in kept_phrases]
    for phrase, vids in kept_phrases:
        recs = [records[vid] for vid in vids if vid in records]
        row = _build_pattern(
            pattern_key=phrase_pattern_key(phrase),
            kind="title_phrase",
            label=phrase,
            recs=recs,
            extra_reason=REASON_TITLE_PHRASE,
            extra_human=f'shared normalized title phrase "{phrase}"',
            small_ids=small_ids,
            now=now,
        )
        if row is not None:
            patterns.append(row)

    kept_labels = {normalize_title(p.label) for p in patterns}
    topic_videos: dict[str, set[str]] = defaultdict(set)
    topic_label: dict[str, str] = {}
    for rec in records.values():
        topic = (rec.video.topic or "").strip()
        if not topic:
            continue
        key = topic_pattern_key(topic)
        topic_videos[key].add(rec.video.id)
        topic_label[key] = topic
    for key, vids in topic_videos.items():
        recs = [records[vid] for vid in vids if vid in records]
        if len(recs) > config.max_keyword_pattern_videos:
            continue
        if normalize_title(topic_label[key]) in kept_labels:
            continue
        if any(_jaccard(vids, other) >= _PHRASE_JACCARD_MERGE for other in kept_video_sets):
            continue
        row = _build_pattern(
            pattern_key=key,
            kind="video_topic",
            label=topic_label[key],
            recs=recs,
            extra_reason=REASON_VIDEO_TOPIC,
            extra_human=f'shared Video.topic "{topic_label[key]}"',
            small_ids=small_ids,
            now=now,
        )
        if row is not None and row.pattern_key not in used_keys:
            patterns.append(row)

    def sort_key(item: PatternCandidate) -> tuple:
        return (
            -item.channel_count,
            -item.breakout_video_count,
            -item.videos_last_24h,
            -item.video_count,
            item.pattern_key,
        )

    patterns.sort(key=sort_key)
    return patterns[: config.pattern_limit]
