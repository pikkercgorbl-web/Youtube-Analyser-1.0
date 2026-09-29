# Stage 1.10 validation outcome analysis (T0 → T72)

**Experiment:** `stage110_20260914_141029`
**T0 reference:** 2026-09-14T14:10:29.608646+00:00
**T72 elapsed (actual):** 71.9567 h

## Usable N

`{'T24': {'cohort_rows': 500, 'refreshed': 498, 'missing': 2, 'failed': 0, 'other': 0, 'elapsed_hours': 24.077}, 'T48': {'cohort_rows': 500, 'refreshed': 496, 'missing': 4, 'failed': 0, 'other': 0, 'elapsed_hours': 48.027}, 'T72': {'cohort_rows': 500, 'refreshed': 494, 'missing': 6, 'failed': 0, 'other': 0, 'elapsed_hours': 71.9567}}`

## Q1 — T0 VPH vs views (T72 final)

- Spearman views: `{'n': 494, 'rho': 0.7826}`
- Spearman VPH: `{'n': 494, 'rho': 0.8082}`
- Δρ (VPH−views): `0.0256`
- Top-10 capture views: `0.5`
- Top-10 capture VPH: `0.62`
- Bootstrap: `{'method': 'bootstrap_percentile_CI_n=1000_seed=42', 'spearman_views_ci': {'low': 0.7133, 'high': 0.8413}, 'spearman_vph_ci': {'low': 0.7372, 'high': 0.8655}, 'spearman_diff_vph_minus_views_ci': {'low': 0.0021, 'high': 0.0501}, 'top10_recall_diff_vph_minus_views_ci': {'low': 0.0, 'high': 0.2251}, 'mean_spearman_views': 0.7811, 'mean_spearman_vph': 0.807}`

## Q2 — Channel-relative baseline (T72)

`{'by_channel_baseline_status': {'ok': {'n_refreshed': 409, 'views_vs_channel_median': {'n': 406, 'spearman': {'n': 406, 'rho': 0.0787}, 'top10_capture': {'top_n': 41, 'captured_in_predictor_top_bin': 5, 'capture_rate': 0.122}}, 'views_vs_channel_p75': {'n': 408, 'spearman': {'n': 408, 'rho': 0.1073}, 'top10_capture': {'top_n': 41, 'captured_in_predictor_top_bin': 6, 'capture_rate': 0.1463}}, 'vph_vs_channel_median': {'n': 0, 'spearman': {'n': 0, 'rho': None}, 'top10_capture': {}}, 't0_vph_on_same_rows': {'n': 409, 'spearman': {'n': 409, 'rho': 0.8389}, 'top10_capture': {'top_n': 41, 'captured_in_predictor_top_bin': 28, 'capture_rate': 0.6829}}}, 'partial': {'n_refreshed': 49, 'views_vs_channel_median': {'n': 47, 'spearman': {'n': 47, 'rho': -0.0648}, 'top10_capture': {'top_n': 5, 'captured_in_predictor_top_bin': 0, 'capture_rate': 0.0}}, 'views_vs_channel_p75': {'n': 49, 'spearman': {'n': 49, 'rho': 0.0083}, 'top10_capture': {'top_n': 5, 'captured_in_predictor_top_bin': 0, 'capture_rate': 0.0}}, 'vph_vs_channel_median': {'n': 0, 'spearman': {'n': 0, 'rho': None}, 'top10_capture': {}}, 't0_vph_on_same_rows': {'n': 49, 'spearman': {'n': 49, 'rho': 0.4308}, 'top10_capture': {'top_n': 5, 'captured_in_predictor_top_bin': 2, 'capture_rate': 0.4}}}}, 'view_baseline_available_n': 458, 'velocity_baseline_available_n': 0, 'incremental_view_baseline_subset': {'note': 'Same refreshed rows with channel view baseline; compare view-relative vs raw VPH.', 't0_vph': {'n': 458, 'spearman': {'n': 458, 'rho': 0.8131}, 'top10_capture': {'top_n': 46, 'captured_in_predictor_top_bin': 30, 'capture_rate': 0.6522}}, 'views_vs_channel_median': {'n': 453, 'spearman': {'n': 453, 'rho': 0.0891}, 'top10_capture': {'top_n': 46, 'captured_in_predictor_top_bin': 7, 'capture_rate': 0.1522}}, 'vph_vs_channel_median': {'n': 0, 'spearman': {'n': 0, 'rho': None}, 'top10_capture': {}}}}`

## Checkpoint stability

`{'spearman_views': {'T24': {'n': 498, 'rho': 0.7809}, 'T48': {'n': 496, 'rho': 0.7887}, 'T72': {'n': 494, 'rho': 0.7826}}, 'spearman_vph': {'T24': {'n': 498, 'rho': 0.8226}, 'T48': {'n': 496, 'rho': 0.8172}, 'T72': {'n': 494, 'rho': 0.8082}}, 'delta_rho_vph_minus_views': {'T24': 0.0417, 'T48': 0.0285, 'T72': 0.0256}}`

## Missingness (T72)

`{'missing_video_ids': ['SP3XAsGztCk', 'vIUzC5gAXAA', '3K2EwKJQ-1g', 'bGwYurIB82M', 'aVwG0lkDpT0', '8J9A6Qq0MIE'], 'missing_count': 6, 'refreshed_summary': {'n': 494, 'median_t0_views': 4154.0, 'median_t0_vph': 297.53, 'channel_baseline_status_counts': {'ok': 409, 'partial': 49, 'insufficient_history': 30, 'failed': 6}}, 'missing_summary': {'n': 6, 'median_t0_views': 4565.0, 'median_t0_vph': 277.98, 'channel_baseline_status_counts': {'ok': 4, 'partial': 1, 'insufficient_history': 1}}}`

## First cohort comparison

`{'first_cohort_elapsed_hours': 67.0689, 'first_cohort_joined_n': 2794, 'first_cohort_spearman_views': 0.7966, 'first_cohort_spearman_vph': 0.8275, 'first_cohort_top10_capture_views': 0.6214, 'first_cohort_top10_capture_vph': 0.7029, 'first_cohort_bootstrap': {'method': 'bootstrap_percentile_CI_n=1000_seed=42', 'spearman_views_ci': {'low': 0.7751, 'high': 0.8181}, 'spearman_vph_ci': {'low': 0.8039, 'high': 0.8451}, 'spearman_diff_vph_minus_views_ci': {'low': 0.022, 'high': 0.0331}, 'top10_recall_diff_vph_minus_views_ci': {'low': 0.0486, 'high': 0.1224}, 'mean_spearman_views': 0.7973, 'mean_spearman_vph': 0.8248}}`
