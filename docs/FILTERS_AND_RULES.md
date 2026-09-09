# Sharp Scout Filters & Rules - Complete Reference

## Overview
Sharp Scout uses a **4-phase pipeline** followed by a **QA Gate**. Every play must pass ALL filters to be approved.

---

## PHASE 4: MARKET VALIDATION FILTERS (filters.py)

These filters validate that a model edge is supported by actual market behavior. A play must have:

### ✅ Required: EV Threshold
- **Rule**: `edge >= 2.0%` (configurable: `ev_threshold`)
- **What it means**: The expected value must be at least 2%
- **Why it blocks**: Low EV plays aren't worth the risk

### ✅ Required: At Least ONE Confirmation Signal

A play MUST have at least one of these three confirmations:

#### 1. Money-Ticket Gap (Sharp Money)
- **Rule**: Handle % exceeds ticket % by **≥12%** on our side
- **Config**: `money_ticket_gap = 0.12` (12%)
- **What it checks**: `money_pct - ticket_pct >= 12%`
- **Example**: 
  - Public tickets: 40% on our side
  - Money: 55% on our side  
  - Gap: +15% ✅ PASS (sharps agree with us)
- **Why it blocks**: No sharp money confirmation

#### 2. Reverse Line Movement (RLM)
- **Spreads**: Line moves AGAINST the public toward our side
  - Public 64% on away, but line moved toward home → RLM supports home play
  - Must move ≥0.25 points to count
- **Totals**: Total moves AGAINST the public
  - Public on over, but total moved down → RLM supports under
  - Must move ≥0.25 to count
- **Why it blocks**: No RLM confirmation = line moved WITH public or stayed flat

#### 3. Steam (Line Velocity)
- **Rule**: ≥2 sharp books moved the line ≥0.5 points in the same direction within 90 minutes
- **Config**: 
  - `steam_min_books = 2`
  - `steam_min_points = 0.5`
  - `steam_window_minutes = 90`
- **Why it blocks**: No coordinated sharp book movement detected

### ✅ Required: H2H (Moneyline) Sanity Checks

For moneyline plays ONLY:

1. **Max EV Cap**: `edge < 50%` 
   - Blocks stale/offshore misquotes
   
2. **Max Plus Price**: `price < +1200`
   - Blocks extreme longshots

3. **Tight Spread + Big Dog Check**:
   - If model spread is close to pick'em (< 10 points) but ML is extreme dog (>+600)
   - Blocks likely bad book pricing errors

### 🟡 Tier Assignment (for approved plays)

After passing all filters, plays get tiered:

- **PLAY tier**: 
  - 2+ confirmations AND edge ≥3%, OR
  - 1 confirmation AND edge ≥2.5%
  
- **LEAN tier**: 
  - 1 confirmation AND edge <2.5%

---

## QA GATE: TWO-LAYER SAFETY NET (qa/gate.py)

### LAYER 1: DATA PROVENANCE (blocks deployment)

These checks run on the **entire pipeline output**:

1. **Demo Mode Check**
   - Blocks if `demo=True` (using mock data)

2. **Minimum Games**
   - NFL: ≥4 games required
   - NCAAF: ≥20 games required
   - **Current NFL**: 272 games ✅ 
   - **Current CFB**: 84 games ✅

3. **Minimum Rated Teams**
   - NFL: ≥28 teams with power ratings
   - NCAAF: ≥80 teams with power ratings
   - Blocks if skip-pbp or demo ratings used

4. **Rating Spread Check**
   - Power rating standard deviation ≥0.01
   - Blocks if all teams have same/similar ratings (degenerate data)

### LAYER 2: PLAY-BY-PLAY SANITY (quarantines plays)

These checks run on each **individual pending play**:

#### ⚠️ VOID (removes from ledger)

1. **Missing Kickoff**: Play has no parseable kickoff time

2. **Stale Kickoff**: Kickoff is outside the current display week
   - NFL: Only current gameweek (Thu-Mon)
   - CFB: Only current college week (Tue-Mon ET)

3. **Orphan Event**: Game not found in latest pipeline output

4. **Not Revalidated**: Play no longer passes Phase 4 filters in latest run
   - **This is likely blocking NFL plays right now**

#### 🟡 QUARANTINE (held for review)

1. **Unrated Team**
   - Team missing from power ratings database
   - **Currently blocking FSU plays** (SMU missing)

2. **Single Book** 
   - Only 1 book offers this line
   - Need ≥2 books for corroboration
   - Config: `MIN_BOOKS_FOR_CORROBORATION = 2`

3. **Duplicate P_True Cluster**
   - Same win probability appears ≥5 times (suspicious)
   - Suggests degenerate simulation inputs
   - Config: `DUPLICATE_P_TRUE_MIN_CLUSTER = 5`

4. **Spread Model Conflict** (NEW - your fix!)
   - **Probability Gap**: `|p_true - p_mkt| ≥ 15%`
     - Config: `spread_model_prob_gap = 0.15`
     - Model says 76% to cover, sharp market says 48% → 28% gap → QUARANTINE
   
   - **Line Gap**: `|model_spread - market_line| ≥ 4.0 points`
     - Config: `spread_model_line_gap = 4.0`
     - Model spread -4.5, market line +2.5 → 7-point gap → QUARANTINE

5. **ML Model Conflict**
   - Model favors home to win but play is away ML (or vice versa)
   - Only when model and play sides clearly contradict

6. **Cross-Market Conflict**
   - For ML plays: spread sharp money is on the OPPOSITE side
   - Suggests internal inconsistency

7. **Weak ML Confirmation**
   - For ML plays: handle gap < 12%
   - Moneyline plays need strong sharp money confirmation

8. **Offshore Outlier**
   - Offshore book price diverges >15 cents from Pinnacle close
   - Suggests stale/bad pricing

---

## WHY YOU HAVE ZERO NFL PLAYS

Based on the filters, here's what's likely happening:

### NFL (0 approved, 0 quarantined):

The NFL pipeline generated **3 validated signals** but none made it to the ledger as pending plays. This means:

1. **Phase 4 filters rejected them initially**, OR
2. **QA Gate voided them** because:
   - They're outside the display week window, OR
   - They didn't revalidate when the pipeline ran again

### CFB (3 approved, 45 quarantined):

**Approved plays** (passing everything):
- TULSA @ SAM HOUSTON: under 51.0 (3.2% EV)
- TTU @ ORST: over 54.5 (2.7% EV)
- TOWSON @ SCAR: over 55.5 (2.2% EV)

**Quarantined plays** (45 total) failed due to:
- **Unrated teams** (SMU, others missing from ratings)
- **Spread model conflicts** (model disagrees with market by >15% or >4 points)
- **Duplicate p_true clusters** (suspicious simulation data)
- **Single book only** (no corroboration)

---

## CONFIG VALUES (Current Settings)

### Phase 4 Thresholds
```
ev_threshold: 0.02                    # 2% minimum EV
money_ticket_gap: 0.12                # 12% sharp money confirmation
```

### H2H Guardrails
```
max_h2h_edge: 0.50                    # 50% max EV (blocks stale prices)
max_h2h_plus_price: 1200.0            # +1200 max dog price
h2h_dog_price_tight_spread_floor: 600 # +600 threshold
h2h_tight_spread_threshold: 10.0      # 10-point model spread
```

### QA Gate Thresholds
```
spread_model_prob_gap: 0.15           # 15% probability disagreement
spread_model_line_gap: 4.0            # 4-point line disagreement
MIN_BOOKS_FOR_CORROBORATION: 2        # Need 2+ books
DUPLICATE_P_TRUE_MIN_CLUSTER: 5       # 5+ identical probabilities
```

### Steam Detection
```
steam_window_minutes: 90              # 90-minute window
steam_min_points: 0.5                 # 0.5-point minimum move
steam_min_books: 2                    # 2+ sharp books
steam_score_threshold: 1.0            # Score ≥1.0 to flag
```

---

## TO INVESTIGATE NFL

Check the latest NFL signals to see why plays aren't being posted:

```bash
cd /Users/jasoneger/Documents/Cursor/betting/sharp-scout
cat docs/latest_signals.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
plays = data.get('plays', [])
print(f'Validated signals: {len(plays)}')
for p in plays[:5]:
    flags = p.get('flags', {})
    print(f\"{p['away_team']} @ {p['home_team']} {p['market']} - \")
    print(f\"  EV: {p['edge']*100:.1f}% | Flags: {flags}\")
"
```

Most likely culprits:
1. **No RLM or sharp money confirmation** (most common)
2. **EV below 2% threshold**
3. **Single book only (no corroboration)**
4. **Plays were outside display week when QA gate ran**
