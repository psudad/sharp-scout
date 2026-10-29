# NBA Pace totals — current-season method backtest

Compares **legacy** totals (prior-blended pace/ORTG from committed priors + history) vs **2026-27 only** game-log averages (this PR). Injury-adj totals use the same ESPN absence rules; spreads unchanged.

Min gap for play flag: **3.0 pt** raw + injury rules (v1).

## 2026-10-25 (ET slate)

| Game | Line | Actual | Old total | New total | Old inj total | New inj total | Old gap | New gap | v1 play (new) | Result |
|------|------|--------|-----------|-----------|---------------|---------------|---------|---------|---------------|--------|
| IND @ BKN | 231.5 | 245 | 228.1 | 231.1 | 228.1 | 231.1 | -3.4 | -0.4 | — | — |
| ORL @ NYK | 224.5 | 213 | 224.8 | 213.6 | 224.8 | 213.6 | +0.3 | -10.9 | ORL @ NYK: Under 224.5 | W |
| LAC @ OKC | 224.5 | 209 | 223.4 | 202.7 | 223.4 | 202.7 | -1.1 | -21.8 | LAC @ OKC: Under 224.5 | W |
| TOR @ MIN | 229.5 | 211 | 224.1 | 206.0 | 224.1 | 206.0 | -5.4 | -23.5 | TOR @ MIN: Under 229.5 | W |
| DET @ PHI | 228.5 | 199 | 228.3 | 232.0 | 228.3 | 232.0 | -0.2 | +3.5 | DET @ PHI: Over 228.5 | L |
| MEM @ SAC | 234.5 | 235 | 235.1 | 229.2 | 235.1 | 229.2 | +0.6 | -5.3 | MEM @ SAC: Under 234.5 | L |

## 2026-10-26 (ET slate)

| Game | Line | Actual | Old total | New total | Old inj total | New inj total | Old gap | New gap | v1 play (new) | Result |
|------|------|--------|-----------|-----------|---------------|---------------|---------|---------|---------------|--------|
| WAS @ CHA | 228 | 213 | 230.1 | 221.6 | 230.1 | 221.6 | +2.1 | -6.4 | WAS @ CHA: Under 228 | W |
| MIN @ CLE | 232 | 252 | 230.6 | 220.6 | 230.6 | 220.6 | -1.4 | -11.4 | MIN @ CLE: Under 232 | L |
| CHI @ BOS | 233 | 233 | 230.1 | 234.8 | 230.1 | 234.8 | -2.9 | +1.8 | — | — |
| DAL @ MIA | 240.75 | 222 | 234.6 | 240.9 | 234.6 | 240.9 | -6.1 | +0.1 | — | — |
| IND @ MIL | 238.5 | 212 | 234.0 | 257.9 | 234.0 | 257.9 | -4.5 | +19.4 | IND @ MIL: Over 238.5 | L |
| PHX @ OKC | 221.5 | 239 | 222.5 | 203.4 | 222.5 | 203.4 | +1.0 | -18.1 | PHX @ OKC: Under 221.5 | L |
| ATL @ HOU | 229.5 | 230 | 229.2 | 235.7 | 229.2 | 235.7 | -0.3 | +6.2 | ATL @ HOU: Over 229.5 | W |
| MEM @ UTA | 237.5 | 215 | 241.2 | 250.3 | 241.2 | 250.3 | +3.7 | +12.8 | MEM @ UTA: Over 237.5 | L |
| GSW @ DEN | 236.5 | 248 | 241.6 | 240.1 | 241.6 | 240.1 | +5.1 | +3.6 | GSW @ DEN: Over 236.5 | W |

## 2026-10-27 (ET slate)

| Game | Line | Actual | Old total | New total | Old inj total | New inj total | Old gap | New gap | v1 play (new) | Result |
|------|------|--------|-----------|-----------|---------------|---------------|---------|---------|---------------|--------|
| BKN @ BOS | 222.5 | 249 | 224.9 | 228.8 | 224.8 | 224.8 | +2.3 | +2.3 | — | — |
| DET @ NYK | 220.5 | 208 | 221.2 | 200.9 | 214.7 | 220.4 | -5.8 | -0.1 | — | — |
| SAC @ SAS | 232.5 | 233 | 233.3 | 226.9 | 230.5 | 232.1 | -2.0 | -0.4 | — | — |
| POR @ LAL | 233.5 | 265 | 233.4 | 234.6 | 237.6 | 234.6 | +4.1 | +1.1 | — | — |

## 2026-10-28 (ET slate)

| Game | Line | Actual | Old total | New total | Old inj total | New inj total | Old gap | New gap | v1 play (new) | Result |
|------|------|--------|-----------|-----------|---------------|---------------|---------|---------|---------------|--------|
| MIA @ ATL | 239.5 | 246 | 232.3 | 231.2 | 232.3 | 231.2 | -7.2 | -8.3 | MIA @ ATL: Under 239.5 | L |
| WAS @ CLE | 239.25 | 232 | 236.6 | 242.4 | 236.6 | 242.4 | -2.6 | +3.2 | WAS @ CLE: Over 239.25 | L |
| CHA @ DET | 216 | 186 | 221.2 | 211.9 | 222.0 | 221.1 | +6.0 | +5.1 | CHA @ DET: Over 216 | L |
| PHI @ IND | 237.5 | 223 | 227.2 | 215.5 | 225.3 | 225.3 | -12.2 | -12.2 | PHI @ IND: Under 237.5 | W |
| ORL @ TOR | 224.5 | 228 | 222.2 | 208.7 | 218.9 | 218.9 | -5.6 | -5.6 | ORL @ TOR: Under 224.5 | L |
| NYK @ CHI | 232.5 | 260 | 227.7 | 217.1 | 228.6 | 217.1 | -3.9 | -15.4 | NYK @ CHI: Under 232.5 | L |
| HOU @ MIL | 226.5 | 232 | 227.5 | 234.6 | 226.2 | 226.2 | -0.3 | -0.3 | — | — |
| GSW @ MIN | 227.5 | 233 | 233.9 | 244.4 | 233.6 | 233.6 | +6.1 | +6.1 | GSW @ MIN: Over 227.5 | W |
| DEN @ NOP | 240.5 | 195 | 246.0 | 253.9 | 246.3 | 246.3 | +5.8 | +5.8 | DEN @ NOP: Over 240.5 | L |
| SAS @ UTA | 233.5 | 228 | 236.3 | 235.6 | 234.0 | 234.4 | +0.5 | +0.9 | — | — |
| OKC @ DAL | 228.5 | 216 | 226.1 | 214.1 | 223.9 | 223.9 | -4.6 | -4.6 | OKC @ DAL: Under 228.5 | W |
| LAL @ LAC | 224.5 | 190 | 234.4 | 241.2 | 229.7 | 231.9 | +5.2 | +7.4 | LAL @ LAC: Over 224.5 | L |

## Oct 27–28 headline totals (official card games)

Honest read on whether the **new** method would still publish the Oct 28 official totals:

| Game | Official play | New inj gap vs line | Still ≥ 3 pt? |
|------|---------------|---------------------|-----------------|
| GSW @ MIN | Over 227.5 | **+6.1** | Yes — still plays; **W** |
| DEN @ NOP | Over 240.5 | **+5.8** | Yes — still plays; **L** (actual 195) |
| NYK @ CHI | Under 232.5* | **−15.4** | Yes — stronger under; **L** (actual 260) |
| LAL @ LAC | Over 224.5 | **+7.4** | Yes — still plays; **L** (actual 190) |

\*Tip snapshot line 232.5 in paper store; official card graded at 233.5.

**Takeaway:** Removing prior-season blend **lowers** many totals (Oct 25–26 unders get smaller gaps), but on Oct 28 **DEN** and **LAL** overs stay firmly on the card — new raw totals (**253.9**, **241.2**) are even **higher** than legacy (**246.0**, **234.4**) because early 2026-27 game logs for those matchups still imply high pace/efficiency. Fixing the Oct 28 over misses needs more than dropping last year (e.g. shrink toward market, higher total threshold) — not implemented here.

Spread rows in the tables above are unchanged (margin path still prior-blended).

_Generated by `scripts/build_nba_totals_backtest_doc.py`._

