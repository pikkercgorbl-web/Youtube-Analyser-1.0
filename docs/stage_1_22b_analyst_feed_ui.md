# Stage 1.22B — Analyst Feed UI

## A. Product goal

Give one analyst a daily workspace to inspect thousands of collected videos through a small set of persisted Attention signals:

- 🔥 Winners
- 📈 Patterns
- 🌱 Rising Channels
- 📋 Today’s top videos (full VideoWinner snapshot)

Typical review: 15–30 minutes. This stage is **UI + snapshot read-path only**. No Attention recompute, LLM, embeddings, YouTube HTTP, Breakout / Monitoring / Discovery / lifecycle changes.

## B. Route / navigation

- Route: `/opportunities`
- Pattern detail: `/opportunities/patterns/[pattern_key]` (`pattern_key` URL-encoded)
- Sidebar Radar item **Возможности** (first in the Radar group)
- Supporting views unchanged: Пул ключей, Производительность ключей, Мониторинг, Операции

## C. Main page layout

1. Header + snapshot freshness (`computed_at`, `source=snapshot`, window, candidate count)
2. Summary cards: Winners, Patterns, Rising Channels, 72h confirmed (count of top videos with `delayed_outcome_state=confirmed`)
3. Winner preview (~8 cards)
4. Full today’s top table
5. All pattern cards
6. Rising channels (or insufficient-history copy)

## D. Winners

Preview cards + full table of persisted `GET /api/attention/videos`. Title/thumbnail open `https://www.youtube.com/watch?v={id}`. Unknown subscribers are not shown as 0. Badges only from `reason_codes` / stored states. Client-side search/sort only.

## E. Patterns

`GET /api/attention/patterns` renders **all** snapshot patterns. Channel diversity is the primary metric. Grouping source is labeled, not merged. `breakout-eligible` is shown as membership in the Breakout **sample**, never as “breakout winner”.

## F. Pattern detail

`GET /api/attention/patterns/{pattern_key}` returns the snapshot pattern plus a **read-path hydrate** of every participating video from existing `Video` / latest `VideoSnapshot` / Channel rows. Winner overlay is applied when the video is in the persisted top. Related TargetKeyword labels and participating channels are included. Filters: channel, in-today’s-top vs rest, VPH/views/newest. Technical accordion: `pattern_key`, `kind`, keyword IDs.

Hydration does **not** call `compute_attention_engine`.

## G. Rising Channels

`GET /api/attention/channels`. Empty list uses insufficient-history copy (not “нет каналов”). When rows exist, expand inline: windows, representative videos, reasons. Subscriber growth only if `subscriber_growth_available`.

## H. Snapshot semantics

Default APIs read the persisted Attention snapshot. The UI never passes `live=true`. Freshness is age of `computed_at`, not a live ticker.

## I. Performance

`/opportunities` fires four snapshot GETs in parallel (`summary`, `videos`, `patterns`, `channels`). No Breakout recompute, no full corpus scan in the frontend. Pattern detail hydrates only member IDs (bounded latest-snapshot lookup).

## J. Empty / error states

| State | UI |
|-------|----|
| `data_source=unavailable` | “Attention Engine ещё не рассчитан.” + CLI hint |
| API error | retry |
| Patterns empty | ordinary empty copy |
| Channels empty | insufficient history |

## K. Saved Topics hook

`frontend/src/lib/saved-topics.ts` — disabled Сохранить control, tooltip “Закладки будут подключены на следующем этапе”. **No localStorage.** Identity = backend `pattern_key`. Stage 1.22C must add Frozen Snapshot + Live State + History + user status + notes/tags.

## L. Tests

- Frontend: `attention-format.test.ts`, `opportunities-dashboard.test.tsx`, sidebar IA
- Backend: `scripts/test_attention_feed_1_22b.py` (detail hydrate, no live compute)

## M. Production observations

Against persisted snapshot `attention_20261001T192246Z` (source=snapshot, window 24h, 14 553 candidates):

| Surface | Measurement |
|---------|-------------|
| `GET /opportunities` first compile | ~1.8s HTML 200 (Next compile) |
| Warm HTML `/opportunities` | **~130ms** |
| 4 snapshot APIs in parallel (warm) | **~1.3s** (each ~1.2–1.3s; cold after uvicorn reload ~31s) |
| Winners rendered | **50** |
| Patterns rendered | **20** |
| Rising Channels | **0 rows** → insufficient-history copy |
| Pattern detail hydrate | **~2.0–3.0s** per inspected pattern |

The UI does not pass `live=true`. Channel momentum remains empty because comparable previous-window history is still missing.

## N. Pattern-quality findings

Manual inspection (no grouping changes):

1. **ai se kaise banaye** (title phrase, 57 videos / 56 channels) — coherent Hindi/English “how to make AI video/cartoon” cluster. Closely overlaps sibling phrases (`se cartoon kaise banaye`, `cartoon kaise banaye ai`, `banaye ai se cartoon`, `long ai kaise banaye`). Strong channel diversity; useful as a family, redundant as five cards.
2. **diorama making mini motor** (title phrase, 78 / 40) — titles are nearly identical DIY diorama/mini-motor science-project copies. High video_count, weaker uniqueness; channel diversity (40) still shows spread of uploaders of the same template.
3. **Minecraft испытания** (keyword provenance, 25 / 25) — mixed Minecraft-adjacent and off-topic (GTA, Poppy Playtime, Cobblemon). Keyword provenance is **not** a tight semantic niche. Diversity is high but research value is uneven.
4. **тайны космоса** (keyword provenance, 24 / 23) — mostly space/science explainers, with some off-cluster items (audiobook, fringe cosmology). Better than Minecraft keyword group, still noisy.

Recommendation: keep groups unmerged in UI; 1.22B.1 should consider title-phrase near-duplicate families **after** more evidence, and tighter keyword-provenance quality later.

## O. Recommended 1.22B.1 / 1.22C

- **1.22B.1** Pattern Refinement only after audit evidence (duplicate title-phrase families).
- **1.22C** Saved Topics persistence (not browser-only bookmarks).
