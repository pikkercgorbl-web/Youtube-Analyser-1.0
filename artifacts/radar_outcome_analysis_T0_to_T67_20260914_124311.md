# Outcome Analysis T0 → T67

**Elapsed hours:** 67.0689
**Joined refreshed rows:** 2794

## 1. Data quality

`{'snapshot_rows': 2819, 'joined_refreshed_rows': 2794, 'missing_refresh_excluded': 25, 'duplicate_video_id_in_joined': 0, 'negative_absolute_growth_count': 22, 'zero_absolute_growth_count': 177, 't0_vph_available': 2760, 't0_vph_missing': 34, 't0_v_s_available': 327, 't0_v_s_missing': 2467, 't0_subscribers_available': 327, 't0_age_available': 2794}`

## 2. Outcome distribution

`{'absolute_view_growth': {'count': 2794, 'min': -46599.0, 'median': 151.5, 'p75': 3110.25, 'p90': 15041.7, 'p95': 38318.65, 'max': 5816102.0, 'p99': 156266.33, 'thresholds': {'p50': 151.5, 'p75': 3110.25, 'p90': 15041.7, 'p95': 38318.65, 'p99': 156266.33}, 'top_50_pct': {'threshold': 151.5, 'count': 1397}, 'top_25_pct': {'threshold': 3110.25, 'count': 699}, 'top_10_pct': {'threshold': 15041.7, 'count': 280}, 'top_5_pct': {'threshold': 38318.65, 'count': 140}, 'top_1_pct': {'threshold': 156266.33, 'count': 28}}, 'view_growth_multiple': {'count': 2582, 'min': 0.0, 'median': 2.4236, 'p75': 5.5931, 'p90': 16.9952, 'p95': 34.4401, 'max': 12909.0, 'p99': 119.6724}, 'avg_growth_views_per_hour': {'count': 2794, 'min': -694.793, 'median': 2.2588, 'p75': 46.3739, 'p90': 224.2723, 'p95': 571.3326, 'max': 86718.315, 'p99': 2329.9373}}`

## 3. H0 — initial views

`{'spearman': {'n': 2794, 'rho': 0.7966}, 'decile_bins': {'D1': {'n': 344, 'median_growth': 2.0, 'mean_growth': 108.2703}, 'D10': {'n': 280, 'median_growth': 24604.0, 'mean_growth': 82229.5393}, 'D2': {'n': 224, 'median_growth': 9.5, 'mean_growth': 61.9777}, 'D3': {'n': 271, 'median_growth': 27.0, 'mean_growth': 131.7011}, 'D4': {'n': 279, 'median_growth': 51.0, 'mean_growth': 250.2186}, 'D5': {'n': 281, 'median_growth': 101.0, 'mean_growth': 647.7758}, 'D6': {'n': 278, 'median_growth': 279.0, 'mean_growth': 1953.723}, 'D7': {'n': 279, 'median_growth': 791.0, 'mean_growth': 3983.1613}, 'D8': {'n': 279, 'median_growth': 2319.0, 'mean_growth': 5270.0968}, 'D9': {'n': 279, 'median_growth': 5242.0, 'mean_growth': 13298.3118}}, 'top10_capture': {'top_n': 280, 'captured_in_predictor_top_bin': 174, 'capture_rate': 0.6214}}`

## 4. H1 — T0 VPH

`{'spearman': {'n': 2760, 'rho': 0.8275}, 'vph_bins': {'100-1k': {'n': 598, 'median_growth': 4512.5, 'mean_growth': 8540.8562}, '10k-25k': {'n': 28, 'median_growth': 142026.0, 'mean_growth': 179267.4286}, '1k-5k': {'n': 182, 'median_growth': 27126.0, 'mean_growth': 75798.1978}, '25k-50k': {'n': 6, 'median_growth': 112066.0, 'mean_growth': 357885.3333}, '5k-10k': {'n': 32, 'median_growth': 59984.5, 'mean_growth': 97328.5938}, '<=100': {'n': 1910, 'median_growth': 46.0, 'mean_growth': 526.6429}, '>50k': {'n': 4, 'median_growth': -14264.5, 'mean_growth': -14429.0}, 'missing': {'n': 34, 'median_growth': 26.0, 'mean_growth': 1934.0588}}, 'top10_capture': {'top_n': 276, 'captured_in_predictor_top_bin': 194, 'capture_rate': 0.7029}}`

## 5. H2 — Views/Subscribers

`{'sample_size': 327, 'selection_bias_note': 'T0 V/S is only available where subscriber fetch succeeded; historically concentrated among passed / homepage_fetched channels.', 'spearman': {'n': 327, 'rho': -0.0884}, 'v_s_bins': {'0.1-0.5': {'n': 110, 'median_growth': 25111.0, 'mean_growth': 114097.0545}, '0.5-1': {'n': 28, 'median_growth': 21073.0, 'mean_growth': 40880.7143}, '1-2': {'n': 17, 'median_growth': 2799.0, 'mean_growth': 34833.5294}, '2-5': {'n': 13, 'median_growth': 20755.0, 'mean_growth': 35497.5385}, '<0.1': {'n': 142, 'median_growth': 18500.0, 'mean_growth': 52634.3521}, '>=5': {'n': 17, 'median_growth': 2655.0, 'mean_growth': 35824.0588}}, 'top10_capture': {'top_n': 33, 'captured_in_predictor_top_bin': 3, 'capture_rate': 0.0909}}`

## 6. H3 — VPH + V/S + Age

`{'vph_cutoffs': {'p33': 1.4957, 'p67': 75.4171}, 'v_s_cutoffs': {'p33': 0.05, 'p67': 0.2534}, 'combinations': {'low|missing|18-24h': {'n': 404, 'median_absolute_growth': 8.0, 'p90_growth': 114.7, 'top_10pct_hit_rate': 0.0}, 'medium|missing|18-24h': {'n': 328, 'median_absolute_growth': 143.5, 'p90_growth': 1778.6, 'top_10pct_hit_rate': 0.0}, 'medium|missing|12-18h': {'n': 262, 'median_absolute_growth': 119.5, 'p90_growth': 1034.1, 'top_10pct_hit_rate': 0.0038}, 'low|missing|12-18h': {'n': 248, 'median_absolute_growth': 11.0, 'p90_growth': 125.4, 'top_10pct_hit_rate': 0.0}, 'high|missing|18-24h': {'n': 189, 'median_absolute_growth': 2878.0, 'p90_growth': 7249.2, 'top_10pct_hit_rate': 0.0265}, 'medium|missing|6-12h': {'n': 167, 'median_absolute_growth': 171.0, 'p90_growth': 2122.4, 'top_10pct_hit_rate': 0.0}, 'high|missing|12-18h': {'n': 152, 'median_absolute_growth': 2963.5, 'p90_growth': 9745.2, 'top_10pct_hit_rate': 0.0592}, 'high|missing|<6h': {'n': 144, 'median_absolute_growth': 11069.0, 'p90_growth': 49060.0, 'top_10pct_hit_rate': 0.4375}, 'medium|missing|<6h': {'n': 143, 'median_absolute_growth': 270.0, 'p90_growth': 5231.0, 'top_10pct_hit_rate': 0.014}, 'low|missing|6-12h': {'n': 134, 'median_absolute_growth': 12.0, 'p90_growth': 138.4, 'top_10pct_hit_rate': 0.0}, 'low|missing|<6h': {'n': 133, 'median_absolute_growth': 12.0, 'p90_growth': 109.4, 'top_10pct_hit_rate': 0.0}, 'high|missing|6-12h': {'n': 126, 'median_absolute_growth': 4297.5, 'p90_growth': 22882.5, 'top_10pct_hit_rate': 0.1825}, 'high|high|18-24h': {'n': 50, 'median_absolute_growth': 19473.0, 'p90_growth': 103651.7, 'top_10pct_hit_rate': 0.52}, 'high|medium|18-24h': {'n': 50, 'median_absolute_growth': 17053.5, 'p90_growth': 104775.2, 'top_10pct_hit_rate': 0.54}, 'high|low|18-24h': {'n': 39, 'median_absolute_growth': 11352.0, 'p90_growth': 57853.0, 'top_10pct_hit_rate': 0.3846}, 'missing|missing|invalid_or_zero': {'n': 34, 'median_absolute_growth': 26.0, 'p90_growth': 9010.4, 'top_10pct_hit_rate': 0.0}, 'high|high|12-18h': {'n': 29, 'median_absolute_growth': 20755.0, 'p90_growth': 149800.4, 'top_10pct_hit_rate': 0.5172}, 'high|low|6-12h': {'n': 26, 'median_absolute_growth': 25560.5, 'p90_growth': 184194.0, 'top_10pct_hit_rate': 0.7308}, 'high|medium|12-18h': {'n': 26, 'median_absolute_growth': 30302.0, 'p90_growth': 150459.0, 'top_10pct_hit_rate': 0.8077}, 'high|low|12-18h': {'n': 24, 'median_absolute_growth': 11605.0, 'p90_growth': 64990.0, 'top_10pct_hit_rate': 0.4583}, 'high|high|6-12h': {'n': 19, 'median_absolute_growth': 26185.0, 'p90_growth': 149727.6, 'top_10pct_hit_rate': 0.6316}, 'high|low|<6h': {'n': 16, 'median_absolute_growth': 71217.0, 'p90_growth': 511516.0, 'top_10pct_hit_rate': 0.875}, 'high|medium|6-12h': {'n': 16, 'median_absolute_growth': 57877.5, 'p90_growth': 143046.0, 'top_10pct_hit_rate': 0.6875}, 'high|high|<6h': {'n': 7, 'median_absolute_growth': 3965.0, 'p90_growth': 87617.6, 'top_10pct_hit_rate': 0.4286}, 'high|medium|<6h': {'n': 7, 'median_absolute_growth': 13822.0, 'p90_growth': 56337.6, 'top_10pct_hit_rate': 0.4286}, 'medium|low|12-18h': {'n': 4, 'median_absolute_growth': 334.0, 'p90_growth': 891.1, 'top_10pct_hit_rate': 0.0}, 'medium|medium|12-18h': {'n': 4, 'median_absolute_growth': 1217.5, 'p90_growth': 2169.7, 'top_10pct_hit_rate': 0.0}, 'medium|low|18-24h': {'n': 3, 'median_absolute_growth': 207.0, 'p90_growth': 1394.2, 'top_10pct_hit_rate': 0.0}, 'medium|high|<6h': {'n': 2, 'median_absolute_growth': 3136.0, 'p90_growth': 5540.0, 'top_10pct_hit_rate': 0.0}, 'medium|missing|>24h': {'n': 2, 'median_absolute_growth': 136.0, 'p90_growth': 206.4, 'top_10pct_hit_rate': 0.0}, 'low|missing|>24h': {'n': 1, 'median_absolute_growth': 66.0, 'p90_growth': 66.0, 'top_10pct_hit_rate': 0.0}, 'medium|high|12-18h': {'n': 1, 'median_absolute_growth': 75.0, 'p90_growth': 75.0, 'top_10pct_hit_rate': 0.0}, 'medium|high|18-24h': {'n': 1, 'median_absolute_growth': 2799.0, 'p90_growth': 2799.0, 'top_10pct_hit_rate': 0.0}, 'medium|low|<6h': {'n': 1, 'median_absolute_growth': 67.0, 'p90_growth': 67.0, 'top_10pct_hit_rate': 0.0}, 'medium|medium|18-24h': {'n': 1, 'median_absolute_growth': 178.0, 'p90_growth': 178.0, 'top_10pct_hit_rate': 0.0}, 'medium|medium|6-12h': {'n': 1, 'median_absolute_growth': 738.0, 'p90_growth': 738.0, 'top_10pct_hit_rate': 0.0}}}`

## 7. H4 — velocity + V/S + channel size

`{'n_with_subscribers_vph_vps': 327, 'subscriber_bands': {'p33': 93055.8, 'p67': 535442.0}, 'high_vph_cutoff': 3121.0874, 'high_v_s_cutoff': 0.26, 'cohorts': {'baseline_all_with_subs': {'n': 327, 'median_absolute_growth': 19502.0, 'p90_absolute_growth': 124887.8}, 'high_vph_only': {'n': 108, 'median_absolute_growth': 57779.5, 'p90_absolute_growth': 302433.2}, 'high_v_s_only': {'n': 109, 'median_absolute_growth': 19444.0, 'p90_absolute_growth': 128873.2}, 'high_vph_high_v_s_small_or_medium_channel': {'n': 42, 'median_absolute_growth': 29127.0, 'p90_absolute_growth': 228880.1}, 'large_channel_high_vph': {'n': 51, 'median_absolute_growth': 71821.0, 'p90_absolute_growth': 438582.0}}}`

## 8. Passed vs rejected

`{'passed': {'n': 40, 'median_absolute_growth': 4922.5, 'p90_absolute_growth': 153836.1, 'top_10pct_share': 0.375, 'top_5pct_share': 0.225}, 'rejected': {'n': 2754, 'median_absolute_growth': 150.0, 'p90_absolute_growth': 14143.7, 'top_10pct_share': 0.0962, 'top_5pct_share': 0.0476}, 'rejected_in_top_10pct_future_growth': {'count': 265, 'by_filter_reason': {'language': 6, 'min_subscribers': 1, 'min_views': 99, 'min_viral_coeff': 159}}}`

## 9. Rejected future winners

`{'count': 265, 'by_filter_reason': {'language': 6, 'min_subscribers': 1, 'min_views': 99, 'min_viral_coeff': 159}}`

## 10. Keyword differences

`{'multi_keyword_membership_allowed': True, 'keywords': {'AI tools': {'n_membership_rows': 341, 'median_t0_vph': 9.665, 'median_absolute_growth': 134.0, 'p90_absolute_growth': 9034.0, 'top_10pct_winner_count': 25, 'winner_rate': 0.0733}, 'fitness': {'n_membership_rows': 206, 'median_t0_vph': 6.565, 'median_absolute_growth': 109.0, 'p90_absolute_growth': 6863.0, 'top_10pct_winner_count': 14, 'winner_rate': 0.068}, 'gaming': {'n_membership_rows': 184, 'median_t0_vph': 1015.8, 'median_absolute_growth': 8573.0, 'p90_absolute_growth': 94918.7, 'top_10pct_winner_count': 77, 'winner_rate': 0.4185}, 'history': {'n_membership_rows': 328, 'median_t0_vph': 59.98, 'median_absolute_growth': 827.5, 'p90_absolute_growth': 19884.0, 'top_10pct_winner_count': 40, 'winner_rate': 0.122}, 'home improvement': {'n_membership_rows': 329, 'median_t0_vph': 2.43, 'median_absolute_growth': 27.0, 'p90_absolute_growth': 3885.2, 'top_10pct_winner_count': 10, 'winner_rate': 0.0304}, 'interesting facts': {'n_membership_rows': 257, 'median_t0_vph': 68.25, 'median_absolute_growth': 1510.0, 'p90_absolute_growth': 27101.0, 'top_10pct_winner_count': 38, 'winner_rate': 0.1479}, 'productivity': {'n_membership_rows': 283, 'median_t0_vph': 0.9, 'median_absolute_growth': 20.0, 'p90_absolute_growth': 964.4, 'top_10pct_winner_count': 4, 'winner_rate': 0.0141}, 'self improvement': {'n_membership_rows': 278, 'median_t0_vph': 0.77, 'median_absolute_growth': 27.5, 'p90_absolute_growth': 3166.9, 'top_10pct_winner_count': 8, 'winner_rate': 0.0288}, 'technology': {'n_membership_rows': 236, 'median_t0_vph': 38.935, 'median_absolute_growth': 486.5, 'p90_absolute_growth': 26675.5, 'top_10pct_winner_count': 32, 'winner_rate': 0.1356}, 'travel': {'n_membership_rows': 363, 'median_t0_vph': 8.12, 'median_absolute_growth': 194.0, 'p90_absolute_growth': 14160.8, 'top_10pct_winner_count': 33, 'winner_rate': 0.0909}}}`

## 11. Top winners

- `_2hlMsgs4aE` growth=5816102 vph=3181.01 outcome=rejected
- `5rhQGVR3HgI` growth=1507460 vph=31551.32 outcome=rejected
- `4F29ZB3U6IY` growth=633023 vph=15472.48 outcome=rejected
- `fveNvHCoqKs` growth=608445 vph=14328.71 outcome=rejected
- `PCkZ5pfo-pI` growth=521995 vph=11388.52 outcome=rejected
- `SCo9kesuoX8` growth=498698 vph=13555.18 outcome=rejected
- `x7C5KUzNqEA` growth=438582 vph=12908.45 outcome=rejected
- `u13E1qsIrDo` growth=415720 vph=36886.88 outcome=rejected
- `KIn-1EuXx78` growth=390009 vph=6164.54 outcome=rejected
- `5mYAtPYg7Po` growth=367519 vph=3008.95 outcome=rejected

## 12. Conclusions

- **H0_summary:** Initial T0 views were strong associated with absolute growth (Spearman rho=0.7966).
- **H1_summary:** T0 VPH was strong associated with absolute growth (Spearman rho=0.8275).
- **H2_summary:** T0 V/S was weak associated with absolute growth among V/S-available rows (Spearman rho=-0.0884); exploratory only.
- **strongest_observed_signal:** H1_t0_vph
- **strongest_rho:** 0.8275

## 13. Limitations

- Observational snapshot over ~67h; not causal.
- Missing refresh videos excluded; not counted as zero growth.
- V/S coverage is sparse and selection-biased.
- Cross-keyword duplicates collapsed in snapshot; keyword analysis uses multi-membership.
- Negative growth preserved and may reflect YouTube view count corrections.

## 14. Recommended next experiment

- Define stratified sampling using keyword + VPH + age; keep missing V/S explicit.
- Re-run outcome window at >=72h if a longer horizon is needed.
- Compare qualification rule changes using rejected top-growth cohort as audit set.
