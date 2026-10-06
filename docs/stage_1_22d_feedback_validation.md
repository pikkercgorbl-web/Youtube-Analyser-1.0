# Stage 1.22D — Feedback + Validation

**Status:** done (2026-10-06)

## Scope

- Append-only **SavedTopicEvent** (`status_changed`, `archived`, `restored`, `feedback_added`).
- Append-only **SavedTopicFeedback** (finding rating, comment, optional own-test URL/dates/outcome, manual metrics).
- State change + event in one DB transaction; same status → no event; no backfilled history for pre-existing topics.
- Read-only **Validation** report: `/api/validation/report`, UI `/validation`.

## PostgreSQL 1.22C regression

`scripts/test_saved_topics_1_22c_postgres_regression.py` on `SAVED_TOPICS_POSTGRES_TEST_URL` (default DB name `youtube_radar_saved_topics_test`). Refuses production `DATABASE_URL`.

## Tests

| Script | DB |
|--------|-----|
| `test_saved_topics_1_22c.py` | SQLite in-memory |
| `test_saved_topics_1_22d.py` | SQLite in-memory |
| `test_saved_topics_1_22c_postgres_regression.py` | Dedicated Postgres |

## User path

Opportunities → save family → Saved Topic detail → status decisions → feedback / own test → Validation report.

## Limitations

- No YouTube API, no profitability scoring, no Attention recompute from UI.
- Validation counts are descriptive; bounded-sample deltas are not market growth proof.
- Feedback history is append-only; “latest” drives validation distributions.
