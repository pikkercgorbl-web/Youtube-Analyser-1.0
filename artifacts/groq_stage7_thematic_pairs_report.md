# Stage 7 — thematic EN pairs (corrected methodology)

**Generated:** 2026-10-07 (UTC)  
**Machine-readable:** `artifacts/groq_stage7_thematic_pairs_20261007T153149Z.json` (also `groq_stage7_search_compare_latest.json`)  
**Constraints:** no LLM calls, no DB writes, no workers.

## What changed vs the flawed run

The earlier 9-search compare (`реальные истории` / `что если` / `historical mysteries` vs mixed EN LLM queries) mixed **languages and themes**. Cyrillic baselines vs English LLM queries mostly yielded **zero overlap** and **different title language pools** — that is **not** evidence that LLM queries are better.

This rerun uses **three English manual baselines** paired with **saved Groq suggestions** on the **same theme**, identical InnerTube settings per pair (`iter_radar_search_pages`, 1 page, sort by upload date, `hl=en` / `gl=US` for all six queries).

| Pair | Manual baseline | Saved LLM query | Live search | LLM page |
|------|-----------------|-----------------|-------------|----------|
| betrayal | `betrayal stories` | `real life betrayal stories` | live | reused cache |
| abandoned | `abandoned places stories` | `real stories of mysterious abandoned places` | live | reused cache |
| anime what-if | `anime what if` | `what if you have cursed energy` | live | reused cache |

**3 live InnerTube calls** this run (6 max budget).

## Summary metrics

| Pair | Intersection (page 1) | Baseline-only | LLM-only | Overlap with Groq evidence corpus |
|------|----------------------:|--------------:|---------:|----------------------------------:|
| betrayal_stories | 2 | 18 | 18 | 0 |
| abandoned_places | 7 | 13 | 13 | 0 |
| anime_what_if | 0 | 20 | 20 | 0 |

**Interpretation:** Overlap measures **query wording + ranking**, not LLM superiority. All 20 LLM-side IDs per pair are **outside** the small keyword-discovery evidence packet — **not** auto-useful finds.

### Formats (page 1, heuristic)

- **Betrayal:** both sides mostly `regular`; drama/storytime titles dominate on both pages.
- **Abandoned:** baseline includes **1× `live`** in intersection (urbex stream-style title); LLM page all `regular` in this sample — documentary/history narration titles appear on LLM-only side.
- **Anime what-if:** both pages `regular`; **zero intersection** — baseline pulls broad anime hypotheticals; LLM query narrows to **cursed energy / JJK-adjacent** and **GTA/mod** style titles on LLM-only side (theme-adjacent but not the same SERP).

Faceless suitability: only **title + format hints** (`faceless_production_format_hint_only` in JSON). **No faceless claim without watching the video.**

---

## Manual review examples (3–5 per pair)

### 1. Betrayal stories

| Role | Title | URL |
|------|-------|-----|
| Both | The Unclaimed Bride \| True Life Story \| FULL NIGERIAN MOVIE | https://www.youtube.com/watch?v=ffnI9CrYf1M |
| Both | Her Husband Left Her in Mexico—Then The Mafia Boss at the Airport Noticed Her | https://www.youtube.com/watch?v=lAzxiw2czKU |
| LLM only | My Stepmother Hates Me … Learn English With Story | https://www.youtube.com/watch?v=7draP0Fmi_k |
| LLM only | My Husband Kicked Me Out After My Dad’s Funeral—Then His Mom Demanded 50% of My House | https://www.youtube.com/watch?v=jVgjnHrJCuo |
| LLM only | How a Poor Boy Became a CEO … Emotional Love & Success Story | https://www.youtube.com/watch?v=JYjimwNV-Wc |

**Theme:** Both queries surface personal betrayal / relationship drama. LLM phrasing adds “real life” and ESL/storytime variants.  
**Irrelevant (baseline-only heuristic):** 1 title flagged (see JSON `wVyJhS7jvMg`).  
**Faceless hint:** several intersection/LLM titles look like **narrated storytime** (`regular`); verify production style manually.

### 2. Abandoned places stories

| Role | Title | URL |
|------|-------|-----|
| Both | The Strange Remains of Fort Apache Just Got Even Stranger | https://www.youtube.com/watch?v=c559xA7_WMo |
| Both | What’s Inside the Haveli? … Abandoned Haveli | https://www.youtube.com/watch?v=gZd6iGipeeo |
| LLM only | The Abandoned Dutch Cemetery That Rewrote Colonial America | https://www.youtube.com/watch?v=vo-uJri5IPo |
| LLM only | America's Secret Submarine Base: Why Connecticut Abandoned It | https://www.youtube.com/watch?v=-O7U9F7Ibbc |
| LLM only | The Most Overcrowded Sea Fortress … Abandoned Engineering | https://www.youtube.com/watch?v=ZmO62svOU14 |

**Theme:** Strong overlap (7/20) — same mystery/abandonment niche. LLM-only extras skew **history/documentary** (“Lost Histories”, “Lost Museum”).  
**Caveat:** intersection includes **live** urbex-style entry — not assumed faceless-friendly.  
**Baseline-only:** more horror-story / regional titles (see JSON analysis lists).

### 3. Anime what if ↔ cursed energy

| Role | Title | URL |
|------|-------|-----|
| LLM only | Franklin & Shinchan … Cursed … in GTA 5! | https://www.youtube.com/watch?v=vvWU1h7Eb7w |
| LLM only | (see JSON for 4 more LLM-only thematic/heuristic picks) | — |
| Baseline only | (see JSON — broad anime “what if” edits, 16 thematic heuristic on baseline page) | — |

**Theme:** Same high-level “hypothetical” lane, but **no shared video IDs** on page 1 — queries target **different sub-niches** (general anime edits vs cursed-energy/GTA).  
**Conclusion for this pair:** LLM query is **more specific**; baseline is **broader** — compare overlap alone does not rank them.

---

## Stage 7 conclusions (corrected)

1. Saved LLM English queries can retrieve **on-theme** Latin-heavy results when baselines are **English and matched by theme**.
2. **Higher overlap** (abandoned) vs **lower** (betrayal) vs **none** (anime) shows **query specificity** matters more than “LLM vs manual” label.
3. Prior RU/EN cross-topic run is **retired** as LLM advantage evidence.
4. **LLM not integrated** into Radar; Groq experiment remains offline harness only.

**Re-run:** `python scripts/groq_stage7_search_compare.py`
