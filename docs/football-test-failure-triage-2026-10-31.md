# Football pytest failure triage (2026-10-31)

Five football-related tests were failing on `main` while `test_nba_official_pace` was left alone.

**Outcome:** All five were **stale tests or fixtures**, not regressions in pick/filter/model behavior. Fixes land in PR **A** (`cursor/fix-football-tests-a-cacb`). **No product behavior PR** is required; this document is the draft **B** record.

## Per-test classification

| Test | Classification | Reason |
|------|----------------|--------|
| `test_ncaaf_team_match::test_action_network_prefers_mascot_free_location` | Stale test | `_team_name` is an instance method; NCAAF key order requires `ActionNetworkClient(league="ncaaf")`. |
| `test_ncaaf_team_match::test_state_schools_never_masquerade_as_parent_program` | Stale expectations | `ncaaf_display_code` prefers registered aliases (`INST`, `MOST`, `TNST`); masquerade checks vs parent flagships remain valid. |
| `test_paper_momentum::test_paper_momentum_logs_first_move` | Stale fixture | First snapshot used default `now` (after second snapshot), inverting open vs scan lines. |
| `test_qa_gate::test_spread_model_conflict_quarantined` | Stale fixture | Hard-coded Oct 2025 kickoff triggers `stale_kickoff` **void** before line-gap quarantine is asserted. |
| `test_steam::test_steam_detected_across_multiple_books` | Stale fixture | `betonline` is not in `settings.sharp_books`; steam correctly counted 2 books, not 3. |

## Draft PR B — behavior changes

**None proposed.** Quarantine rules, steam thresholds, and paper momentum side selection were already correct; tests did not reflect current API/config.

If we later add `betonline` to `sharp_books` or change QA kickoff windows, add targeted tests in a **behavior** PR with explicit play-impact notes.
