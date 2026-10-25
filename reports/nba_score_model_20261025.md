# NBA score projection model v2 (research)

Walk-forward staged build — MAE after each layer (OOS 2022-23 – 2024-25).

## Stage MAE ladder

| Stage | Margin MAE (model / close / blend) | Total MAE (model / close / blend) | Blend w |
|-------|-----------------------------------|-----------------------------------|---------|
| 0: v1_baseline (score-only EMA, no opp ridg… | 13.358 / 10.375 / 10.375 | 17.353 / 14.285 / 14.285 | 0.00 |
| 1: possession ridge (ESPN box OR poss est)… | 11.079 / 10.375 / 10.371 | 19.825 / 14.285 / 14.315 | 0.05 |
| 2: + preseason priors (1/3 mean regress)… | 11.056 / 10.375 / 10.372 | 19.936 / 14.285 / 14.307 | 0.05 |
| 3: + schedule (rest/B2B/3-in-4/travel/altit… | 10.827 / 10.375 / 10.37 | 20.157 / 14.285 / 14.369 | 0.10 |
| 4: + player minutes layer (0-min injury pro… | 10.859 / 10.375 / 10.371 | 35.219 / 14.285 / 14.611 | 0.10 |

## Final stage (4) vs open & close

- Margin MAE vs **open**: 12.18
- Margin MAE vs **close**: 10.375

### ATS / O-U (≥1pt edge vs close / vs open)

- ATS vs close: {'n': 3152, 'record': '1610-1542-0', 'units_at_110': -78.36}
- ATS vs open: {'n': 3280, 'record': '1661-1619-0', 'units_at_110': -109.0}
- O/U vs close: {'n': 3938, 'record': '1934-2004-0', 'units_at_110': -245.82}

## Line-move / CLV proxy (stage 5)

{'n_oos': 3941, 'n_oos_with_open_close_move': 1473, 'spread_move_hit_rate_ge1': 0.929, 'spread_move_n_ge1': 1356, 'spread_move_corr_ge1': 0.867, 'total_move_hit_rate_ge1': 0.704, 'total_move_n_ge1': 98, 'total_move_corr_ge1': 0.002, 'combo_model_sharp_stake_spread': {'n': 1239, 'hit_rate': 0.637}}

## Verdict

v2 stage-4 margin MAE **10.859** still **above** the close (**10.375**); v1 was **13.358**. Beating open→close CLV is the realistic path; production needs richer injury feeds and multi-book opens.

## Tonight's slate (final stage engine)

| Away @ Home | Proj | Margin | Total | Close spr/tot |
|-------------|------|--------|-------|---------------|
| LAL @ UTA | 116.2-108.7 | -7.6 | 224.9 | None / None |
| IND @ BKN | 114.2-103.0 | -11.1 | 217.2 | None / None |
| ORL @ NYK | 101.1-108.6 | +7.5 | 209.6 | None / None |
| TOR @ MIN | 102.8-116.5 | +13.7 | 219.4 | None / None |
| LAC @ OKC | 105.6-114.7 | +9.2 | 220.3 | None / None |
| DET @ PHI | 116.7-108.2 | -8.6 | 224.9 | None / None |
| MEM @ SAC | 116.1-116.2 | +0.1 | 232.3 | None / None |
