# NBA score projection model v2 (research)

Walk-forward staged build — MAE after each layer (OOS 2022-23 – 2024-25).

**v1 baseline weakness:** score-derived pseudo-possessions, no opponent-adjusted ridge, and PPP/ORtg scale mix — explains ~13.4 margin MAE vs ~10.4 close.

## Stage MAE ladder

| Stage | Margin MAE (model / close / blend) | Total MAE (model / close / blend) | Blend w |
|-------|-----------------------------------|-----------------------------------|---------|
| 0: v1_baseline (score-only EMA, no opp ridge) | 13.358 / 10.375 / 10.375 | 17.353 / 14.285 / 14.285 | 0.00 |
| 1: possession ridge (ESPN box OR poss est) | 11.317 / 10.375 / 10.374 | 15.327 / 14.285 / 14.286 | 0.05 |
| 2: + preseason priors (1/3 mean regress) | 11.075 / 10.375 / 10.372 | 15.118 / 14.285 / 14.283 | 0.05 |
| 3: + schedule (rest/B2B/3-in-4/travel/altitude) | 10.849 / 10.375 / 10.37 | 15.118 / 14.285 / 14.286 | 0.10 |
| 4: + player minutes layer (0-min injury proxy) | 10.863 / 10.375 / 10.37 | 15.118 / 14.285 / 14.286 | 0.10 |

## Final stage (3) vs open & close

- Margin MAE vs **open**: 12.18
- Margin MAE vs **close**: 10.375

### ATS / O-U (≥1pt edge vs close / vs open)

- ATS vs close: {'n': 3140, 'record': '1610-1530-0', 'units_at_110': -66.36}
- ATS vs open: {'n': 3269, 'record': '1665-1604-0', 'units_at_110': -90.36}
- O/U vs close: {'n': 3415, 'record': '1708-1707-0', 'units_at_110': -154.27}

## CLV audit — SBR true openers (2010-11 – 2020-21, walk-forward stage 3)

_Yahoo `pregame_odds` ≈ close → prior ~90% move hits were **artifact** (subset + pseudo-open)._

{'seasons': ['2010-11', '2011-12', '2012-13', '2013-14', '2014-15', '2015-16', '2016-17', '2017-18', '2018-19', '2019-20', '2020-21'], 'n_sbr_games': 12581, 'n_with_open_close_diff_ge_half': 10535, 'line_move_hit_rate_ge1pt_model_edge': 0.508, 'line_move_n': 9172, 'line_move_corr': -0.127, 'ats_opener_ge1': {'n': 9172, 'record': '4486-4515-171', 'units_at_110': -436.82}, 'ats_opener_ge2': {'n': 6193, 'record': '3034-3046-113', 'units_at_110': -287.82}, 'ats_opener_ge3': {'n': 3989, 'record': '1941-1979-69', 'units_at_110': -214.45}, 'audit_note': 'Uses SBR home_open_spread vs home_close_spread; grades ATS vs opener spread. Walk-forward model from full history; no close line in projection.'}

## Verdict

Margin improved **13.358** → **10.849** (stage 3) vs close **10.375** — near market, not beatable. Totals were broken by ridge without a league-mean intercept (~20 MAE); fixed to **15.118** vs close **14.285** (pace×ORtg path). **SBR CLV** (true openers): ~51% line-move direction, negative ATS vs opener at 1/2/3+ pt edges — no credible CLV edge; Yahoo ~90% was pseudo-open/selection. Stage 4 player proxy is margin-only (+0.01 MAE); skip for totals.

## Tonight's slate (final stage engine)

| Away @ Home | Proj | Margin | Total | Close spr/tot |
|-------------|------|--------|-------|---------------|
| LAL @ UTA | 119.5-111.9 | -7.6 | 231.6 | None / None |
| IND @ BKN | 116.2-105.0 | -11.2 | 220.2 | None / None |
| ORL @ NYK | 103.4-110.9 | +7.5 | 213.4 | None / None |
| TOR @ MIN | 105.5-119.2 | +13.7 | 223.9 | None / None |
| LAC @ OKC | 107.2-116.4 | +9.2 | 222.6 | None / None |
| DET @ PHI | 119.8-111.2 | -8.6 | 230.1 | None / None |
| MEM @ SAC | 119.4-119.6 | +0.2 | 238.1 | None / None |
