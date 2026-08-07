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

    ev_threshold: float = 0.02
    money_ticket_gap: float = 0.20
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

    @property
    def sharp_books(self) -> list[str]:
        return [b.strip() for b in self.sharp_bookmakers.split(",") if b.strip()]

    @property
    def retail_books(self) -> list[str]:
        return [b.strip() for b in self.retail_bookmakers.split(",") if b.strip()]

    @property
    def seasons(self) -> list[int]:
        return [int(s.strip()) for s in self.ratings_seasons.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()