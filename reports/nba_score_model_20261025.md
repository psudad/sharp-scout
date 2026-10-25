# NBA score projection model (research)

Research only — independent team ratings → projected points/margin/total vs closing lines.

## Out-of-sample (2022-23 – 2024-25)

Games: **3941**

Line join QA (OOS): mean(margin+home_spread)=0.0412, share |net|<3pt=0.2065

### Mean absolute error

| Target | Model | Market close | Model⊕market blend |
|--------|-------|--------------|-------------------|
| Margin | 13.358 | 10.375 | 10.375 (w=0.00) |
| Total | 17.353 | 14.285 | 14.285 |

### ATS / O-U when projection beats close by ≥ N points (flat -110)

### Data fixes in this report

- Yahoo↔ESPN score join used undated away@home fallback (latest rematch), pairing wrong finals to closing lines.
- ESPN cache keyed by kickoff date with sparse coverage; rebuilt as scoreboard-request-date keys only (v2).
- Yahoo scores now require spread_home_won / total_over_won agreement (±1 day date shift allowed).

- **ATS ≥1pt edge:** 1823-1782-0 (-124.73u, n=3605)
- **ATS ≥2pt edge:** 1690-1636-0 (-99.64u, n=3326)
- **ATS ≥3pt edge:** 1525-1461-0 (-74.64u, n=2986)
- **ATS ≥4pt edge:** 1359-1326-0 (-90.55u, n=2685)

- **O/U ≥1pt edge:** 1846-1828-0 (-149.82u, n=3674)
- **O/U ≥2pt edge:** 1713-1691-0 (-133.73u, n=3404)
- **O/U ≥3pt edge:** 1591-1580-0 (-133.64u, n=3171)
- **O/U ≥4pt edge:** 1457-1461-0 (-136.45u, n=2918)

### Early (Oct–Nov) vs later

- Early: {"n": 890, "margin_mae_model": 11.987, "margin_mae_market": 9.89}
- Later: {"n": 3051, "margin_mae_model": 13.758, "margin_mae_market": 10.517}

## Verdict

The walk-forward efficiency model **does not beat the closing spread** on margin MAE out-of-sample. Totals are closer but still slightly behind or tied with the market. It is **not production-worthy** without richer data (possession-level PBP, injuries, multi-book openers) and a calibrated ensemble that proves OOS ATS/O-U edge after vig.

## Tonight's slate (projections vs board lines if present)

| Away @ Home | Proj score | Margin | Total | Close spread | Close total |
|-------------|------------|--------|-------|--------------|-------------|
| LAL @ UTA | 105.8-105.9 | +0.1 | 211.7 | None | None |
| IND @ BKN | 101.3-104.6 | +3.2 | 205.9 | 7.0 | 232.5 |
| ORL @ NYK | 104.8-115.5 | +10.7 | 220.3 | None | None |
| TOR @ MIN | 120.1-110.8 | -9.3 | 230.9 | -1.0 | 229.5 |
| LAC @ OKC | 95.7-111.8 | +16.1 | 207.5 | -17.0 | 225.0 |
| DET @ PHI | 116.3-109.9 | -6.4 | 226.2 | 1.0 | 228.5 |
| MEM @ SAC | 115.5-112.6 | -2.9 | 228.1 | 3.0 | 235.0 |
