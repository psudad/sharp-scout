# Sharp Scout — Backlog

Queued work items. Not yet built.

## Open

### Guard against unrated-team / oversized-edge plays (NCAAF)
**Priority:** medium · **Queued:** 2026-09-05

Even with real power ratings, two failure modes still produce plays that "look off":

1. **Unrated FCS underdogs.** FCS teams aren't in the FBS play-by-play, so they get a
   default/zero rating. In FCS-vs-FBS games the model overrates the dog and invents
   value — e.g. *Idaho State @ Utah State* away ML showed +45% "edge" at only a 29%
   win probability.
2. **Oversized edges between two rated teams.** Real but implausibly large spread edges
   (~40%+), e.g. *Central Michigan @ New Mexico* CMU +10.5 at +41% edge.

**Proposed fix (pipeline / filters):**
- Detect when a team is unrated (missing from `build_power_ratings`, i.e. power == 0 with
  no PBP rows) and **suppress or de-tier ML/spread plays on that side** (especially FCS
  underdogs). Consider tagging the game as "unrated matchup — model unreliable."
- **Cap absurd edges:** flag/downgrade any play whose `edge` exceeds a sane ceiling
  (e.g. > ~25–30% ATS) so it can't post as a top play without review.
- Add regression tests: an FCS-dog ML must not validate as a `play`; an over-cap edge
  must be de-tiered.

**Notes:** `--skip-pbp` was removed from the gameday rebuild (2026-09-05) so ratings are
now real; this guard addresses the residual unrated/outlier cases. Small, testable change.

### QA gate: block demo/stale data + verify (don't blindly kill) high-EV plays
**Priority:** high · **Queued:** 2026-09-05

Tonight two failures stacked silently: the Odds API returned 401 → silent fallback to
demo events, and `--skip-pbp` → demo ratings. Nothing flagged that the live board was
showing fake data. Add QA layers, deterministic first.

**Layer 1 — Data-provenance gate (CI, deterministic; highest value).**
- **Block the Pages deploy** if `demo == True`, if odds/AN fell back to mock, or if
  `n_games` is below a gameday floor.
- Assert ratings are real: team count > threshold AND power spread (stdev) > 0 — catches
  the flat/demo table.
- On failure, **alert** (email via Gmail integration or open a GitHub issue) instead of
  silently deploying stale data.

**Layer 2 — Play sanity checks (deterministic). High EV is QUARANTINED, not deleted.**
- Do **not** hard-cap EV — high EV can be legitimate (soft small-market line, early FCS/FBS
  totals). Gate on *why* the edge exists, via a **corroboration test**:
  - Trusted (post, maybe tag "High EV — verify") when built on a real market line:
    multiple books present, a consensus/mid exists, AND both teams are rated.
  - **Held for review** (quarantine list + alert) when the edge comes from an unrated
    team, a single book, or no consensus — i.e. the model is guessing.
  - Example: Ark State +51% (flat ratings, no corroboration) → quarantined; a genuine
    +18% on a fully-rated, multi-book game → posts.
- Also flag suspicious duplicate-`p_true` clusters (a tell that sims ran on degenerate
  inputs). Nothing is silently dropped — quarantined plays surface for a quick eyeball.

**Layer 3 — LLM QA review (the "agent"). Optional, second.**
- Cloud agent reads the freshly built slate and reports anything implausible in plain
  English. Sits *behind* Layers 1–2 (free, fast, can't hallucinate) as a backstop only.

**Suggested build:** `scripts/qa_gate.py` wired into the gameday workflow before deploy;
regression tests for each rule (demo-fallback fails the gate; unrated/no-consensus high-EV
is quarantined; a corroborated high-EV play passes).

### End-of-week evaluator agent (planning — user request 2026-09-06)
**Priority:** medium · **Planning only — no build until confirmed**

Weekly retrospective that grades **every lens**, not just tracked ledger plays, and explains
*why* high-EV model leans did or didn't become recommendations.

**Systems to score independently (from `stage_picks.py`):**
| UI label | Stage key | What it is |
|----------|-----------|------------|
| **Quant Pick** | `model` | Monte Carlo + power ratings — same as "the model" |
| **Sharp Book** | `sharp` | Pinnacle/Circa no-vig favorite (a **price**, not money flow) |
| **Public** | `public` | Ticket-% majority |
| **Handle** | `money` | Handle-% majority (where dollars are flowing) |
| **Sharp Money** | `sharp_edge` | Handle % minus ticket % gap |
| **RLM** | `rlm` | Reverse line movement |
| **Hybrid** | `hybrid` | Validated Phase-4 play if one exists; else model lean with allies |

**Key distinction (user FAQ):**
- **Quant = Model** — yes, same thing. "Quant Pick" is the model stage column.
- **Handle ≠ Quant** — Handle follows *betting dollars*; Quant follows *simulated fair value*.
- **Phase 3 EV / Double Diamond ≠ a play** — Games table shows raw model edges from
  `discover_edges`. A tracked play requires Phase 4 `validate_edge`: EV ≥ 2% **plus**
  at least one of RLM, money-ticket gap ≥ 20%, or steam.

**Example cases to explain in the report:**
- *Wisconsin +21 @ Notre Dame* — model 97% cover, ~94% EV, Double Diamond in Games table,
  but **rejected** because money-ticket gap was only −4% (need ≥20%) and no RLM/steam.
  Hybrid = "model lean only — no confirming market stage."
- *WSU +24 @ Washington* — model loves the dog on spread (97% cover) but no validated spread
  play; **Over 51.5** *did* validate (3% EV + market confirmation) and is on the ledger.

**Deliverable shape:**
1. `scripts/week_review.py` (or cloud-agent prompt) — input: week's ledger + stage_cards + scores.
2. Output: per-system W-L-P, units, ROI; table of "model said X, market said Y, result Z";
   list of **near-misses** (high EV + high Win % but filter rejected) with rejection reason;
   recommendations (e.g. lower money-ticket gap for large dogs? separate Week-1 rules?).
3. Optional LLM narrative summary for the web agent to discuss — sits on top of deterministic grades.

**Open tuning questions for the evaluator to inform (not change yet):**
- Should mega-dog spreads (e.g. +21) with huge model EV but no handle confirmation ever post?
- Is the 20% money-ticket gap too strict early season when splits are thin?
- Should Double Diamond in Games auto-flag for human review even when Phase 4 rejects?
