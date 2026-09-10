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
    prop_markets: str = (
        "player_pass_yds,player_pass_tds,player_rush_yds,player_rush_attempts,"
        "player_receptions,player_reception_yds,player_reception_tds,player_anytime_td"
    )
    prop_ev_threshold: float = 0.02
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
    # Props run in shadow mode until the projection is calibrated against settled prop
    # history: artifacts are still written for review, but nothing reaches the ledger or
    # the public board. Set PROPS_PUBLISH_ENABLED=true to publish.
    props_publish_enabled: bool = False
    # Pregame run windows (hours before kickoff)
    pregame_windows_hours: str = "12,3,1"
    pregame_window_tolerance_minutes: int = 25

    # Optional comma-separated inactive player names for reallocation
    inactive_players: str = ""

    # Model-vs-market disagreement logging ("why is our model wrong?")
    disagreement_prob_threshold: float = 0.05  # |p_true - p_mkt| to flag a disagreement
    # QA gate — quarantine spreads when model and sharp market disagree implausibly
    spread_model_prob_gap: float = 0.15  # |p_true - p_mkt| quarantine threshold
    spread_model_line_gap: float = 4.0  # |model_spread - home market line| in points
    # Steam detection (pre-kick line velocity across sharp books)
    steam_window_minutes: int = 90  # look-back window for velocity
    steam_min_points: float = 0.5  # minimum aggregate move to consider
    steam_min_books: int = 2  # minimum sharp books moving together
    steam_score_threshold: float = 1.0  # steam score at/above which we flag steam

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