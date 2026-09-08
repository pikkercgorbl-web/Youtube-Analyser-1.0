# Radar v0.1 — Experimental Trend Detection Specification

## Goal

Turn the existing keyword-driven explosive-channel radar into an experimental trend detector that can identify both:

1. individual video anomalies; and
2. emerging topics supported by multiple independent channels.

The first version is deliberately data-first: every decision must leave enough historical data to evaluate whether the decision was useful later.

## Pipeline

```text
Discovery
  -> dedupe(video_id)
  -> RadarCandidate
  -> Video / VideoSnapshot / ChannelSnapshot
  -> embedding for every eligible candidate
  -> topic assignment
  -> video signal + topic signal
  -> adaptive observation tier
  -> cross-channel confirmation
  -> stateful topic alert
  -> future observations
  -> evaluation + control group
```

## Final decisions

### Discovery

- Keep the existing InnerTube discovery path as the primary experimental candidate source.
- Do not treat `min_views` and `min_viral_coeff` as hard discovery filters; those are observation/ranking signals.
- Keep hard validity filters (missing channel, blacklist, invalid upload period/format) as rejection filters.
- Persist every discovered candidate and its rejection reason.
- Deduplicate by `video_id` before embedding or topic assignment.
- Persist the discovery source (`keyword`, `suggestion`, `channel`, `graph`, `api`) so source quality can be measured later.

Removing the old hard view/virality thresholds is intentionally expected to increase the candidate volume by orders of magnitude. Stage 0 must measure the resulting discovery, storage, embedding, and observation load before tightening polling policy.

### Observation

- Add `VideoSnapshot` for point-in-time video statistics.
- Reuse `ChannelSnapshot`; do not create a second channel-history table.
- Poll metrics in batches of up to 50 video IDs.
- Polling is adaptive: promotion and demotion are both required.
- Every observed candidate has a hard observation budget (`checks_count`, maximum age/hot duration) as a safety stop.
- A traffic-quality heuristic may reduce polling priority but must not claim to identify bots with certainty.
- Stage 0 is a measurement phase: record candidate volume, hard-filter rejection rate, eligible volume, unique channels, and later observation throughput before relying on fixed polling assumptions.

### Baseline

Use hierarchical shrinkage instead of hard buckets:

```text
topic_estimate  = shrink(topic_baseline, global_baseline, n_topic)
channel_estimate = shrink(channel_baseline, topic_estimate, n_channel)

w = n / (n + k)
```

Until semantic topics exist, the only valid temporary topic proxy in v0.1 is `discovery_keyword`. `Channel.topic` and `Video.topic` are not baseline inputs because they are currently not populated by the existing radar/search ingestion path. Every baseline calculation must store `baseline_source` explicitly so proxy-based measurements cannot be confused with semantic-topic measurements during evaluation.

### Temporal signal

Store and calculate:

- views per short window (for example 20m / 1h / 3h / 6h / 24h);
- velocity;
- acceleration;
- relative performance against the expected-view baseline.

### Tier logic

Keep video and topic signals separate. Do not invent a weighted combined score in v0.1.

Minimum MVP rule:

- strong video signal -> promote;
- strong topic signal -> floor at T1;
- both strong -> aggressive tier;
- persistent slowdown -> demote;
- plateau/max budget -> cooldown/stop.

### Embeddings

- Compute embeddings for every new eligible candidate after dedupe, not only for already-hot videos.
- Use a lightweight local multilingual embedding model such as `multilingual-e5-small`.
- The embedding service owns preprocessing and E5 prefixes; callers do not add prefixes manually.
- Store the semantic input `content_hash` and a `config_hash` derived from model + preprocessing configuration.
- `config_hash` answers whether the embedding configuration changed; `content_hash` answers whether the semantic input changed. Both are required for deterministic, idempotent recomputation.
- Similarity is used for online topic assignment.

### Topic grouping

Use a simple online nearest-topic approach in v0.1:

```text
new embedding
  -> nearest active topic centroid
  -> similarity >= threshold ? attach : create topic
```

Run a daily merge pass to reduce fragmentation. Merge operations must be logged as events; historical topic metrics are not silently rewritten.

Merged topics must have an explicit inactive/resolution state (for example `merged_into_id`) so a source topic cannot continue receiving new memberships after it has been merged.

Topic membership is historical so that a video can move between topic identities without destroying the past. The current active membership used for cross-channel confirmation must be unambiguous; reassignment history must not inflate channel counts.

### Cross-channel confirmation

A topic becomes meaningful only when semantic similarity and multiple independent channels agree. Count distinct channels within the active/new-topic observation window, not raw video count. Individual video virality alone is Level 1, not the final product signal.

### Alerts

Topic state machine:

```text
candidate -> emerging -> confirmed -> alerted -> cooled
```

Alerts are event-based, not emitted on every polling cycle. Re-alert requires a meaningful renewed transition after cooldown.

### Evaluation

Every alert stores:

- algorithm configuration hash;
- trigger/state transition;
- triggering video;
- initial topic video count;
- initial topic channel count.

Outcomes are measured at 6h / 24h / 72h / 7d. Control samples must receive equivalent future outcome measurement so the control group can estimate missed opportunities, not only precision among alerted items.

Maintain a stratified control group:

- random;
- borderline;
- low-score.

### Idempotency

All derived results must be safely repeatable after worker failure. External/expensive work is keyed by deterministic content/config hashes rather than manually incremented versions.

## Development stages

The implementation is intentionally staged. The repository should not jump directly to embeddings, semantic topics, or alerts before the ingestion and measurement foundation is working.

### Stage 0 — Measure current radar throughput

**Goal:** establish real baseline numbers before changing discovery behavior.

Development scope:

- Do not redesign the Radar yet.
- Run the current worker and collect real measurements.
- Measure videos discovered per keyword/cycle/day.
- Measure hard-filter rejection counts and reasons.
- Measure eligible candidates that would enter the future Radar pipeline.
- Measure unique channels encountered.
- Record current worker runtime, pages fetched, and request volume.
- Use these numbers to estimate the likely increase after removing `min_views`/`min_viral_coeff` as discovery gates.

Important: Stage 0 is not considered complete after a code change alone. The worker must accumulate enough real runtime data to make the volume estimate useful. Initial collection target: roughly 2–3 days of normal operation.

### Stage 1 — Discovery → Persistence separation

**Goal:** stop making discovery depend on the old explosive-channel qualification logic.

Add a `RadarCandidate` persistence layer with, at minimum:

```python
class RadarCandidate(Base):
    __tablename__ = "radar_candidates"
    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    discovery_keyword: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

Implementation rules:

- Persist every discovered item after the hard validity checks.
- Keep missing channel, blacklist, invalid upload period/format as hard rejection conditions.
- Remove `min_views` and `min_viral_coeff` from the discovery gate.
- Those metrics become later observation/tier signals.
- Deduplicate on `video_id` before any embedding/topic processing.
- Keep discovery source information for later source-quality evaluation.
- Do not destroy an existing candidate record merely because the same video is rediscovered from another source.

### Stage 2 — Video history + reuse channel history

**Goal:** create the time-series foundation for growth analysis.

Add `VideoSnapshot` and reuse the existing `ChannelSnapshot`.

`VideoSnapshot` must capture at least:

- video_id;
- views;
- likes;
- comments;
- recorded_at.

Poll and persist metrics in batches of up to 50 video IDs using the existing client capability.

Verify the actual `Video.id` type in the repository before implementing the foreign key; do not assume it from the specification alone.

### Stage 3 — Baseline + temporal signal

**Goal:** estimate expected performance and detect acceleration without hard subscriber/view buckets.

Use hierarchical shrinkage:

```text
 topic_estimate  = shrink(topic_baseline, global_baseline, n_topic)
 channel_estimate = shrink(channel_baseline, topic_estimate, n_channel)
 w = n / (n + k)
```

Temporary topic proxy:

- `discovery_keyword` only;
- do not use `Channel.topic`;
- do not use `Video.topic`.

Every baseline estimate must record `baseline_source`.

Main performance signal:

```text
relative_performance = current_views / expected_views(channel)
```

Use shrinkage for cold-start channels/topics.

Also calculate:

- views per short window;
- velocity;
- acceleration;
- relative performance against the expected baseline.

Keep the existing `calc_virality_coefficient` available for legacy UI/behavior until dependent code is migrated; it is not the primary v0.1 trend signal.

### Stage 4 — Adaptive observation tiers

**Goal:** spend observation capacity where there is evidence of continued growth.

Introduce T0–T3 observation tiers.

Requirements:

- promotion rules;
- demotion rules;
- `next_check_at`;
- `checks_count`;
- maximum hot age / observation budget;
- cooldown/stop after plateau or budget exhaustion.

Polling must be adaptive in both directions. A candidate that cools down must require fewer checks; it must not remain permanently hot.

Before promoting to the most aggressive tier, a traffic-quality heuristic may lower priority for obvious low-quality anomalies. This remains heuristic and is never treated as definitive bot detection.

### Stage 5 — PostgreSQL/Supabase + pgvector preparation

**Goal:** prepare the production/experimental database for semantic embeddings.

Target:

- PostgreSQL/Supabase;
- pgvector extension;
- vector dimension 384 for `multilingual-e5-small`;
- cosine distance for nearest-topic lookup.

Use the extension without explicit version pinning in migrations.

SQLite remains supported for the existing application until runtime migration is explicitly enabled. Do not silently introduce PostgreSQL-only vector types into SQLite execution paths.

When topic count/data volume grows, HNSW can be added for vector search optimization.

### Stage 6 — Embeddings for every eligible candidate

**Goal:** give every eligible candidate semantic representation, including quiet signals that are not yet hot.

Use:

- `multilingual-e5-small`;
- local CPU inference;
- batched embedding.

The embedding service owns all preprocessing and E5 prefixes. Callers provide raw semantic content only.

Recommended deterministic semantic input should include the available meaningful metadata (for example title, description, tags, and channel title), normalized and truncated by one owned preprocessing function.

`VideoEmbedding` must store:

- video_id;
- embedding vector(384);
- model version;
- `config_hash`;
- `content_hash`;
- computed_at.

Recompute only when either the semantic content or embedding configuration changed.

### Stage 7 — Semantic topic grouping

**Goal:** turn individual video embeddings into persistent emerging-topic identities.

Use online grouping:

```text
new embedding
  -> nearest active topic centroid
  -> similarity >= threshold ? attach : create topic
```

Store historical membership rather than overwriting topic history.

Topic identity needs an explicit active/inactive resolution mechanism such as `merged_into_id` so merged topics stop receiving new memberships.

For the membership representation, current active membership must be unambiguous. Historical reassignment records must not inflate cross-channel counts.

Update topic centroids incrementally for ordinary assignments. When topics merge, recompute the resulting centroid from member embeddings or another mathematically equivalent weighted procedure; do not average centroids as if every topic had the same number of members.

Run a daily merge pass to reduce fragmentation.

Record every merge using `TopicMergeEvent` so historical evaluation remains explainable.

### Stage 8 — Cross-channel confirmation + video/topic signals

**Goal:** distinguish a single viral video from an actual emerging topic.

Count distinct independent channels participating in the active/new topic window.

Store separate signals:

- video signal;
- topic signal;
- cross-channel confirmation evidence.

MVP decision rules:

- strong video signal → promote;
- strong topic signal → floor at T1;
- both strong → more aggressive tier;
- persistent slowdown → demote.

Do not introduce a magic weighted score in v0.1.

### Stage 9 — Stateful alerts

**Goal:** produce meaningful trend alerts without spamming repeated notifications.

Topic state machine:

```text
candidate -> emerging -> confirmed -> alerted -> cooled
```

Persist at least:

- topic_id;
- algorithm config hash;
- trigger/state transition;
- triggering video;
- initial video count;
- initial distinct channel count;
- triggered_at.

Alert only on state transitions.

Re-alert only after cooldown plus a meaningful renewed transition.

### Stage 10 — Evaluation + stratified control group

**Goal:** measure whether Radar actually finds useful opportunities rather than only producing attractive alerts.

For every alert, measure outcomes at:

- 6h;
- 24h;
- 72h;
- 7d.

Store topic-level outcome evidence, not only the number of raw videos.

Maintain a stratified control group:

- random;
- borderline;
- low-score.

Control samples must receive the same future outcome measurement as alerted items. This is necessary to estimate missed opportunities / recall-like behavior, not just precision among alerts.

Do not interpret the first 10–100 alerts as statistically meaningful. The first 2–3 weeks are primarily a data-collection period; useful conclusions require a larger number of outcomes across multiple strata.

### Cross-stage rule

Build and validate a walking skeleton before optimizing every subsystem:

```text
one discovery
  -> one candidate
  -> one snapshot
  -> one baseline estimate
  -> one observation decision
  -> one alert/outcome path
```

The walking skeleton can use simplified logic, but every stage must preserve the data contracts that the final system will need.

## Database direction

Production/experimental target: PostgreSQL/Supabase + pgvector.

Local SQLite remains the fallback for the current application until the runtime is switched explicitly. New vector code must not silently assume SQLite-only behavior.

## Out of scope for v0.1

- HDBSCAN
- FAISS-specific infrastructure
- learned Opportunity Score
- ML prediction model
- full social/channel graph engine
- large refactor of `youtube/client.py`

## Success criterion

The MVP is successful only when it can produce examples of both:

1. a genuine individual video anomaly; and
2. a genuine emerging topic where several semantically related videos from independent channels show coordinated growth.

It must also retain enough future observations to measure whether those alerts were correct and compare them with the stratified control group.

## Implementation guardrails

- The plan is the source of truth for the v0.1 architecture.
- Do not add new scoring formulas or ML layers without updating this specification first.
- Do not use `Channel.topic` or `Video.topic` as a Stage-3 baseline proxy unless a later plan revision explicitly changes that decision.
- Do not make PostgreSQL/pgvector a hidden dependency of the existing SQLite application.
- Do not remove old legacy behavior merely because a v0.1 subsystem exists; migrate dependent UI/services deliberately.
