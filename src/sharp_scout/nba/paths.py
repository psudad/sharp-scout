"""Private on-disk locations for NBA shadow mode."""

from __future__ import annotations

from pathlib import Path

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR

SHADOW_DIR = DATA_DIR / "shadow"
NBA_LEDGER_PATH = SHADOW_DIR / "nba_ledger.json"
NBA_LINE_HISTORY_PATH = SHADOW_DIR / "nba_line_history.json"
NBA_PLAYER_RATES_PATH = SHADOW_DIR / "nba_player_rates.json"
NBA_LATEST_SIGNALS_PATH = SHADOW_DIR / "nba_latest_signals.json"
NBA_REPORT_PATH = SHADOW_DIR / "nba_paper_report.json"
NBA_ARTIFACT_DIR = ARTIFACTS_DIR / "nba_shadow"
PAPER_DIR = DATA_DIR / "paper"
NBA_SCORE_MODEL_PAPER_PATH = PAPER_DIR / "nba_score_model.json"
NBA_INJURY_LAG_PAPER_PATH = PAPER_DIR / "nba_injury_lag.json"
