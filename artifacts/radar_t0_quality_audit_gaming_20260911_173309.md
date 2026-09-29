# T0 Data Quality Audit

**Source:** `C:\Projects\Сайт анализ ниш1\artifacts\cohort_T0_20260911_172900_gaming.jsonl`
**Keyword:** gaming
**Final verdict:** `BLOCKED`

## 1. Dataset overview

- Total records: **195**

## 2. Integrity

- Total records: 195
- Unique video_id: 195
- Duplicate video_id count: 0
- Passed: 19
- Rejected: 176
- Parse errors: 0
- Invariant OK: **True** (`195 == 19 + 176 + 0`)

## 3. Time quality

- `published_at_gt_discovered_at`: 1 (0.51%)
- `age_hours_at_t0_lt_0`: 1 (0.51%)
- `age_hours_at_t0_eq_0`: 0 (0.0%)
- `age_hours_at_t0_lt_1`: 3 (1.54%)
- `age_hours_at_t0_lt_3`: 9 (4.62%)
- `age_hours_at_t0_lt_6`: 23 (11.79%)
- `age_hours_at_t0_lt_24`: 195 (100.0%)
- `age_hours_at_t0_gte_24`: 0 (0.0%)
- Age min/median/max: -0.8585 / 17.3519 / 23.4609 hours

## 4. VPH quality

- VPH available: 194
- VPH missing: 1
- VPH <= 0: 0
- VPH min/median/max: 19.48 / 959.36 / 106105.61
- Arithmetic sanity mismatches: 24 / 194

## 5. Subscriber enrichment

- final_subscribers available: 117
- final_subscribers missing: 78
- Status breakdown: `{'discovery': 4, 'homepage_fetched': 113, 'unavailable': 0, 'not_attempted': 78}`

### By qualification group

- **all**: available=117 (60.0%), missing=78, breakdown={'discovery': 4, 'homepage_fetched': 113, 'unavailable': 0, 'not_attempted': 78}
- **passed**: available=19 (100.0%), missing=0, breakdown={'discovery': 0, 'homepage_fetched': 19, 'unavailable': 0, 'not_attempted': 0}
- **rejected**: available=98 (55.68%), missing=78, breakdown={'discovery': 4, 'homepage_fetched': 94, 'unavailable': 0, 'not_attempted': 78}

## 6. Views/Subscribers

- views_per_subscriber available: 117
- missing: 78
- <= 0: 5
- min/median/max: 0.0 / 0.11 / 658.75
- Arithmetic sanity mismatches: 0 / 117

## 7. Format quality

- Content format breakdown: `{'regular': 195, 'short': 0, 'live': 0, 'unknown': 0}`
- format_violations (is_short/is_live): 0
- Matches expected validation cohort: **True**

## 8. Consistency

- discovery_views present/missing: 195 / 0
- discovered_at present/missing: 195 / 0
- Unique keywords: ['gaming']
- enrichment did not mutate discovery_views: cannot verify from dataset alone
- enrichment did not mutate discovered_at: cannot verify from dataset alone
- video_id immutable: cannot verify from dataset alone
- keyword immutable: cannot verify from dataset alone

## 9. Outliers

- **negative_age**: 1
  - `55acolzGZLU`: {'video_id': '55acolzGZLU', 'reason': 'negative_age', 'discovery_views': 5244, 'discovered_at': '2026-09-11T17:26:30.361103+00:00', 'published_at': '2026-09-11T18:18:01+00:00', 'age_hours_at_t0': -0.8585, 'vph_at_t0': None, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'partial'}
- **extremely_high_vph**: 8
  - `56xrHGO_xHU`: {'video_id': '56xrHGO_xHU', 'reason': 'extremely_high_vph', 'discovery_views': 227288, 'discovered_at': '2026-09-11T17:24:46.532183+00:00', 'published_at': '2026-09-11T15:16:15+00:00', 'age_hours_at_t0': 2.1421, 'vph_at_t0': 106105.61, 'final_subscribers': 3810000, 'views_per_subscriber_at_t0': 0.06, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `9qf7RAQPHbY`: {'video_id': '9qf7RAQPHbY', 'reason': 'extremely_high_vph', 'discovery_views': 454032, 'discovered_at': '2026-09-11T17:24:46.533181+00:00', 'published_at': '2026-09-11T12:11:50+00:00', 'age_hours_at_t0': 5.2157, 'vph_at_t0': 87050.96, 'final_subscribers': 478000, 'views_per_subscriber_at_t0': 0.95, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `uD_Mp4BOolU`: {'video_id': 'uD_Mp4BOolU', 'reason': 'extremely_high_vph', 'discovery_views': 970211, 'discovered_at': '2026-09-11T17:26:14.058288+00:00', 'published_at': '2026-09-10T23:59:29+00:00', 'age_hours_at_t0': 17.4458, 'vph_at_t0': 55612.71, 'final_subscribers': 138000, 'views_per_subscriber_at_t0': 7.03, 'qualification_state': 'passed', 'enrichment_status': 'ok'}
- **extremely_low_vph**: 62
  - `Ey9pM5fY7kc`: {'video_id': 'Ey9pM5fY7kc', 'reason': 'extremely_low_vph', 'discovery_views': 83, 'discovered_at': '2026-09-11T17:28:14.458823+00:00', 'published_at': '2026-09-11T13:12:32+00:00', 'age_hours_at_t0': 4.2618, 'vph_at_t0': 19.48, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `7k5X4bSPWWw`: {'video_id': '7k5X4bSPWWw', 'reason': 'extremely_low_vph', 'discovery_views': 269, 'discovered_at': '2026-09-11T17:28:29.939123+00:00', 'published_at': '2026-09-11T04:37:16+00:00', 'age_hours_at_t0': 12.8539, 'vph_at_t0': 20.93, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `gdNsuVrd610`: {'video_id': 'gdNsuVrd610', 'reason': 'extremely_low_vph', 'discovery_views': 604, 'discovered_at': '2026-09-11T17:28:08.959804+00:00', 'published_at': '2026-09-10T18:15:01+00:00', 'age_hours_at_t0': 23.2189, 'vph_at_t0': 26.01, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
- **extremely_high_views_per_subscriber**: 14
  - `vEhI441-85o`: {'video_id': 'vEhI441-85o', 'reason': 'extremely_high_vps', 'discovery_views': 2635, 'discovered_at': '2026-09-11T17:27:38.791967+00:00', 'published_at': '2026-09-10T21:04:28+00:00', 'age_hours_at_t0': 20.3863, 'vph_at_t0': 129.25, 'final_subscribers': 4, 'views_per_subscriber_at_t0': 658.75, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `1iNyq08MbA0`: {'video_id': '1iNyq08MbA0', 'reason': 'extremely_high_vps', 'discovery_views': 173715, 'discovered_at': '2026-09-11T17:28:35.709594+00:00', 'published_at': '2026-09-11T01:00:06+00:00', 'age_hours_at_t0': 16.4749, 'vph_at_t0': 10544.21, 'final_subscribers': 923, 'views_per_subscriber_at_t0': 188.21, 'qualification_state': 'passed', 'enrichment_status': 'ok'}
  - `LA_-0JxG128`: {'video_id': 'LA_-0JxG128', 'reason': 'extremely_high_vps', 'discovery_views': 705352, 'discovered_at': '2026-09-11T17:26:30.361103+00:00', 'published_at': '2026-09-11T01:50:09+00:00', 'age_hours_at_t0': 15.6059, 'vph_at_t0': 45197.68, 'final_subscribers': 24900, 'views_per_subscriber_at_t0': 28.33, 'qualification_state': 'passed', 'enrichment_status': 'ok'}
- **zero_subscribers_with_nonnull_vps**: 0
- **missing_vph_despite_valid_age_views**: 0
- **missing_final_subscribers**: 78
  - `5mYAtPYg7Po`: {'video_id': '5mYAtPYg7Po', 'reason': 'missing_final_subscribers', 'discovery_views': 6845, 'discovered_at': '2026-09-11T17:24:19.051565+00:00', 'published_at': '2026-09-11T15:00:31+00:00', 'age_hours_at_t0': 2.3967, 'vph_at_t0': 2856.03, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `zsPygpbzJcw`: {'video_id': 'zsPygpbzJcw', 'reason': 'missing_final_subscribers', 'discovery_views': 9356, 'discovered_at': '2026-09-11T17:24:19.051565+00:00', 'published_at': '2026-09-11T13:00:36+00:00', 'age_hours_at_t0': 4.3953, 'vph_at_t0': 2128.64, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}
  - `w6TKr1jDiKI`: {'video_id': 'w6TKr1jDiKI', 'reason': 'missing_final_subscribers', 'discovery_views': 906, 'discovered_at': '2026-09-11T17:24:19.051565+00:00', 'published_at': '2026-09-11T15:21:23+00:00', 'age_hours_at_t0': 2.0489, 'vph_at_t0': 442.19, 'final_subscribers': None, 'views_per_subscriber_at_t0': None, 'qualification_state': 'rejected', 'enrichment_status': 'ok'}

## 10. Final verdict

**BLOCKED**

### Caveats

- **Negative age or published_at after discovered_at (API/Innertube clock skew)** — 1 records (non-blocking): VPH is null or unreliable when publish time is after discovery snapshot
- **VPH arithmetic sanity mismatches** — 24 records (BLOCKS): Stored vph_at_t0 may not match discovery_views/age_hours_at_t0
- **Subscriber fetch not attempted for many channels** — 78 records (non-blocking): final_subscribers and views_per_subscriber_at_t0 unavailable for viral coefficient at T0
