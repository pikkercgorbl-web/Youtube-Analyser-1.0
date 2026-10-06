"""Pattern Family clustering (Stage 1.22B.1). Deterministic, no LLM/embeddings."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import AttentionFamilyIdentity
from app.services.attention_engine_types import (
    FLAG_BROAD_KEYWORD_GROUP,
    FLAG_CROSS_SOURCE,
    FLAG_KEYWORD_ONLY,
    FLAG_PHRASE_SUPPORTED,
    FLAG_REPEATED_TITLE_TEMPLATE,
    FLAG_TOPIC_SUPPORTED,
    FAMILY_REASON_SHARED_CHANNELS,
    FAMILY_REASON_SHARED_KEYWORDS,
    FAMILY_REASON_SHARED_VIDEOS,
    FAMILY_REASON_SINGLE_MEMBER,
    FAMILY_REASON_TOKEN_OVERLAP,
    PatternCandidate,
    PatternFamily,
    PatternKind,
)
from app.services.attention_family_tokens import family_content_tokens
from app.services.attention_title_normalization import normalize_title
from app.services.metrics import ensure_utc

_TOKEN_JACCARD = 0.5
_VIDEO_JACCARD_WITH_TOKENS = 0.15
_VIDEO_JACCARD_STRONG = 0.45
_CHANNEL_JACCARD_WITH_TOKENS = 0.2
_TOKEN_JACCARD_STRICT = 0.66
_TEMPLATE_TITLE_SHARE = 0.4
_TEMPLATE_MIN_CHANNELS = 5
_BROAD_UNIQUE_TITLE_RATIO = 0.45
_BROAD_MIN_VIDEOS = 8


def load_family_identity(session: Session) -> dict[str, str]:
    rows = session.scalars(select(AttentionFamilyIdentity)).all()
    return {row.pattern_key: row.family_key for row in rows}


def upsert_family_identity(session: Session, mapping: dict[str, str], *, now: datetime) -> None:
    """Update pattern_key → family_key. Does not commit. Does not delete unused keys."""
    stamp = ensure_utc(now)
    existing = {row.pattern_key: row for row in session.scalars(select(AttentionFamilyIdentity)).all()}
    for pattern_key, family_key in mapping.items():
        row = existing.get(pattern_key)
        if row is None:
            session.add(
                AttentionFamilyIdentity(pattern_key=pattern_key, family_key=family_key, updated_at=stamp),
            )
        elif row.family_key != family_key:
            row.family_key = family_key
            row.updated_at = stamp
    session.flush()


def _jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


class _UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


def phrase_merge_reasons(left: PatternCandidate, right: PatternCandidate) -> tuple[str, ...]:
    """Conservative phrase-sibling test. Prefer false negatives."""
    if left.kind != "title_phrase" or right.kind != "title_phrase":
        return ()
    tokens_a = family_content_tokens(left.label)
    tokens_b = family_content_tokens(right.label)
    videos_a = set(left.participating_video_ids)
    videos_b = set(right.participating_video_ids)
    channels_a = set(left.participating_channel_ids)
    channels_b = set(right.participating_channel_ids)
    keywords_a = set(left.participating_keyword_ids)
    keywords_b = set(right.participating_keyword_ids)
    tok_j = _jaccard(tokens_a, tokens_b)
    vid_j = _jaccard(videos_a, videos_b)
    ch_j = _jaccard(channels_a, channels_b)
    subset = (
        len(tokens_a) >= 2
        and len(tokens_b) >= 2
        and (tokens_a <= tokens_b or tokens_b <= tokens_a)
    )
    reasons: list[str] = []
    token_ok = tok_j >= _TOKEN_JACCARD or subset
    if token_ok and vid_j >= _VIDEO_JACCARD_WITH_TOKENS:
        reasons.append(FAMILY_REASON_TOKEN_OVERLAP)
        reasons.append(FAMILY_REASON_SHARED_VIDEOS)
    elif vid_j >= _VIDEO_JACCARD_STRONG:
        reasons.append(FAMILY_REASON_SHARED_VIDEOS)
    elif token_ok and tok_j >= _TOKEN_JACCARD_STRICT and ch_j >= _CHANNEL_JACCARD_WITH_TOKENS:
        reasons.append(FAMILY_REASON_TOKEN_OVERLAP)
        reasons.append(FAMILY_REASON_SHARED_CHANNELS)
    else:
        return ()
    if keywords_a and keywords_b and keywords_a & keywords_b:
        reasons.append(FAMILY_REASON_SHARED_KEYWORDS)
    if ch_j >= _CHANNEL_JACCARD_WITH_TOKENS and FAMILY_REASON_SHARED_CHANNELS not in reasons:
        reasons.append(FAMILY_REASON_SHARED_CHANNELS)
    return tuple(dict.fromkeys(reasons))


def cluster_pattern_keys(patterns: list[PatternCandidate]) -> list[list[PatternCandidate]]:
    by_key = {row.pattern_key: row for row in patterns}
    uf = _UnionFind(list(by_key))
    merge_notes: dict[frozenset[str], tuple[str, ...]] = {}
    phrase_rows = [row for row in patterns if row.kind == "title_phrase"]
    for i, left in enumerate(phrase_rows):
        for right in phrase_rows[i + 1 :]:
            reasons = phrase_merge_reasons(left, right)
            if reasons:
                uf.union(left.pattern_key, right.pattern_key)
                merge_notes[frozenset({left.pattern_key, right.pattern_key})] = reasons
    groups: dict[str, list[PatternCandidate]] = defaultdict(list)
    for row in patterns:
        groups[uf.find(row.pattern_key)].append(row)
    clustered = [sorted(members, key=lambda row: row.pattern_key) for members in groups.values()]
    clustered.sort(key=lambda members: (members[0].pattern_key,))
    return clustered


def mint_family_key(members: list[PatternCandidate]) -> str:
    kinds = {row.kind for row in members}
    if kinds == {"keyword_provenance"} and len(members) == 1:
        return f"family:{members[0].pattern_key}"
    if kinds == {"video_topic"} and len(members) == 1:
        return f"family:{members[0].pattern_key}"
    token_sets = [family_content_tokens(row.label) for row in members]
    intersection = set.intersection(*(set(s) for s in token_sets)) if token_sets else set()
    if len(intersection) >= 2:
        core = sorted(intersection)
    else:
        counts: dict[str, int] = defaultdict(int)
        for tokens in token_sets:
            for token in tokens:
                counts[token] += 1
        majority = max(1, (len(members) + 1) // 2)
        core = sorted(token for token, n in counts.items() if n >= majority)
        if len(core) < 2:
            core = sorted({token for tokens in token_sets for token in tokens})
    digest = hashlib.sha256("|".join(core).encode("utf-8")).hexdigest()[:16]
    kind = members[0].kind if len(kinds) == 1 else "mixed"
    return f"family:{kind}:{digest}"


def resolve_family_keys(
    clusters: list[list[PatternCandidate]],
    identity: dict[str, str],
) -> list[tuple[str, list[PatternCandidate]]]:
    """
    Reuse stored family_key when membership grows.

    Split: the larger cluster keeps a previously claimed key; the rest mint new.
    Collision of two historical keys in one cluster: keep lexicographically smallest.
    """
    sized = sorted(
        clusters,
        key=lambda members: (
            -len({vid for row in members for vid in row.participating_video_ids}),
            min(row.pattern_key for row in members),
        ),
    )
    claimed: set[str] = set()
    resolved: list[tuple[str, list[PatternCandidate]]] = []
    for members in sized:
        previous = {identity[row.pattern_key] for row in members if row.pattern_key in identity}
        available = sorted(previous - claimed)
        if available:
            family_key = available[0]
        else:
            family_key = mint_family_key(members)
            suffix = 0
            base = family_key
            while family_key in claimed:
                suffix += 1
                family_key = f"{base}:{suffix}"
        claimed.add(family_key)
        resolved.append((family_key, members))
    resolved.sort(key=lambda item: item[0])
    return resolved


def _window_counts(
    video_ids: list[str],
    first_seen: dict[str, datetime],
    *,
    now: datetime,
) -> tuple[int, int, int]:
    end = ensure_utc(now)
    last_24 = end - timedelta(hours=24)
    prev_24 = end - timedelta(hours=48)
    prev_48 = end - timedelta(hours=72)
    c_last = c_prev = c_older = 0
    for video_id in video_ids:
        seen = first_seen.get(video_id)
        if seen is None:
            continue
        seen = ensure_utc(seen)
        if last_24 < seen <= end:
            c_last += 1
        elif prev_24 < seen <= last_24:
            c_prev += 1
        elif prev_48 < seen <= prev_24:
            c_older += 1
    return c_last, c_prev, c_older


def _pick_label(members: list[PatternCandidate]) -> str:
    phrases = [row for row in members if row.kind == "title_phrase"]
    pool = phrases or members
    pool = sorted(
        pool,
        key=lambda row: (
            -len(family_content_tokens(row.label)),
            -row.video_count,
            row.label,
        ),
    )
    return pool[0].label


def _template_flag(video_ids: list[str], titles: dict[str, str], channel_count: int) -> bool:
    if channel_count < _TEMPLATE_MIN_CHANNELS or len(video_ids) < 8:
        return False
    counts: dict[str, int] = defaultdict(int)
    for video_id in video_ids:
        title = titles.get(video_id)
        if not title:
            continue
        counts[normalize_title(title)] += 1
    if not counts:
        return False
    top = max(counts.values())
    return (top / len(video_ids)) >= _TEMPLATE_TITLE_SHARE


def _broad_keyword(video_ids: list[str], titles: dict[str, str]) -> bool:
    if len(video_ids) < _BROAD_MIN_VIDEOS:
        return False
    unique = {normalize_title(titles[vid]) for vid in video_ids if vid in titles and titles[vid]}
    if not unique:
        return False
    return (len(unique) / len(video_ids)) >= _BROAD_UNIQUE_TITLE_RATIO


def _support_and_flags(
    members: list[PatternCandidate],
    all_patterns: list[PatternCandidate],
    video_ids: set[str],
    titles: dict[str, str],
    channel_count: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    family_kinds = {row.kind for row in members}
    overlapping = {
        row.kind
        for row in all_patterns
        if set(row.participating_video_ids) & video_ids
    }
    sources: list[str] = []
    flags: list[str] = []
    if "keyword_provenance" in overlapping:
        sources.append("keyword")
    if "title_phrase" in overlapping:
        sources.append("title_phrase")
        flags.append(FLAG_PHRASE_SUPPORTED)
    if "video_topic" in overlapping:
        sources.append("topic")
        flags.append(FLAG_TOPIC_SUPPORTED)
    if len(sources) >= 2:
        flags.append(FLAG_CROSS_SOURCE)
    if family_kinds == {"keyword_provenance"} and overlapping <= {"keyword_provenance"}:
        flags.append(FLAG_KEYWORD_ONLY)
        if _broad_keyword(sorted(video_ids), titles):
            flags.append(FLAG_BROAD_KEYWORD_GROUP)
    if family_kinds == {"title_phrase"} and _template_flag(sorted(video_ids), titles, channel_count):
        flags.append(FLAG_REPEATED_TITLE_TEMPLATE)
    return tuple(dict.fromkeys(sources)), tuple(dict.fromkeys(flags))


def _cluster_reasons(members: list[PatternCandidate]) -> tuple[str, ...]:
    if len(members) == 1:
        return (FAMILY_REASON_SINGLE_MEMBER,)
    collected: list[str] = []
    for i, left in enumerate(members):
        for right in members[i + 1 :]:
            collected.extend(phrase_merge_reasons(left, right))
    if not collected:
        collected.append(FAMILY_REASON_TOKEN_OVERLAP)
    return tuple(dict.fromkeys(collected))


def build_family(
    family_key: str,
    members: list[PatternCandidate],
    *,
    all_patterns: list[PatternCandidate],
    now: datetime,
    first_seen: dict[str, datetime] | None = None,
    titles: dict[str, str] | None = None,
) -> PatternFamily:
    seen = first_seen or {}
    title_map = titles or {}
    video_ids = tuple(sorted({vid for row in members for vid in row.participating_video_ids}))
    channel_ids = tuple(sorted({cid for row in members for cid in row.participating_channel_ids}))
    keyword_ids = tuple(sorted({kid for row in members for kid in row.participating_keyword_ids}))
    breakout = len(
        {
            vid
            for row in members
            for vid in row.participating_video_ids
            if row.breakout_video_count and vid in row.participating_video_ids
        },
    )
    # Unique videos that sit in at least one member marked breakout-eligible cannot
    # be recovered per-id; use max unique bound via union of member breakout counts
    # only when each member's videos are disjoint. Prefer union of flags from members
    # that store only counts — approximate: min(len(video_ids), sum(breakout counts))
    # is inflationary. Use: videos that appear in members where breakout_video_count == video_count.
    eligible: set[str] = set()
    for row in members:
        if row.breakout_video_count <= 0:
            continue
        if row.breakout_video_count >= row.video_count:
            eligible.update(row.participating_video_ids)
        else:
            # cannot know which ids; do not invent. Count unique videos from fully-eligible members only,
            # else keep member's count as independent unknown — use max of (union-full, min(sum, unique))
            pass
    if not eligible:
        breakout_count = min(
            len(video_ids),
            max((row.breakout_video_count for row in members), default=0),
        )
    else:
        breakout_count = len(eligible)
        extra = sum(row.breakout_video_count for row in members if row.breakout_video_count < row.video_count)
        if extra:
            breakout_count = min(len(video_ids), breakout_count + extra)
    last_24, prev_24, prev_48 = _window_counts(list(video_ids), seen, now=now)
    kinds: set[str] = {row.kind for row in members}
    family_kind: PatternKind = members[0].kind if len(kinds) == 1 else members[0].kind
    support, flags = _support_and_flags(members, all_patterns, set(video_ids), title_map, len(channel_ids))
    seen_times = [seen[vid] for vid in video_ids if vid in seen]
    return PatternFamily(
        family_key=family_key,
        label=_pick_label(members),
        family_kind=family_kind,
        member_pattern_keys=tuple(row.pattern_key for row in sorted(members, key=lambda r: r.pattern_key)),
        member_labels=tuple(row.label for row in sorted(members, key=lambda r: r.pattern_key)),
        video_ids=video_ids,
        channel_ids=channel_ids,
        keyword_ids=keyword_ids,
        video_count=len(video_ids),
        channel_count=len(channel_ids),
        keyword_count=len(keyword_ids),
        breakout_eligible_count=breakout_count,
        videos_last_24h=last_24,
        videos_previous_24h=prev_24,
        videos_previous_48_24h=prev_48,
        grouping_reasons=_cluster_reasons(members),
        quality_flags=flags,
        support_sources=support,
        first_seen_at=min(seen_times) if seen_times else min((row.first_seen_at for row in members if row.first_seen_at), default=None),
        latest_seen_at=max(seen_times) if seen_times else max((row.latest_seen_at for row in members if row.latest_seen_at), default=None),
    )


def sort_families(families: list[PatternFamily]) -> list[PatternFamily]:
    return sorted(
        families,
        key=lambda row: (
            -row.channel_count,
            -len(row.support_sources),
            -row.breakout_eligible_count,
            -row.videos_last_24h,
            -row.video_count,
            row.family_key,
        ),
    )


def build_pattern_families(
    patterns: list[PatternCandidate] | tuple[PatternCandidate, ...],
    *,
    now: datetime,
    identity: dict[str, str] | None = None,
    first_seen: dict[str, datetime] | None = None,
    titles: dict[str, str] | None = None,
) -> tuple[list[PatternFamily], dict[str, str]]:
    rows = list(patterns)
    clusters = cluster_pattern_keys(rows)
    assigned = resolve_family_keys(clusters, identity or {})
    families: list[PatternFamily] = []
    next_identity: dict[str, str] = dict(identity or {})
    for family_key, members in assigned:
        families.append(
            build_family(
                family_key,
                members,
                all_patterns=rows,
                now=now,
                first_seen=first_seen,
                titles=titles,
            ),
        )
        for member in members:
            next_identity[member.pattern_key] = family_key
    return sort_families(families), next_identity
