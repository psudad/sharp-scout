# NBA Action Network sharp splits (manual snapshots)

GitHub Actions cannot log into Action Network Pro. Pull **public betting** splits in a browser session and commit JSON here.

## Filename

`YYYY-MM-DD-HHMM.json` (Eastern time when the pull finished), e.g. `2026-10-26-0820.json`.

## Schema (version 1)

```json
{
  "version": 1,
  "source": "action_network_pro",
  "pulled_at": "2026-10-26T08:20:00-04:00",
  "game_date": "2026-10-26",
  "games": [
    {
      "away": "Timberwolves",
      "home": "Cavaliers",
      "tip_et": "19:00",
      "spread": { "bets": [74, 26], "money": [76, 24] },
      "total": { "bets": [85, 15], "money": [88, 12] },
      "ml": { "bets": [60, 40], "money": [79, 21] }
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `pulled_at` | ISO-8601 timestamp of the pull (used to pick the latest snapshot **before tip**). |
| `game_date` | Slate date in US/Eastern (`YYYY-MM-DD`) for matching Odds API events. |
| `away` / `home` | Team nickname or 3-letter code (see `nicknames.py`). |
| `tip_et` | Optional `HH:MM` Eastern tip for disambiguation. |
| `spread` / `total` / `ml` | Percent of handle on each side: `[away, home]` or `[over, under]`. Integers 0–100. |

Optional `note` and per-market `line` strings from the UI are ignored by the tagger.

## Tag rule (display-only)

For each paper play’s market and side:

- **with sharps** — that side’s `money − bets ≥ 10` (percentage points)
- **against sharps** — the opposite side’s `money − bets ≥ 10`
- **no signal** — neither side clears the gap
- **no data** — no snapshot covers the game, or the play is a prop

Threshold is `SHARP_MONEY_GAP_PT` in `sharp_scout.nba.sharp_splits.filter`.
