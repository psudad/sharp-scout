from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
ARTIFACTS_DIR = ROOT / "artifacts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    odds_api_key: str = ""
    action_network_cookie: str = ""
    # Preferred auth: a Bearer JWT from a logged-in Action Network session
    # (authorization header). Long-lived (~1yr). Takes precedence over the cookie.
    action_network_token: str = ""

    ev_threshold: float = 0.02
    money_ticket_gap: float = 0.12
    # Moneyline guardrails — block stale/offshore misquotes from auto-plays
    max_h2h_edge: float = 0.50
    max_h2h_plus_price: float = 1200.0
    h2h_dog_price_tight_spread_floor: float = 600.0
    h2h_tight_spread_threshold: float = 10.0
    monte_carlo_sims: int = 10_000

    # Sharp books preferred for P_mkt; Circa when present in aggregator response
    sharp_bookmakers: str = "pinnacle,circa,circa_sports,betfair_ex_eu"
    # Retail books to shop for execution price
    retail_bookmakers: str = "draftkings,fanduel,betmgm,williamhill_us,fanatics"

    database_url: str = f"sqlite:///{DATA_DIR / 'sharp_scout.db'}"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Google Analytics 4 measurement ID (e.g. G-XXXXXXXXXX) for GitHub Pages visitor tracking
    ga_measurement_id: str = ""

    # Ratings lookback seasons (inclusive current when available)
    ratings_seasons: str = "2023,2024,2025,2026"
    # Recency half-life in weeks for EPA weighting
    epa_half_life_weeks: float = 6.0

    # Player props
    # player_rush_attempts dropped: 1-7 live in Week 3 and its overs are the most
    # over-confident market in the backfit (p 0.7 -> 0.60 realized).
    prop_markets: str = (
        "player_pass_yds,player_pass_tds,player_rush_yds,"
        "player_receptions,player_reception_yds,player_reception_tds,player_anytime_td"
    )
    prop_ev_threshold: float = 0.02
    # p_true = p_mkt + k·(p_cal − p_mkt) against the two-way no-vig prop price, same idea
    # as the sides' anchor_k. Unanchored, the biggest model-vs-market gaps were the worst
    # bets (10-20% "edge" bucket went 26-41 in Week 3).
    prop_anchor_k: float = 0.3
    # Fair price props are anchored/judged against: "consensus" = median no-vig over prob
    # across books quoting the same player/line (needs prop_consensus_min_books), falling
    # back to the book's own two-way; "book" = legacy own-book no-vig (structurally ~0
    # props can clear the EV floor at −110/−110 with k=0.3 and a 10% gap cap).
    prop_fair_source: str = "consensus"
    prop_consensus_min_books: int = 3
    # Per-season weight decay for prop usage baselines (0.5 → last season counts double
    # the one before it), so a stale rookie year cannot anchor a current projection.
    prop_season_decay: float = 0.5
    # Blend weight on current-season-only per-game rates (rest = multi-season recency blend).
    prop_current_season_blend: float = 0.65
    # Minimum games in the current season before the blend kicks in.
    prop_current_season_min_games: int = 2
    # Wider tails on yardage/count sims — the backfit showed the raw MC was over-narrow.
    prop_rec_yards_cv: float = 0.68
    prop_rush_yards_cv: float = 0.66
    prop_pass_yards_cv: float = 0.48
    prop_count_dispersion: float = 1.45
    # Props guardrails — a prop edge this large means the projection, not the market, is
    # broken; publish nothing above it (mirrors max_h2h_edge on the sides pipeline).
    max_prop_edge: float = 0.35
    # Simulated certainty above this is degenerate, not a real edge.
    max_prop_p_true: float = 0.97
    # |p_true - p_mkt| beyond this means the projection disagrees with the whole market,
    # which on an uncalibrated prop model is model error rather than edge.
    prop_model_market_gap: float = 0.10
    # Only pull player props for games kicking off inside this horizon (API credits).
    prop_horizon_days: float = 8.0
    # Props publish to the ledger and public board (consensus no-vig pricing, #70).
    # Set PROPS_PUBLISH_ENABLED=false to return to shadow mode.
    props_publish_enabled: bool = True
    # Pregame run windows (hours before kickoff)
    pregame_windows_hours: str = "12,4,3,2,1"
    pregame_window_tolerance_minutes: int = 25
    # Fire a missed window late (once) instead of skipping it. See find_due_windows.
    pregame_catchup: bool = True

    # Optional comma-separated inactive player names for reallocation
    inactive_players: str = ""

    # Model-vs-market disagreement logging ("why is our model wrong?")
    disagreement_prob_threshold: float = 0.05  # |p_true - p_mkt| to flag a disagreement
    # QA gate — quarantine spreads when model and sharp market disagree implausibly
    spread_model_prob_gap: float = 0.15  # |p_true - p_mkt| quarantine threshold
    spread_model_line_gap: float = 4.0  # |model_spread - home market line| in points
    # NCAAF model hygiene (backtested on 2026 Weeks 1–3, see docs/ncaaf-model-review)
    ncaaf_prior_seasons: int = 1  # prior seasons of PBP blended into CFB power ratings
    # CFB ratings fit (as-of backtest 2025 Wk4–13 → 2026 Wk2–4, FBS-vs-FBS margins)
    ncaaf_epa_half_life_weeks: float = 10.0
    ncaaf_epa_ridge_alpha: float = 20.0
    # NFL sides ratings (as-of backtest 2024–25 Wk4–17: margin corr 0.27 → 0.37)
    nfl_epa_half_life_weeks: float = 16.0
    ncaaf_ban_ml_dogs: bool = True  # NCAAF moneyline underdogs went 4–12 / 8–12 in every rating variant
    ncaaf_sharp_veto: bool = True  # reject plays where the sharp book's no-vig side is against us
    nfl_sharp_veto: bool = True  # same rule for NFL (model has no edge vs the close; 48.7% over 546 games)

    # Product gate — only certified plays reach the ledger / LOCKED card (see qa/product_gate.py).
    product_gate_enabled: bool = True
    product_ev_min: float = 0.04  # 4% anchored EV floor (live card was ~50% at 2%)
    product_p_fair_min: float = 0.50  # sharp no-vig must favor our side at the bet line
    product_markets: str = "spreads,totals,h2h"  # h2h stays watchlist-only via product_shadow_markets
    # EV band: tilt-driven EVs above the ceiling went 77-75 (50.7%) on 2026 graded
    # candidates; 4-12% (no ML) went 31-13. None disables the ceiling. Re-tune both
    # bounds whenever anchor_k / anchor_tilt_cap change (EV scale moves with k).
    product_ev_max: float | None = 0.12
    # Whitelist "sport:market" pairs (comma-separated) that bypass the EV ceiling,
    # use their own EV floor, and rank ahead of other plays for the per-sport cap.
    # NCAAF totals went 45-19 (70.3%) on graded candidates thru Wk6 2026.
    product_whitelist: str = "ncaaf:totals"
    product_whitelist_enabled: bool = True
    product_whitelist_ev_min: float = 0.02
    product_min_books: int = 2  # multi-book corroboration on the same side/line
    # ML (h2h) on the certified card — stricter than spreads/totals (option B).
    product_ml_require_split_board: bool = True
    product_ml_require_spread_sharp_align: bool = True  # spread $ vs tickets same side as ML
    product_ml_require_ml_ticket_gap: bool = True  # ML market handle gap on our side
    product_ml_ticket_gap: float | None = None  # default: money_ticket_gap
    product_play_tier_only: bool = True  # leans stay research-only in artifacts
    product_max_plays_nfl: int = 5
    product_max_plays_ncaaf: int = 5
    # Totals on the certified card — don't LOCK a total that fights the sharp-money read.
    # (Week 4 2026: SEA U43 and NO U48 both locked on model + RLM while the dollars were
    # on the OVER, and both lost. These rules require money agreement, not RLM alone.)
    product_total_sharp_guardrail: bool = True
    product_total_money_gap: float = 0.10  # money-ticket gap on OUR side that counts as confirmation
    product_total_opposing_gap: float = 0.05  # sharp money this far on the OTHER side vetoes the total
    product_total_model_market_max_gap: float = 5.0  # |model_total - market line| allowed w/o confirmation
    # Spreads on the certified card — Phase 4 can pass on RLM alone; product gate needs handle
    # on our side (Southern Miss +10 locked at T-4h with only +8% spread sharp money).
    product_spread_sharp_guardrail: bool = True
    product_spread_money_gap: float = 0.12  # money-ticket gap on OUR spread side (default = filter bar)
    # Do not post a first-time LOCKED play inside this window before kickoff (hours).
    # Was 8h (#59). Graded 2026 confirmed candidates (Sep 22-Oct 12): last pre-kick state
    # <8h before kickoff went 27-19 (58.7%) vs 4-9 at >=8h — splits/RLM mature late, so
    # the 8h rule removed the better plays and blocked every Sunday-morning NFL run.
    # 2h still posts before the NFL T-1h card freeze.
    product_min_certify_lead_hours: float = 2.0
    # Price vs sharp: p_fair (Pinnacle no-vig at our line) minus our price's implied prob.
    # A play priced well below sharp fair starts with negative CLV; the vig alone is ~-2.4%
    # at -110, so -1% only blocks prices materially worse than the sharp market.
    product_min_price_vs_fair: float = -0.01
    # Markets tracked as watchlist (shadow-graded) but never posted to the LOCKED card.
    # Moneyline went 8-13 (-4.4u) certified through Week 4 2026; 17-31 across all graded
    # candidates through Week 6. Keep h2h here (= no-ML gate on the LOCKED card).
    product_shadow_markets: str = "h2h"
    # Narrow LOCKED lanes: Phase-4 confirmed + Pinnacle no-vig on our side (≥50%).
    # Priority order is the comma list (first = highest). Replaces spread/total
    # product guardrails and multi-book corroboration for lane plays only.
    product_narrow_lanes_enabled: bool = True
    product_narrow_lanes: str = "ncaaf:totals,ncaaf:spreads,nfl:spreads"
    # Per narrow-lane EV floors as sport:market:min (comma-separated). Unlisted lanes use product_ev_min.
    product_narrow_lane_ev_mins: str = "nfl:spreads:0.03"

    # QA promote — post these on the LOCKED card (same rule NFL + NCAAF).
    qa_promote_single_book_totals: bool = True
    qa_promote_spread_prob_conflict: bool = True  # prob-gap only; spread line-gap stays quarantine
    # QA watchlist — softer holds still tracked but not LOCKED (near-miss EV, etc.).
    qa_watchlist_enabled: bool = True
    qa_air_single_book_totals: bool = True  # legacy alias when promote is off
    qa_air_spread_prob_conflict: bool = True
    qa_air_product_gate_near_miss: bool = True  # EV in [ev_threshold, product_ev_min) → watchlist
    qa_watchlist_unit_scale: float = 1.0  # multiply play-tier units for watchlist tracking
    # Steam detection (pre-kick line velocity across sharp books)
    steam_window_minutes: int = 90  # look-back window for velocity
    steam_min_points: float = 0.5  # minimum aggregate move to consider
    steam_min_books: int = 2  # minimum sharp books moving together
    steam_score_threshold: float = 1.0  # steam score at/above which we flag steam

    # NCAAF totals shadow — paper-track EV ≥12% totals (private data/shadow/, zero extra API)
    ncaaf_totals_shadow_enabled: bool = True

    # NFL simulation totals (board / measurement — not on LOCKED card unless enabled below)
    nfl_totals_sim_count: int = 8000
    # Weight on sim median vs Pinnacle total when blending (0 = auto from OOS history).
    nfl_totals_blend_weight_sim: float = 0.0
    # When blend weight is 0, pick weight via walk-forward choose_blend_weight on prior weeks.
    nfl_totals_blend_auto: bool = True
    # OOS training rows for live walk-forward bias / blend (season backtest CSV).
    nfl_totals_calibration_csv: str = "reports/nfl_totals_sim_backtest_2026.csv"
    # When True, NFL totals may certify to the LOCKED card if the sim lean matches first.
    product_nfl_totals_card_enabled: bool = False

    # Line history: store every book on spreads/totals from existing Odds API responses.
    line_history_all_books: bool = True
    line_history_retain_after: str = "2026-06-01T00:00:00+00:00"
    paper_nfl_totals_momentum_min_move: float = 0.5

    # NBA shadow pipeline (never published to GitHub Pages — see data/shadow/)
    nba_shadow_enabled: bool = True
    nba_ev_threshold: float = 0.02
    nba_prop_ev_threshold: float = 0.02
    nba_prop_over_extra_ev: float = 0.02  # overs need +2% vs base threshold
    nba_prop_consensus_min_books: int = 3
    nba_prop_min_projected_minutes: float = 12.0  # skip unders below this
    nba_prop_horizon_hours: float = 36.0
    nba_max_prop_events_per_run: int = 10  # Odds API budget guardrail
    nba_prop_regions: str = "us,us2"  # props omit eu (Pinnacle not on NBA props feed)
    nba_max_props_per_game: int = 5  # picks + possible props combined, per event
    nba_primary_retail_book: str = "fanduel"
    nba_secondary_retail_book: str = "draftkings"
    nba_unit_dollars: float = 10.0
    nba_kelly_fraction: float = 0.25
    nba_cap_game_line_units: float = 1.5
    nba_cap_prop_units: float = 0.75
    nba_cap_units_per_game: float = 3.0
    nba_cap_units_per_night: float = 8.0
    nba_paper_start: str = "2026-11-02"
    nba_paper_end: str = "2026-12-13"
    nba_pace_min_gap_pts: float = 3.0  # v1 official card (production)
    nba_pace_require_raw_gap: bool = True  # v1: injury adj cannot create a play
    nba_injury_day_to_day_weight: float = 0.18
    nba_injury_impact_scale: float = 0.5  # halve player hits until enough graded injury nights
    nba_injury_impact_scale_full_after_graded: int = 50
    nba_pace_early_season_team_games: int = 15  # v1 half-unit sizing only
    nba_pace_large_gap_warn_pts: float = 7.0  # v1 half-unit sizing only
    nba_pace_half_unit_sizing_enabled: bool = True
    # Shadow Pace v2 (paper only — never on official Jason card)
    nba_pace_v2_shadow_enabled: bool = True
    nba_v2_early_min_gap: bool = True
    nba_v2_early_min_gap_pts: float = 4.5
    nba_v2_early_season_team_games: int = 15
    nba_v2_large_gap_warn_pts: float = 7.0
    nba_v2_exclude_large_gap_early: bool = True
    nba_v2_require_raw_gap: bool = True
    nba_v2_market_blend: bool = True
    nba_v2_schedule_context: bool = True
    nba_v2_roster_priors: bool = True
    nba_v2_slower_observe: bool = True
    # Optional extra line snapshot (disabled — Odds API credits exhausted until reset)
    nba_pace_pre_tip_snapshot_enabled: bool = False
    nba_pace_pre_tip_snapshot_minutes: int = 15
    nba_prop_markets: str = (
        "player_points,player_rebounds,player_assists,player_threes,"
        "player_points_rebounds_assists"
    )

    @property
    def nba_prop_market_list(self) -> list[str]:
        return [m.strip() for m in self.nba_prop_markets.split(",") if m.strip()]

    @property
    def sharp_books(self) -> list[str]:
        return [b.strip() for b in self.sharp_bookmakers.split(",") if b.strip()]

    @property
    def retail_books(self) -> list[str]:
        return [b.strip() for b in self.retail_bookmakers.split(",") if b.strip()]

    @property
    def seasons(self) -> list[int]:
        return [int(s.strip()) for s in self.ratings_seasons.split(",") if s.strip()]

    @property
    def prop_market_list(self) -> list[str]:
        return [m.strip() for m in self.prop_markets.split(",") if m.strip()]

    @property
    def pregame_windows(self) -> list[float]:
        return [float(x.strip()) for x in self.pregame_windows_hours.split(",") if x.strip()]

    @property
    def inactive_list(self) -> list[str]:
        return [x.strip() for x in self.inactive_players.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()