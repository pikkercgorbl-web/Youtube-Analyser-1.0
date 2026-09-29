# Signal Robustness T0 → T67 (Stage 1.9E)

## 1. Executive summary

- **Primary question:** T0 VPH adds information beyond T0 views for ~67.1h absolute growth.
- Identical VPH population **n=2652** (regular, valid views/outcome, non-null VPH).
- Spearman views **ρ=0.7978**; VPH **ρ=0.8253** (Δρ=0.0275).
- Bootstrap 95% CI Δρ (VPH−views): **{'low': 0.022, 'high': 0.0331}**.
- Top-10% signal → top-10% winner recall: views **0.6208**, VPH **0.7026**.
- At top-10% overlap, **VPH-only** median growth **27015.5** vs **views-only** **9238.5** (winner rate 0.75 vs 0.2).
- Within-keyword VPH percentile **did not** beat raw VPH on top-10% recall (0.5242 vs 0.7026).

## 2. Analysis population

- Joined rows loaded: **2794**
- Primary (regular + views + outcome): **2683**
- VPH-eligible (identical head-to-head): **2652**
- Negative growth preserved: **20**
- Input JSONL is Stage 1.9D joined export (refreshed-only); refresh_status filter applied when field is present.

### Outcome winner thresholds (absolute_view_growth, primary population)

- Top 25%: **3283.5**
- Top 10%: **16435.80000000001**
- Top 5%: **40174.00000000001**
- Top 1%: **157324.4199999984**

## 3. Views vs VPH head-to-head

### Spearman (identical n)
- t0_views ↔ growth: ρ=0.7978
- t0_vph ↔ growth: ρ=0.8253

### t0_views captures
- selected=266, tp=167, precision=0.6278, recall=0.6208, lift=6.1895

### t0_vph captures
- selected=266, tp=189, precision=0.7105, recall=0.7026, lift=7.0049

## 4. Views/VPH overlap (top 10%)

- Intersection **226**, views-only **40**, VPH-only **40**, Jaccard **0.7386**.

| Group | n | median growth | P90 | top-10% winner rate |
| --- | ---: | ---: | ---: | ---: |
| Both | 226 | 31097.5 | 173322.5 | 0.7035 |
| Views only | 40 | 9238.5 | 40059.7 | 0.2 |
| VPH only | 40 | 27015.5 | 89832.3 | 0.75 |
| Neither | 2346 | 116.0 | 5441.0 | 0.0307 |

## 5. VPH controlling for T0 views

View deciles × within-decile VPH tertiles — see JSON `within_views_vph_control`. Upper deciles (D8–D10): higher VPH tertiles show higher median future growth.

## 6. Age robustness

| Band | n | ρ views | ρ VPH | median growth |
| --- | ---: | ---: | ---: | ---: |
| 0-3h | 168 | 0.8191 | 0.8133 | 1136.5 |
| 12-18h | 724 | 0.8084 | 0.8068 | 131.0 |
| 18-24h | 1014 | 0.8372 | 0.837 | 141.5 |
| 3-6h | 276 | 0.8385 | 0.8374 | 427.0 |
| 6-12h | 467 | 0.8087 | 0.8158 | 290.0 |
| >24h | 3 | 0.5 | 0.5 | 66.0 |

## 7. Keyword robustness

- Keywords where ρ(VPH) > ρ(views): **AI tools, fitness, gaming, history, home improvement, interesting facts, productivity, self improvement, technology, travel**
- Keywords where views > VPH: **none**

| Keyword | n | ρ views | ρ VPH | Δρ |
| --- | ---: | ---: | ---: | ---: |
| AI tools | 324 | 0.8898 | 0.9176 | 0.0278 |
| fitness | 194 | 0.5386 | 0.5701 | 0.0315 |
| gaming | 183 | 0.452 | 0.5395 | 0.0875 |
| history | 325 | 0.7814 | 0.8659 | 0.0845 |
| home improvement | 293 | 0.6226 | 0.6611 | 0.0385 |
| interesting facts | 247 | 0.8259 | 0.8653 | 0.0394 |
| productivity | 274 | 0.6389 | 0.6516 | 0.0127 |
| self improvement | 266 | 0.8083 | 0.8213 | 0.013 |
| technology | 210 | 0.8303 | 0.8665 | 0.0362 |
| travel | 347 | 0.7751 | 0.8223 | 0.0472 |

## 8. Within-keyword normalization

- Rule: multi-keyword videos store per-keyword percentiles; global comparison uses MAX; median tested as sensitivity
- Raw VPH top-10% capture recall **0.7026**
- Within-keyword MAX percentile recall **0.5242**

## 9. Qualification diagnostics (passed vs future winners)

Top-10% winners: precision **0.375**, recall **0.0558**, lift **3.7402** (selected n=40).

## 10. Failure reason diagnostics

first_failure_reason does not prove the video would pass all later filters

- **language** (n=15): median growth 12140.0, top-10% winner rate 0.4
- **min_subscribers** (n=1): median growth 70286.0, top-10% winner rate 1.0
- **min_views** (n=2389): median growth 116.0, top-10% winner rate 0.0385
- **min_viral_coeff** (n=238): median growth 26040.5, top-10% winner rate 0.6513

## 11. min_views boundary (~10k)

- Below 10k views but global top-10% winners: **92**
See JSON bins and example rows for T0 VPH/age/keyword at rejection boundary.

## 12. min_viral_coeff diagnostics

- Rejected min_viral_coeff with V/S: n=238; without V/S: n=0. Future winners in this bucket: **155** (V/S coverage 155).

## 13. Signal-selection curves (top-10% future winners)

| Budget | views recall | VPH recall | within-kw MAX recall |
| --- | ---: | ---: | ---: |
| top 5% | 0.3903 | 0.3941 | 0.3271 |
| top 10% | 0.6208 | 0.7026 | 0.5242 |
| current qualification | — | — | recall=0.0558 (n=40) |

## 14. Bootstrap stability

- Method: bootstrap_percentile_CI_n=1000_seed=42
- Spearman views CI: {'low': 0.7751, 'high': 0.8181}
- Spearman VPH CI: {'low': 0.8039, 'high': 0.8451}
- Δρ (VPH−views) CI: {'low': 0.022, 'high': 0.0331}
- Top-10% recall diff (VPH−views) CI: {'low': 0.0486, 'high': 0.1224}

## 15. Decision matrix

| Signal | Verdict | Rationale |
| --- | --- | --- |
| T0 views | **STRONG** | Strong global association and retrieval; primary scale signal. |
| T0 VPH | **STRONG** | Higher ρ and recall vs views; VPH-only overlap bucket outperforms views-only at top-10%. |
| within-keyword VPH percentile | **WEAK** | Did not beat raw global VPH on top-10% winner recall in this cohort. |
| V/S | **WEAK** | Selection-biased sample; no reliable global association. |
| current qualification | **PROMISING** | High precision, very low recall — misses most future winners. |

## 16. Limitations

- Observational ~67h window; association not causation.
- Winner thresholds derived from same dataset — hypotheses for next cohort only.
- V/S coverage sparse and selection-biased.
- first_failure_reason is not exclusive failure attribution.
- Global VPH confounded by keyword velocity baselines.

## 17. Recommendation for next stage

- Validate VPH vs views incremental value on a fresh independent T0→T72 cohort.
- Prototype niche-relative VPH percentile in offline replay before any production change.
- Audit min_views/min_viral_coeff false negatives with velocity-aware rules as experiments only.
