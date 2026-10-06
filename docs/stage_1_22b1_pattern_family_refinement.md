# Stage 1.22B.1 — Pattern Family Refinement

## A. Problem

Title-phrase Pattern rows are order-sensitive. Production showed sibling Hindi tutorial phrases as five cards, template diorama repetition, and broad keyword provenance groups.

## B. Family definition

`PatternFamily` is an aggregation over **kept Pattern rows**. Original `pattern_key` rows are not deleted. Every pattern belongs to exactly one family (possibly a singleton).

## C. Stable identity

`family_key` is deterministic and bookmarkable.

1. **Persistent map** `attention_family_identity`: `pattern_key → family_key` survives snapshot replace.
2. When membership **grows**, members reuse the existing `family_key`.
3. If two historical keys collide in one cluster, keep the lexicographically smallest unused key.
4. On **split**, the larger cluster keeps a claimed key; the rest mint a new key.
5. First mint:
   - keyword singleton: `family:kw:{id}`
   - topic singleton: `family:topic:{digest}`
   - phrase cluster: `family:title_phrase:{sha256(sorted core tokens)[:16]}` where core is the intersection of content tokens if size ≥ 2, else majority tokens.

Not a random UUID.

## D. Merge rules

Only **title_phrase** rows may merge. Conservative, prefer false negatives.

Merge if:

- content-token Jaccard ≥ 0.5 or token subset (len ≥ 2) **and** video Jaccard ≥ 0.15, or
- video Jaccard ≥ 0.45, or
- token Jaccard ≥ 0.66 **and** channel Jaccard ≥ 0.2

Reasons: `high_token_overlap`, `shared_video_membership`, `shared_channel_membership`, `shared_keyword_context`.

Keyword and topic families stay separate (cross-source is support, not merge).

## E. Generic token handling

Comparison-only particles (`se`, `kaise`, `ko`, `ki`, …). Stored labels unchanged. Verbs like `banaye` and topical nouns stay.

## F. Cross-source support

`support_sources` is a list (`keyword`, `title_phrase`, `topic`) from overlapping member videos. No numeric score. Flag `cross_source_supported` when ≥ 2 sources.

## G. Template-pattern semantics

`repeated_title_template` if ≥ 40% of unique videos share the same normalized title and ≥ 5 channels. **Not hidden.**

## H. Keyword-only semantics

`keyword_only` if the family is keyword provenance and videos do not overlap phrase/topic patterns. `broad_keyword_group` if unique normalized titles / videos ≥ 0.45 and ≥ 8 videos. Not “invalid”.

## I. Read model

Computed in `refresh_attention_engine` / `compute_attention_engine`. Tables:

- `attention_pattern_families`
- `attention_pattern_family_members`
- `attention_pattern_family_videos`
- `attention_family_identity` (not wiped on snapshot replace)

Parent `attention_runs` flushed first. Helper does not commit.

## J. API

- `GET /api/attention/pattern-families`
- `GET /api/attention/pattern-families/{family_key}`

Existing `/patterns` remain for audit. Default snapshot, no live recompute.

## K. UI

`/opportunities` shows family cards. Detail: `/opportunities/families/{family_key}`. “Показать исходные паттерны” links to `/opportunities/patterns/{pattern_key}`.

## L. SavedTopic preparation

Bookmark hook uses `family_key`. No persistence yet.

## M. Tests

`scripts/test_attention_pattern_families_1_22b1.py` plus frontend feed tests.

## N. Production findings

Refresh `attention_20261001T200000Z`:

- Before: **20 Pattern** rows
- After: **17 PatternFamilies** over the same 20 patterns (3 sibling merges into one 4-member family; `long ai kaise banaye` stayed a singleton — conservative false negative)

AI / kaise family `family:title_phrase:3195a35ca30d277c` label `cartoon kaise banaye ai`:

- members: `ai se kaise banaye`, `se cartoon kaise banaye`, `cartoon kaise banaye ai`, `banaye ai se cartoon`
- 74 unique videos / 73 channels
- reasons: token overlap + shared videos/channels/keywords

Diorama: visible singleton, flag `repeated_title_template`, 78/40.

Minecraft испытания: singleton keyword family, `phrase_supported` + `cross_source_supported` (videos also overlap a title-phrase pattern). Not keyword_only.

тайны космоса: singleton, `topic_supported` + `cross_source_supported` (`keyword` + `topic`).

Warm `/opportunities` snapshot APIs (summary+videos+families+channels): ~1.3s after warmup. Family detail hydrate ~2s.

Attention refresh wall time ~105s (similar to prior evidence-load dominated run; family clustering is not the bottleneck).

## O. Limitations

- Families cover only the bounded Pattern list (pattern_limit), not all ngrams.
- Breakout-eligible unique count is approximate when only member totals exist.
- Split of a family mints a new key for the smaller side.
- Particles are a conservative list, not a language model.

## P. Next stage 1.22C

Saved Topics: frozen snapshot + live state + history + user status + notes, keyed by `family_key`.
