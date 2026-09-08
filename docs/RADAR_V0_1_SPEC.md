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

It must also retain enough future observations to measure whether those alerts were correct.
