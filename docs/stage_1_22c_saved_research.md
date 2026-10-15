# Stage 1.22C — Saved Research (SavedVideo + SavedFamily)

## A. Product correction

Saved Research is **not** “Saved Topics only”. Analysts bookmark:

- **SavedVideo** — one exact winner / signal combination.
- **SavedFamily** — a broader PatternFamily (topic/format market pattern).

Legacy `/api/saved-topics` and `saved_topics` tables remain for 1.22D validation; new UX uses `/saved` and `/api/saved-videos` + `/api/saved-families`.

## B–D. Semantics

| Entity | Question it answers | Unique key |
|--------|---------------------|------------|
| SavedVideo | “What happened to **this video** after I saved it?” | `video_id` (one active row; archive + restore) |
| SavedFamily | “What happened to **this family** after I saved it?” | `family_key` (must exist in current Attention snapshot at save time) |

Shared user metadata: `status` (`WATCHING` | `WANT_TO_TEST` | `TESTING` | `DROPPED`), `notes`, `tags_json`, `archived_at`, timestamps. **Radar never auto-updates status.**

Russian UI labels: Наблюдаю / Хочу протестировать / Тестирую / Отбросил.

## E. Frozen snapshots

Built **server-side** at save from persisted Attention snapshot (+ canonical `Video` / `Channel` for identity). Frontend does not assemble analytics JSON.

- **Video:** identity, winner evidence (or canonical fallback), keyword/topic context, **family memberships at save time** (label + family_key).
- **Family:** full `build_frozen_snapshot` payload (patterns, counts, breakout evidence, support/quality flags).

Frozen columns / JSON are **immutable** after insert; PATCH cannot change them.

## F–G. Live state & history

- **Live** = latest row in `saved_*_observations` (not a recompute).
- **History** = append-only observations; unique `(saved_*_id, attention_run_id)`.

Video observation when absent from winners: `video_present_in_attention=false`, message *«Видео не входит в текущую выборку Attention Engine.»* — still may set views/VPH from latest `VideoSnapshot` (`monitoring_snapshot_available`).

Family absence: `family_present=false`, *«Тема не представлена в текущей выборке Attention Engine»* — **not** “dead” or “failed”.

## H. Video ↔ Family context

`families_for_video()` derives related families from persisted snapshot membership. Opportunities winner cards show **Связанные темы** with open + save-family actions.

## I. Archive / restore

`archived_at` set on archive; archived rows skip future observation append; restore re-enables and may backfill current-run observation if missing.

## J. Transaction safety & Attention integration

**Save:** `Saved*` row + initial observation in one DB transaction (API commit); failure rolls back both.

**Attention refresh** (`persist_attention_result` in `attention_read_model.py`):

1. Replace Attention snapshot (add/flush, no commit inside helper).
2. `append_saved_topic_observations_for_result` (legacy).
3. `append_saved_research_observations_for_result` (SavedVideo + SavedFamily).

Owner (e.g. `refresh_attention_engine.py`) **commits once**. If observation append fails before commit, entire publication rolls back with the session.

Helpers: add/flush only — **no commit/rollback** inside observation appenders.

## K. API

| Method | Path |
|--------|------|
| POST | `/api/saved-videos` `{ "video_id" }` |
| GET | `/api/saved-videos` |
| GET/PATCH | `/api/saved-videos/{id}` |
| POST | `/api/saved-videos/{id}/archive` \| `/restore` |
| GET | `/api/saved-videos/{id}/history` |
| POST | `/api/saved-families` `{ "family_key" }` |
| GET | `/api/saved-families` … (mirror) |

PATCH: `status`, `notes`, `tags` only.

## L. UI

- Nav: **Сохранённое** → `/saved` (tabs Видео / Темы).
- Opportunities: **Сохранить видео**, related families, **Сохранить тему** on family cards.
- Detail routes: `/saved/videos/{id}`, `/saved/families/{id}` (THEN/NOW + absence copy).

No localStorage bookmarks.

## M. Performance

List/detail endpoints use bounded queries (saved rows + latest observation). No Attention recompute, no YouTube HTTP on save or list.

## N. Tests

`python scripts/test_saved_research_1_22c.py` — save, idempotency, refresh append, absence semantics, API patch/archive.

Legacy: `scripts/test_saved_topics_1_22c.py` still passes.

## O. Production validation (manual)

1. Save one strong winner, one AI/kaise family, one diorama family via UI or POST.
2. `python scripts/refresh_attention_engine.py`
3. Verify observation count + THEN/NOW on `/saved/...` detail.

Do not tune Attention rules for these cases.

## P. Known limitations

- Legacy `saved_topics` not auto-migrated to `saved_families`.
- No per-user `user_id` yet (single-workspace); columns can be added later.
- Detail pages: status/notes/tags editing UI minimal (PATCH API ready).
- SavedTopic validation report still reads legacy table.

## Q. Readiness for 1.22D

Persisted: save timestamps, frozen signals, observation timeline, user status/tags, archive, video vs family split — sufficient for feedback analytics described in 1.22D spec.
