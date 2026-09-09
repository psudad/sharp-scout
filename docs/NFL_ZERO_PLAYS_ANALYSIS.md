# Why NFL Has Zero Approved Plays - Analysis

**Date**: September 8, 2026  
**Status**: 3 validated signals, 0 approved, 2 quarantined, 1 missing

---

## Summary

The NFL pipeline generated **3 validated plays** that passed Phase 4 filters:

1. **KC @ DEN** - h2h home @ draftkings -125 (34.2% EV) ❌ **MISSING FROM LEDGER**
2. **WAS @ PHI** - spreads home -4.5 @ lowvig -108 (15.5% EV) 🟡 **QUARANTINED**
3. **ATL @ PIT** - h2h away @ betfair_ex_eu +166 (10.6% EV) 🟡 **QUARANTINED**

---

## Play-by-Play Analysis

### 1. KC @ DEN h2h home (34.2% EV) - MISSING ❌

**What happened**: This play passed Phase 4 filters but **never made it to the ledger**.

**Why**: Two possibilities:
1. The **h2h outlier check** might be blocking it from being added to the ledger
2. The EV is so high (34.2%) it might exceed the `max_h2h_edge = 50%` threshold, though 34.2% < 50%

**Filter details**:
- ✅ EV: 34.2% (above 2% threshold)
- ✅ Money-ticket gap: YES (sharp money confirmation)
- ❌ RLM: NO
- ❌ Steam: NO
- ✅ Filter passed: TRUE

**The problem**: Even though it passed filters, moneyline plays have special scrutiny. The price is -125, which is reasonable, but the 34.2% EV is suspiciously high. This might trigger:
- A stale price check
- The model being too aggressive on this pick'em-ish game

**Action needed**: Check if there's additional h2h filtering happening between Phase 4 and ledger append.

---

### 2. WAS @ PHI spreads home -4.5 (15.5% EV) - QUARANTINED 🟡

**QA Gate reasons**:
```
[quarantine] p_true=0.5998 appears in a suspicious cluster — degenerate sim inputs?
```

**What it means**: The win probability 59.98% appears multiple times across different plays, suggesting:
- The Monte Carlo simulation is producing duplicate results
- Possible rounding or input data issue
- Not enough variation in simulation inputs

**Filter details**:
- ✅ EV: 15.5% (above 2% threshold)
- ✅ Money-ticket gap: YES
- ❌ RLM: NO
- ❌ Steam: NO
- ✅ Filter passed: TRUE

**Fix**: Investigate why simulations are producing duplicate p_true values. This is a legitimate QA concern.

---

### 3. ATL @ PIT h2h away (10.6% EV) - QUARANTINED 🟡

**QA Gate reasons**:
```
[quarantine] p_true=0.4157 appears in a suspicious cluster — degenerate sim inputs?
[quarantine] Model favors PIT to win (55.8%) but play is ATL ML (p_true=41.6%)
[quarantine] Spread sharp money on PIT (+25% gap) conflicts with ML play on ATL
```

**What it means**: 
1. **Duplicate p_true issue** (same as WAS @ PHI)
2. **Model conflict**: Model thinks PIT wins 55.8%, so why are we betting ATL moneyline at only 41.6% win probability?
3. **Cross-market conflict**: Sharp money is on PIT spread, but we're playing ATL moneyline

**The real problem**: This is a **model vs sharp market disagreement**:
- Our model: PIT 55.8% to win
- ATL ML p_true: 41.6% (this doesn't make sense - if PIT is 55.8% to win, ATL should be 44.2%)
- The play is betting AGAINST our own model

**This is working as intended** - the QA gate correctly caught an internal contradiction.

---

## Root Causes

### 1. Duplicate P_True Clusters (WAS @ PHI, ATL @ PIT)

**Problem**: Monte Carlo simulations are producing identical win probabilities too often.

**Check this**:
```python
# In latest_signals.json, count how many signals have p_true = 0.5998
# and how many have p_true = 0.4157
```

**Threshold**: ≥5 identical values triggers quarantine  
**Config**: `DUPLICATE_P_TRUE_MIN_CLUSTER = 5`

**Likely cause**:
- Rounding p_true to 4 decimals creates clusters
- Not enough variation in simulation parameters
- Possible bug in Monte Carlo sampling

---

### 2. H2H Plays Are Heavily Filtered

Moneyline plays face additional scrutiny:

#### H2H Outlier Checks (from filters.py):
1. **Max EV**: edge < 50%
2. **Max Plus Price**: price < +1200
3. **Tight Spread Check**: If model spread is pick'em-ish but ML is extreme

#### QA Gate H2H Checks (from qa/gate.py):
1. **Model conflict**: Model favors opposite side
2. **Cross-market conflict**: Spread sharp money disagrees
3. **Weak confirmation**: ML handle gap < 12%

**The KC @ DEN play** likely failed one of these post-filter checks.

---

## Why CFB Has 3 Approved Plays

CFB totals (TULSA, TTU, TOWSON) avoided these issues:

✅ **No h2h scrutiny** (they're totals, not moneylines)  
✅ **No duplicate p_true** (different games, different probabilities)  
✅ **No model conflicts** (totals don't have spread/ML disagreements)  
✅ **Sharp money confirmation** (all passed money-ticket gap)

---

## Recommendations

### Short Term

1. **Increase tolerance for p_true clusters**
   - Change `DUPLICATE_P_TRUE_MIN_CLUSTER` from 5 to 10
   - Or exclude close games (50-55% range) from the check

2. **Review h2h ledger append logic**
   - The KC @ DEN play passed filters but didn't make the ledger
   - Check if there's an additional filter between Phase 4 and ledger.append()

3. **Relax cross-market conflict rule for close games**
   - If the spread and ML are both coin flips, allow disagreement

### Long Term

1. **Fix duplicate p_true issue**
   - Add more randomness to Monte Carlo simulations
   - Use more decimal places before rounding
   - Investigate why identical probabilities are common

2. **Add diagnostic logging**
   - Log why plays that pass filters don't make it to ledger
   - Track h2h rejection reasons separately

3. **Review model calibration**
   - The ATL @ PIT play shows model thinks PIT wins 55.8% but p_true=41.6%
   - This internal inconsistency suggests calibration drift

---

## Testing Commands

```bash
# Check duplicate p_true values
cat docs/latest_signals.json | python3 -c "
from collections import Counter
import sys, json
data = json.load(sys.stdin)
signals = data.get('signals', [])
p_trues = [round(s['p_true'], 4) for s in signals if 'p_true' in s]
counts = Counter(p_trues)
print('P_true values appearing 5+ times:')
for val, count in counts.items():
    if count >= 5:
        print(f'  {val:.4f}: {count} times')
"

# Check h2h plays specifically
cat docs/latest_signals.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
plays = [p for p in data.get('plays', []) if p['market'] == 'h2h']
print(f'Total h2h validated plays: {len(plays)}')
for p in plays:
    print(f\"{p['away_team']} @ {p['home_team']}: {p['side']} - EV={p['edge']*100:.1f}%\")
"

# Check ledger append timing
ls -lt data/ledger.json docs/latest_signals.json artifacts/latest_signals.json
```
