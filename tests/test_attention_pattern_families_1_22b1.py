"""Stage 1.22B.1 Pattern Family clustering."""

from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.attention_engine_types import PatternCandidate
from app.services.attention_family_tokens import family_content_tokens
from app.services.attention_pattern_families import (
    build_pattern_families,
    mint_family_key,
    phrase_merge_reasons,
    resolve_family_keys,
    cluster_pattern_keys,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _pattern(
    *,
    key: str,
    kind: str,
    label: str,
    videos: tuple[str, ...],
    channels: tuple[str, ...],
    keywords: tuple[int, ...] = (),
    breakout: int = 0,
) -> PatternCandidate:
    return PatternCandidate(
        pattern_key=key,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        video_count=len(videos),
        channel_count=len(channels),
        keyword_count=len(keywords),
        breakout_video_count=breakout,
        small_channel_winner_count=0,
        first_seen_at=NOW,
        latest_seen_at=NOW,
        videos_last_24h=1,
        videos_previous_24h=0,
        videos_previous_48_24h=0,
        participating_video_ids=videos,
        participating_channel_ids=channels,
        participating_keyword_ids=keywords,
        reason_codes=("multi_video_evidence",),
        human_reasons=("related videos",),
    )


def test_reordered_phrase_siblings_merge() -> None:
    shared = tuple(f"v{i}" for i in range(8))
    extra_a = ("va1", "va2")
    extra_b = ("vb1", "vb2")
    a = _pattern(
        key="phrase:a",
        kind="title_phrase",
        label="ai se kaise banaye",
        videos=shared + extra_a,
        channels=tuple(f"c{i}" for i in range(6)),
        keywords=(1,),
    )
    b = _pattern(
        key="phrase:b",
        kind="title_phrase",
        label="banaye ai se cartoon",
        videos=shared + extra_b,
        channels=tuple(f"c{i}" for i in range(2, 8)),
        keywords=(1,),
    )
    assert phrase_merge_reasons(a, b)
    families, _ = build_pattern_families([a, b], now=NOW)
    assert len(families) == 1
    assert set(families[0].member_pattern_keys) == {"phrase:a", "phrase:b"}
    assert families[0].video_count == 12
    assert families[0].channel_count == 8


def test_unrelated_phrases_do_not_merge() -> None:
    a = _pattern(
        key="phrase:ai",
        kind="title_phrase",
        label="ai se kaise banaye",
        videos=tuple(f"a{i}" for i in range(6)),
        channels=tuple(f"ca{i}" for i in range(6)),
    )
    b = _pattern(
        key="phrase:dio",
        kind="title_phrase",
        label="diorama making mini motor",
        videos=tuple(f"d{i}" for i in range(6)),
        channels=tuple(f"cd{i}" for i in range(6)),
    )
    assert not phrase_merge_reasons(a, b)
    families, _ = build_pattern_families([a, b], now=NOW)
    assert len(families) == 2


def test_overlapping_videos_and_channels_deduped() -> None:
    a = _pattern(
        key="phrase:a",
        kind="title_phrase",
        label="cartoon kaise banaye ai",
        videos=("v1", "v2", "v3"),
        channels=("c1", "c2"),
        keywords=(1, 2),
        breakout=3,
    )
    b = _pattern(
        key="phrase:b",
        kind="title_phrase",
        label="ai se kaise banaye",
        videos=("v2", "v3", "v4"),
        channels=("c2", "c3"),
        keywords=(2, 3),
        breakout=3,
    )
    families, _ = build_pattern_families([a, b], now=NOW)
    fam = families[0]
    assert fam.video_count == 4
    assert fam.channel_count == 3
    assert fam.keyword_count == 3
    assert set(fam.video_ids) == {"v1", "v2", "v3", "v4"}


def test_repeated_title_template_flag_stays_visible() -> None:
    videos = tuple(f"d{i}" for i in range(10))
    channels = tuple(f"ch{i}" for i in range(8))
    row = _pattern(
        key="phrase:dio",
        kind="title_phrase",
        label="diorama making mini motor",
        videos=videos,
        channels=channels,
    )
    titles = {vid: "Diy diorama making mini motor water pump science project" for vid in videos[:8]}
    titles[videos[8]] = "other diorama clip"
    titles[videos[9]] = "another diorama clip"
    families, _ = build_pattern_families([row], now=NOW, titles=titles)
    assert len(families) == 1
    assert "repeated_title_template" in families[0].quality_flags
    assert families[0].video_count == 10


def test_keyword_only_stays_separate() -> None:
    kw = _pattern(
        key="kw:136",
        kind="keyword_provenance",
        label="Minecraft испытания",
        videos=tuple(f"m{i}" for i in range(10)),
        channels=tuple(f"mc{i}" for i in range(10)),
        keywords=(136,),
    )
    phrase = _pattern(
        key="phrase:dio",
        kind="title_phrase",
        label="diorama making mini motor",
        videos=tuple(f"d{i}" for i in range(6)),
        channels=tuple(f"dc{i}" for i in range(6)),
    )
    titles = {f"m{i}": f"unrelated title {i} extra words here" for i in range(10)}
    families, _ = build_pattern_families([kw, phrase], now=NOW, titles=titles)
    assert len(families) == 2
    minecraft = next(row for row in families if "Minecraft" in row.label)
    assert "keyword_only" in minecraft.quality_flags
    assert "broad_keyword_group" in minecraft.quality_flags


def test_cross_source_support_exposed() -> None:
    videos = tuple(f"s{i}" for i in range(6))
    phrase = _pattern(
        key="phrase:space",
        kind="title_phrase",
        label="тайны космоса факты",
        videos=videos,
        channels=tuple(f"sc{i}" for i in range(5)),
        keywords=(133,),
    )
    kw = _pattern(
        key="kw:133",
        kind="keyword_provenance",
        label="тайны космоса",
        videos=videos,
        channels=tuple(f"sc{i}" for i in range(5)),
        keywords=(133,),
    )
    families, _ = build_pattern_families([phrase, kw], now=NOW)
    phrase_fam = next(row for row in families if row.family_kind == "title_phrase")
    assert "keyword" in phrase_fam.support_sources
    assert "title_phrase" in phrase_fam.support_sources
    assert "cross_source_supported" in phrase_fam.quality_flags
    assert len(families) == 2


def test_family_key_deterministic() -> None:
    row = _pattern(
        key="phrase:x",
        kind="title_phrase",
        label="ai se kaise banaye",
        videos=("v1", "v2"),
        channels=("c1", "c2"),
    )
    a = mint_family_key([row])
    b = mint_family_key([row])
    assert a == b
    assert a.startswith("family:")


def test_family_key_stable_when_membership_grows() -> None:
    shared = tuple(f"v{i}" for i in range(8))
    a = _pattern(key="phrase:a", kind="title_phrase", label="ai se kaise banaye", videos=shared + ("a1",), channels=tuple(f"c{i}" for i in range(6)))
    b = _pattern(key="phrase:b", kind="title_phrase", label="cartoon kaise banaye ai", videos=shared + ("b1",), channels=tuple(f"c{i}" for i in range(1, 7)))
    families1, identity = build_pattern_families([a, b], now=NOW)
    key = families1[0].family_key
    c = _pattern(key="phrase:c", kind="title_phrase", label="long ai kaise banaye", videos=shared + ("c1",), channels=tuple(f"c{i}" for i in range(2, 8)))
    families2, identity2 = build_pattern_families([a, b, c], now=NOW, identity=identity)
    assert len(families2) == 1
    assert families2[0].family_key == key
    assert identity2["phrase:c"] == key


def test_original_pattern_keys_preserved() -> None:
    a = _pattern(key="phrase:keep", kind="title_phrase", label="ai se kaise banaye", videos=("v1", "v2", "v3", "v4"), channels=("c1", "c2", "c3"))
    families, _ = build_pattern_families([a], now=NOW)
    assert families[0].member_pattern_keys == ("phrase:keep",)


def test_no_llm_embeddings_http_or_score() -> None:
    src = inspect.getsource(sys.modules["app.services.attention_pattern_families"])
    assert "openai" not in src.lower()
    assert "httpx" not in src
    assert "from app.integrations.youtube" not in src
    assert "composite_score" not in src
    assert "opportunity_probability" not in src


def test_content_tokens_drop_particles_keep_banaye() -> None:
    tokens = family_content_tokens("ai se kaise banaye")
    assert "se" not in tokens
    assert "kaise" not in tokens
    assert "banaye" in tokens
    assert "ai" in tokens


def test_resolve_uses_existing_identity() -> None:
    a = _pattern(key="p1", kind="title_phrase", label="ai se kaise banaye", videos=("v1", "v2", "v3"), channels=("c1", "c2"))
    clusters = cluster_pattern_keys([a])
    resolved = resolve_family_keys(clusters, {"p1": "family:kept"})
    assert resolved[0][0] == "family:kept"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("Passed family tests")
