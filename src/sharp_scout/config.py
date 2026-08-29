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
    money_ticket_gap: float = 0.20
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
    # Pregame run windows (hours before kickoff)
    pregame_windows_hours: str = "12,3,1"
    pregame_window_tolerance_minutes: int = 25

    # Optional comma-separated inactive player names for reallocation
    inactive_players: str = ""

    # Model-vs-market disagreement logging ("why is our model wrong?")
    disagreement_prob_threshold: float = 0.05  # |p_true - p_mkt| to flag a disagreement
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