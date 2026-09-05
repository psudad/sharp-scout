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
