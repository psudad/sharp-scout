# NBA score projection model (research)

Research only — independent team ratings → projected points/margin/total vs closing lines.

## Out-of-sample (2022-23 – 2024-25)

Games: **3953**

### Mean absolute error

| Target | Model | Market close | Model⊕market blend |
|--------|-------|--------------|-------------------|
| Margin | 13.052 | 13.31 | 12.353 (w=0.40) |
| Total | 16.661 | 16.511 | 15.475 |

### ATS / O-U when projection beats close by ≥ N points (flat -110)

_Note: |model−market| ≥1pt selects ~93% of OOS games; flat units below are **not** independent proof of betting edge (use MAE + calibration; paper-trade CLV before any live use)._

- **ATS ≥1pt edge:** 2343-1337-0 (793.0u, n=3680)
- **ATS ≥2pt edge:** 2213-1222-0 (789.82u, n=3435)
- **ATS ≥3pt edge:** 2078-1106-0 (783.09u, n=3184)
- **ATS ≥4pt edge:** 1943-981-0 (785.36u, n=2924)

- **O/U ≥1pt edge:** 2325-1426-0 (687.64u, n=3751)
- **O/U ≥2pt edge:** 2245-1328-0 (712.91u, n=3573)
- **O/U ≥3pt edge:** 2136-1244-0 (697.82u, n=3380)
- **O/U ≥4pt edge:** 2045-1156-0 (703.09u, n=3201)

### Early (Oct–Nov) vs later

- Early: {"n": 890, "margin_mae_model": 12.532, "margin_mae_market": 13.004}
- Later: {"n": 3063, "margin_mae_model": 13.203, "margin_mae_market": 13.398}

## Verdict

Margin MAE is **modestly below** the closing line OOS (~0.26 pts); totals lag the market slightly. That is research-grade signal, not a license to bet: possession-level PBP, injury/minutes, multi-book closes, and paper-trade CLV at realistic thresholds would be required before the NBA lane.

## Tonight's slate (projections vs board lines if present)

| Away @ Home | Proj score | Margin | Total | Close spread | Close total |
|-------------|------------|--------|-------|--------------|-------------|
| LAL @ UTA | 114.0-99.3 | -14.7 | 213.3 | None | None |
| IND @ BKN | 129.1-108.6 | -20.5 | 237.6 | 7.0 | 232.5 |
| ORL @ NYK | 107.4-117.0 | +9.6 | 224.4 | None | None |
| TOR @ MIN | 107.5-113.4 | +5.9 | 220.9 | -1.0 | 229.5 |
| LAC @ OKC | 133.4-103.5 | -29.9 | 237.0 | -17.0 | 225.0 |
| DET @ PHI | 93.1-102.7 | +9.6 | 195.8 | 1.0 | 228.5 |
| MEM @ SAC | 112.7-114.0 | +1.3 | 226.7 | 3.0 | 235.0 |
