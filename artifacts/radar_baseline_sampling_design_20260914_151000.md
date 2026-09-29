# Baseline Sampling Design (Stage 1.10B)

## 1. Source distributions (regular, VPH-eligible)
- Pool size: **2673**
- Unique channels: **2503** (rate **0.9364**)
- VPH P50: **11.61**

## 2. VPH strata
`{'labels': ['low', 'medium', 'high', 'very_high'], 'boundaries': {'p25': 0.8, 'p50': 11.61, 'p75': 177.84, 'p90': 927.7160000000016, 'min': 0.0, 'max': 100182.07}, 'interpretation': {'low': 'vph < 0.8', 'medium': '0.8 <= vph < 177.84', 'high': '177.84 <= vph < 927.7160000000016', 'very_high': 'vph >= 927.7160000000016'}}`

## 3. Channel-size strata
`{'labels': ['small', 'medium', 'large', 'unknown'], 'boundaries': {'p33': 89622.24999999996, 'p67': 518032.5, 'known_n': 326}}`

## 4. Keyword allocation
**Recommendation:** capped_proportional

## 5–6. Designs & retrospective coverage
See JSON `designs` for A/B/C at n=300/500/700.

## 7. Per-channel cap
`{'unlimited': {'selected_count': 500, 'unique_channels': 488, 'expected_runtime_seconds': 1464.0, 'retrospective': {'winners_in_pool': 266, 'winners_selected': 122, 'winner_recall': 0.4586, 'selected_non_winner_share': 0.756}}, 'max_2_per_channel': {'selected_count': 500, 'unique_channels': 488, 'expected_runtime_seconds': 1464.0, 'retrospective': {'winners_in_pool': 266, 'winners_selected': 122, 'winner_recall': 0.4586, 'selected_non_winner_share': 0.756}}, 'max_1_per_channel': {'selected_count': 488, 'unique_channels': 488, 'expected_runtime_seconds': 1464.0, 'retrospective': {'winners_in_pool': 266, 'winners_selected': 120, 'winner_recall': 0.4511, 'selected_non_winner_share': 0.7541}}}`

## 8. Runtime estimates
`{'n300': {'assumed_unique_channels': 270, 'baseline_seconds': 810.0, 'baseline_minutes': 13.5}, 'n500': {'assumed_unique_channels': 484, 'baseline_seconds': 1452.0, 'baseline_minutes': 24.2}, 'n700': {'assumed_unique_channels': 630, 'baseline_seconds': 1890.0, 'baseline_minutes': 31.5}}`

## 9. Frozen sampling rule
```json
{
  "version": "1.10B",
  "seed": 42,
  "eligible_pool": "content_format=regular AND vph_at_t0 IS NOT NULL AND channel_id present",
  "dedupe": "one row per video_id globally before sampling",
  "vph_strata_boundaries": {
    "p25": 0.8,
    "p50": 11.61,
    "p75": 177.84,
    "p90": 927.7160000000016,
    "min": 0.0,
    "max": 100182.07
  },
  "vph_stratum_acceptance_probability": {
    "very_high": 1.0,
    "high": 0.85,
    "medium": 0.45,
    "low": 0.2
  },
  "keyword_allocation": "capped_proportional",
  "keyword_cap_fraction": 0.18,
  "max_candidates_per_channel": 2,
  "target_baseline_sample_sizes": [
    300,
    500,
    700
  ],
  "recommended_target": 500,
  "recommended_design": "A_vph_heavy",
  "t0_only_fields": [
    "age_hours_at_t0",
    "channel_id",
    "content_format",
    "discovered_at",
    "discovery_subscribers",
    "discovery_views",
    "final_subscribers",
    "keyword",
    "video_id",
    "vph_at_t0"
  ],
  "notes": [
    "Acceptance uses vph_at_t0 strata only; no T67/outcome fields at execution time.",
    "Process pool in random shuffle order within keyword after optional top-VPH pass.",
    "Channel baseline fetched once per channel_id per run (cache)."
  ]
}
```

## 10. Limitations
- Retrospective winner recall uses Stage 1.9 T67 outcomes — diagnostic only.
- Subscriber strata sparse (~12% known in T0 cohort); size balancing is approximate.
- Unique-channel ratio extrapolated from gaming pilot (1.10A).
- Next cohort discovery mix may differ from 1.9A keyword distributions.
