# Keyword Performance Historical Validation (Stage 1.18C)

- Schema: `1.18C`
- Runtime: 10.447s

## A. Data sources and coverage

- Cohort 2 joined: `radar_outcome_joined_stage110_T0_to_T72_stage110_20260914_141029.jsonl` SHA256 `69613d88581a8f2c45bee441ddd5e40cec64c1ca06a79022d9412dc30e26e504`
- Signal rows: 494
- Pseudo-keyword limitations: Pseudo-keywords from t0_keywords[] are not TargetKeyword.id., No KeywordScanRun / rescan timeline in join file., Outcome is pre-joined ~72h growth, not recomputed from VideoSnapshot., first_discovery uses first array element only (export order).

## B. Leakage-safe early features

- Allowed: vph_at_discovery, views_at_discovery, early_global_vph_rank, early_top_decile_by_discovery_vph, discovery_yield_counts, new_to_corpus, duplicate_flags, scan_run_metadata
- Forbidden: current_vph_after_horizon, current_breakout_rank_after_outcome, future_snapshots, future_lifecycle_state, outcome_derived_features, production_breakout_leaderboard_at_evaluated_at

## C. Delayed outcome

- {"target": "absolute_view_growth_72h", "horizon_hours": 72, "tolerance_hours": 12, "first_hit_per_keyword_video": true, "no_imputation": true}

## D. Q1 early signal vs delayed outcome (cohort 2, all_hits)

- **early_top_decile_rate_vs_median_absolute_view_growth_72h**: n=10 ρ=0.6444
  - bootstrap 95% CI: [-0.0508, 1.0]
- **median_vph_at_discovery_vs_median_absolute_view_growth_72h**: n=10 ρ=0.4909
  - bootstrap 95% CI: [-0.2346, 0.9245]
- **p90_vph_at_discovery_vs_p90_absolute_view_growth_72h**: n=10 ρ=0.7455
  - bootstrap 95% CI: [0.0728, 1.0]
- **early_top_decile_rate_vs_delayed_top_decile_growth_rate**: n=10 ρ=0.7295
  - bootstrap 95% CI: [0.1748, 0.9868]

## E–H. Robustness, outliers, stability, redundancy

- Evidence strata (sample keys): ['scan_1|attr_10_49|obs_10_plus', 'scan_1|attr_50_plus|obs_10_plus']
- Outlier dominated keywords: 2
- Attribution shared labels: 10

## I. all_hits vs first_discovery

- all_hits keywords=10 obs=496
- first_discovery keywords=10 obs=494

## J. confirmed_breakout_count

- Retain API field for backward compatibility but document explicitly as top_decile_breakout_count alias; do not use the word 'confirmed' in historical validation or lifecycle copy.

## K–L. Metric decision matrix

- `early_top_decile_rate`: **useful_evidence**
- `median_vph_at_discovery`: **useful_evidence**
- `p90_vph_at_discovery`: **useful_evidence**
- `cross_keyword_duplicate_rate`: **promising_but_insufficient_evidence**
- `new_to_corpus_rate`: **not_testable_with_current_data**
- `current_breakout_rank_live`: **weak_or_redundant_for_historical_prediction**
- `confirmed_breakout_count_api_field`: **legacy_alias_document_only**

## Production batch (if run)

- Attempted: True
- Coverage: {'all_hits_observations': 8461, 'first_discovery_observations': 7362, 'keywords_all_hits': 27, 'keywords_with_72h_outcomes': 0, 'load_elapsed_seconds': 8.046}

## M. Lifecycle design implications

- Prefer leakage-safe early_top_decile_by_discovery_vph over live breakout rank for feedback loops.
- Require minimum observed_72h_video_count before keyword promotion decisions (threshold TBD in 1.18E).
- Report scan-order sensitivity when showing first_discovery metrics alongside all_hits.
- Treat high duplicate rate as contextual (popular topics), not automatically penalized.

## P. Limitations

- Pseudo-keywords ≠ production TargetKeyword scheduling entities.
- Frozen outcomes fixed at join time; production path depends on snapshot density.
- Keyword-level N small; do not overclaim weak Spearman estimates.
- No keyword score or lifecycle automation produced in this stage.

## N. Artifact SHA256

- JSON: `a1442f9b8743fb4a7ff1b7b6cc639092c7744c97320b005087e4c2131826c640`
