# T0 Distribution Review (Stage 1.9B)

**Manifest:** `C:\Projects\Сайт анализ ниш1\artifacts\cohort_T0_20260911_173903_manifest.json`
**Cohort run:** `20260911_173903`
**Schema:** 1.9B

## 1. Dataset overview

- Raw records: **2830**
- Regular records (analysis set): **2716**
- Keywords: 10

## 2. Data quality checks

- Qualification invariant: **True** (2830 = 42 + 2788 + 0)
- Regular split invariant: **True** (2716 + 114 = 2830)
- Parse errors: **0**
- Duplicate video_id (regular, global): **11**
- Nullable enrichment issues: **0**

## 3. Global distributions (regular only)

### Views (n=2716)
- min/median/p75/p90/p95/max: 0.0 / 124.0 / 2231.5 / 11395.5 / 26570.75 / 970211.0

### VPH (available=2684, missing=32)
- min/median/p75/p90/p95/max: 0.0 / 11.63 / 179.59 / 926.829 / 2539.279 / 100182.07
- Bins: `{'<=100': 1829, '100-500': 466, '500-1k': 137, '1k-5k': 183, '5k-10k': 31, '10k-25k': 28, '25k-50k': 6, '50k-100k': 3, '>100k': 1}`

### Views/Subscribers (available=331, missing=2385)
- min/median/p75/p90/p95/max: 0.0 / 0.12 / 0.425 / 1.79 / 5.745 / 2230.0

### Age at T0 (available=2716)
- min/p25/median/p75/p90/max: -0.9404 / 8.7733 / 15.4493 / 20.6384 / 22.8987 / 24.0123
- Buckets: `{'negative_or_zero': 32, '<=1h': 45, '1-3h': 126, '3-6h': 279, '6-12h': 473, '12-18h': 732, '18-24h': 1026, '>24h': 3}`

### Subscribers coverage
- available/missing: 331 / 2385
- status: `{'discovery': 51, 'homepage_fetched': 280, 'unavailable': 1, 'not_attempted': 2384}`

## 4. Per-keyword comparison

| keyword | regular | med views | med VPH | P90 VPH | P95 VPH | VPH avail | V/S avail | med age |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| AI tools | 334 | 112.0 | 10.73 | 442.95 | 932.11 | 329 | 27 | 14.34 |
| productivity | 280 | 9.5 | 0.93 | 55.51 | 135.72 | 276 | 3 | 13.2 |
| fitness | 197 | 79.0 | 8.48 | 528.54 | 1414.64 | 195 | 15 | 14.24 |
| gaming | 187 | 14379.0 | 985.8 | 13941.94 | 20523.1 | 186 | 111 | 17.49 |
| history | 326 | 623.0 | 58.91 | 910.62 | 1511.87 | 325 | 39 | 16.91 |
| technology | 213 | 510.0 | 61.67 | 2180.74 | 3345.36 | 211 | 34 | 16.95 |
| self improvement | 275 | 8.0 | 0.8 | 133.26 | 291.51 | 268 | 9 | 15.4 |
| interesting facts | 255 | 909.0 | 70.8 | 1511.3 | 2469.23 | 250 | 47 | 13.96 |
| home improvement | 297 | 57.0 | 3.46 | 228.08 | 589.44 | 294 | 18 | 18.18 |
| travel | 352 | 105.5 | 8.5 | 695.71 | 1867.98 | 350 | 28 | 14.19 |

## 5. VPH tail analysis

Global: `{'>=1000': 252, '>=5000': 69, '>=10000': 38, '>=25000': 10, '>=50000': 4, '>=100000': 1}`
- **AI tools** (n=334): `{'>=1000': 15, '>=5000': 1, '>=10000': 0, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **productivity** (n=280): `{'>=1000': 1, '>=5000': 0, '>=10000': 0, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **fitness** (n=197): `{'>=1000': 14, '>=5000': 2, '>=10000': 1, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **gaming** (n=187): `{'>=1000': 92, '>=5000': 39, '>=10000': 27, '>=25000': 8, '>=50000': 3, '>=100000': 1}`
- **history** (n=326): `{'>=1000': 31, '>=5000': 8, '>=10000': 2, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **technology** (n=213): `{'>=1000': 26, '>=5000': 7, '>=10000': 5, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **self improvement** (n=275): `{'>=1000': 5, '>=5000': 1, '>=10000': 0, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **interesting facts** (n=255): `{'>=1000': 34, '>=5000': 4, '>=10000': 0, '>=25000': 0, '>=50000': 0, '>=100000': 0}`
- **home improvement** (n=297): `{'>=1000': 5, '>=5000': 1, '>=10000': 1, '>=25000': 1, '>=50000': 1, '>=100000': 0}`
- **travel** (n=352): `{'>=1000': 29, '>=5000': 6, '>=10000': 2, '>=25000': 1, '>=50000': 0, '>=100000': 0}`

## 6. V/S coverage analysis

- Global V/S available: **331** / 2716 regular (12.19%)

## 7. Age distribution

`{'negative_or_zero': 32, '<=1h': 45, '1-3h': 126, '3-6h': 279, '6-12h': 473, '12-18h': 732, '18-24h': 1026, '>24h': 3}`

## 8. Important observations

- All main statistics use **regular** records only; raw JSONL retains short/live/unknown for diagnostics.
- VPH tail is heavy-skewed; a small number of videos dominate upper percentiles.
- Subscriber fetch `not_attempted` is common on rejected rows and must not be read as zero.

## 9. Limitations

- T0 snapshot only; no T24/T72 outcomes exist yet.
- VPH is discovery-time velocity, not a validated predictor.
- V/S coverage is limited to records with final_subscribers (mostly passed candidates).
- not_attempted subscriber_fetch is not equivalent to zero subscribers.
- Immutability of discovery fields cannot be verified from JSONL alone.

## 10. Recommendations for the NEXT sampling step

- Stratify by keyword: distributions differ materially across the 10 niches; avoid pooling without keyword strata.
- Consider VPH strata using tail bins (e.g. <=1k, 1k–10k, >=10k); ~38 regular records have VPH >= 10k.
- Consider age_hours_at_t0 strata (e.g. <=6h vs 6–18h vs >18h); counts ~450 / 1237 / ~1029.
- Consider discovery_views strata aligned with qualification threshold (10k+) vs sub-threshold rejected band.
- V/S strata apply only to 331 regular records with subscribers; keep missing V/S as its own stratum.
- Keywords below ~200 regular records may need proportional caps rather than fixed N: fitness, gaming.
- Do not auto-select final experimental N until stratified sampling rules are agreed offline.

## Verification

- NO_NETWORK_REQUESTS: **True**
- NO_DB_WRITES: **True**
- Records processed (raw / regular): 2830 / 2716
