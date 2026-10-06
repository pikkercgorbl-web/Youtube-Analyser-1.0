# Stage 1.22A — Attention Engine Core

## A. Product goal

Radar already collects thousands of videos. A human should inspect **~20–50** opportunities.

Attention Engine turns **existing evidence** into three deterministic families:

1. **VIDEO_WINNER** — a concrete video worth opening
2. **PATTERN** — repeated topic/format across **independent channels**
3. **CHANNEL_MOMENTUM** — a channel whose **recent observed content** looks unusually strong vs its own previous window

It is **not** a giant table, a magic score, a success probability, an LLM niche picker, or a Breakout replacement.

Every item answers: **why was this shown?** (`reason_codes` + `human_reasons`).

Timezone: **UTC**. Window for candidate videos: `(now - window_hours, now]` (default 24h).

## B. Existing evidence reused

| Source | Use |
|--------|-----|
| `Video` / `Channel` | identity, title, topic, publish time, stored subs if &gt; 0 |
| `VideoSnapshot` | views, VPH series, subscribers when recorded |
| `KeywordDiscoveryHit` / `TargetKeyword` | provenance, 72h baseline |
| Breakout v1 (`rank_breakout_v1`, fundamental eligibility) | rank + eligibility **unchanged** |
| Channel velocity baseline (lookback-window snapshots only) | optional relative VPH |
| Horizon matcher (`match_horizon_outcome`, 72h ± 12h) | delayed outcome state |

No new YouTube HTTP. No embeddings. No LLM. No writes to Discovery / Monitoring / Keyword lifecycle.

## C. VideoWinner semantics

A window candidate becomes a winner if it has **at least one** explicit reason, then the list is **bounded**.

Sort (no composite score):

1. `breakout_rank` ascending (unranked last)
2. accelerating before other acceleration states
3. current VPH descending
4. `video_id`

Reason codes (optional, missing ≠ 0):

| Code | Meaning |
|------|---------|
| `breakout_eligible` | regular, age ≤ monitoring max (72h), VPH present |
| `breakout_high_rank` | breakout rank ≤ 20 **in this attention window** |
| `high_current_vph` | eligible VPH ≥ p75 of eligible videos in the window (needs ≥4 VPH values) |
| `small_channel_in_observed_universe` | breakout-eligible **and** known subscribers ≤ p25 of **known** subs in the window — descriptive context, **not** “this channel is exploding” |
| `channel_relative_outlier` | production-ready age-aligned baseline and VPH ≥ 2× channel median |
| `accelerating_velocity` | see §F |
| `confirmed_72h_growth` | horizon snapshot with positive view growth |

`subscribers` is `None` when snapshot subs are null **and** `Channel.subscribers_count` is 0/missing. Stored 0 is not treated as a known size.

Channel-relative v1 **only** uses snapshots already loaded for the 14-day channel lookback. If that is not production-ready, status is `unavailable` or `diagnostic` with notes. No invented thresholds beyond the existing baseline helper.

YouTube URL: `https://www.youtube.com/watch?v={video_id}` (no page fetch).

## D. Pattern semantics

Conservative grouping (prefer false negatives):

1. **Keyword provenance** — videos in the window sharing a `TargetKeyword` via hits  
2. **Title phrase** — consecutive 2–4 significant tokens after normalization  
3. **Video.topic** — only if not Jaccard-overlapping a kept title phrase (≥ 0.8)

**Requirements:** ≥2 videos **and** ≥2 channels. Ten videos from one channel is **not** a pattern.

Title-phrase merge: skip if token subset of a longer kept phrase, or Jaccard ≥ 0.8 of video sets.

Window counts (first seen = min(published_at, hit discovered_at)):

- `videos_last_24h` — (now-24h, now]
- `videos_previous_24h` — (now-48h, now-24h]
- `videos_previous_48_24h` — (now-72h, now-48h]

These are **counts**, not “viral trend” labels.

Sort: channel_count desc, breakout_video_count desc, videos_last_24h desc, video_count desc, pattern_key.

## E. ChannelMomentum semantics

Observation windows (not quality rules):

- **recent** = last **7** days of `published_at`
- **previous** = the **7** days before that  

Chosen to sit next to monitoring’s 72h horizon while still allowing a previous bucket. Documented as observation windows only.

Surface only if there is an explicit reason, e.g.:

- ≥2 recent breakout-eligible videos
- recent median VPH ≥ 1.5× previous median (each side needs ≥2 VPH points)
- ≥2 recent videos with confirmed 72h growth
- subscriber growth **only** from ≥2 `ChannelSnapshot` rows with subscribers &gt; 0 in the 14-day lookback

`subscriber_growth_available=false` ⇒ absolute/pct are null; do not claim growth.

Sort: breakout_video_count desc, confirmed_72h_count desc, VPH ratio desc, recent_video_count desc, channel_id.

## F. Missing-data semantics

| Field | Missing |
|-------|---------|
| subscribers | `null`, not 0 |
| acceleration | `unavailable` if &lt; 3 non-null VPH snapshots |
| delayed 72h | `unavailable` (no discovery views), `pending` (not matured), `missing` (matured, no snapshot in ±12h), `confirmed` / `not_confirmed` |
| channel relative | `unavailable` / `diagnostic` with notes |
| subscriber growth | `subscriber_growth_available=false` |

## G. Pattern identity (Saved Topics later)

`pattern_key` is deterministic:

- `kw:{target_keyword_id}`
- `phrase:{sha256(normalized_phrase)[:16]}`
- `topic:{sha256(normalized_topic)[:16]}`

A future **SavedTopic** should store:

1. **FROZEN SNAPSHOT** — the Pattern payload (counts, members, reasons) at save time  
2. **LIVE STATE** — latest `attention_patterns` row with the same `pattern_key` after a refresh  

Do not use random UUIDs for Pattern identity.

## H. Ranking / order

No global quality score. Families are ranked independently with the sort keys above, then truncated to `--video-limit` / `--pattern-limit` / `--channel-limit`.

The same video **may** appear as a winner **and** a pattern member **and** a channel representative.

## I. Persistence / read model

Tables (created at startup): `attention_runs`, `attention_video_winners`, `attention_patterns`, `attention_pattern_videos`, `attention_channel_momentum`.

Refresh **replaces** the previous snapshot (UI never clusters history on request).

## J. CLI

```powershell
python scripts/refresh_attention_engine.py --window-hours 24 --video-limit 50 --pattern-limit 20 --channel-limit 20
python scripts/refresh_attention_engine.py --dry-run
python scripts/refresh_attention_engine.py --dry-run --json
```

One-shot only. No always-on worker.

## K. API

Prefix `/api/attention`. Default reads the snapshot (`data_source=snapshot`). Empty snapshot → `unavailable` (no silent full recompute).

`?live=true` is diagnostic recompute only.

- `GET /summary`
- `GET /videos`
- `GET /patterns`
- `GET /patterns/{pattern_id}` (`pattern_key`)
- `GET /channels`

## L. Tests

`scripts/test_attention_engine_1_22a.py` (also in `run_fast_regressions.py`).

## M. Production findings

Dry-run on live Postgres, 24h UTC window (2026-09-30 19:03Z – 2026-10-01 19:03Z), **~105s** after lookback scoping (engine echo off).

| Metric | Count |
|--------|--------|
| Candidate videos | 16148 |
| VideoWinners (capped) | 50 |
| Patterns (capped) | 20 |
| ChannelMomentum | **0** |

ChannelMomentum is empty because almost no channel had **≥2 videos in the previous 7-day observation window** in Radar. Volume-only news/TV channels were dropped on purpose (no relative baseline).

VideoWinners are Breakout v1 ranks 1–10 with very high current VPH (not a new score).

Useful-looking patterns: Hindi “kaise banaye” AI-tutorial templates, diorama/mini-motor, compact keyword clusters (Minecraft испытания, тайны космоса). Remaining noise: overlapping Hindi ngrams (`se cartoon kaise banaye` vs `cartoon kaise banaye ai`) — stopword `se` is not in the EN/RU list.

First dry-run without the 30-video keyword cap produced 856-video “ai tools for video editing” corpus slices; those are omitted now.

## N. Known limitations

- Pattern v1 cannot see semantic synonyms (`AI NPC` vs `artificial villager`).
- Channel-relative uses lookback snapshots only, not full channel history.
- Breakout eligibility still uses the 72h monitoring age cap, so older “winners” will not rank as breakout.
- Title ngrams can still miss or over-merge; merge rules are conservative.
- Refresh can be heavy (breakout + snapshots for the window + 14d lookback); that is why the UI reads a snapshot.

## O. Next stage (1.22B)

Analyst Feed UI over the snapshot; optional Saved Topic bookmark of `pattern_key`; human feedback; **not** embeddings unless Pattern v1 is too noisy after inspection.
