# Breakout Ranking v1 — Historical Evaluation (Stage 1.17C)

- Schema: `1.17C`
- Breakout version: `breakout_v1`
- Production age horizon: `72.0h`

## Cohort 1 (T0 → T67)

- Joined: `C:\Projects\Сайт анализ ниш1\artifacts\radar_outcome_joined_T0_T67_20260914_124311.jsonl`
- SHA256: `4ad54a3725a8a777e63436bba26308fbcccb8e17227355f9c8d3380c8412dc11`
- Signal validation N: 2794
- Production eligible N: 2652 (excluded 142: {'missing_vph': 31, 'non_regular_format': 3, 'short_format': 108})

### Signal validation (historical baseline reproduction)
- Views Spearman ρ: 0.7966 (n=2794)
- Views top-10 capture: 0.6214
- VPH Spearman ρ: 0.8275 (n=2760)
- VPH top-10 capture: 0.7029

### Production eligibility population
- Views Spearman ρ: 0.7978
- VPH Spearman ρ: 0.8253
- Breakout v1 Spearman ρ (neg rank): 0.8252
- Breakout top-10 capture (by rank): 0.7068

### Breakout vs raw VPH equivalence
- Identical rank positions: 2043 / 2652
- Changed positions: 609
- Max rank displacement: 12
- Spearman(breakout rank, raw VPH rank): 1.0
- Kendall τ: 0.999539
- Effectively identical: True

## Cohort 2 (stage110 → T72)

- Joined: `C:\Projects\Сайт анализ ниш1\artifacts\radar_outcome_joined_stage110_T0_to_T72_stage110_20260914_141029.jsonl`
- SHA256: `69613d88581a8f2c45bee441ddd5e40cec64c1ca06a79022d9412dc30e26e504`
- Signal validation N: 494
- Production eligible N: 494 (excluded 0: {})

### Signal validation (historical baseline reproduction)
- Views Spearman ρ: 0.7826 (n=494)
- Views top-10 capture: 0.5
- VPH Spearman ρ: 0.8082 (n=494)
- VPH top-10 capture: 0.62

### Production eligibility population
- Views Spearman ρ: 0.7826
- VPH Spearman ρ: 0.8082
- Breakout v1 Spearman ρ (neg rank): 0.8083
- Breakout top-10 capture (by rank): 0.62

### Breakout vs raw VPH equivalence
- Identical rank positions: 481 / 494
- Changed positions: 13
- Max rank displacement: 3
- Spearman(breakout rank, raw VPH rank): 1.0
- Kendall τ: 0.999819
- Effectively identical: True

## Acceptance

- cohort_1_vph_first_ordering: `True`
- cohort_1_no_unexplained_rho_drop: `True`
- cohort_1_deterministic_service: `True`
- cohort_2_vph_first_ordering: `True`
- cohort_2_no_unexplained_rho_drop: `True`
- cohort_2_deterministic_service: `True`
- directionally_consistent_both_cohorts: `True`
- frozen_inputs_verified: `True`
- pass: `True`

Breakout v1 ranks by last-known T0 VPH with views/video_id tie-breaks; it is not expected to outperform raw VPH on predictive metrics.
