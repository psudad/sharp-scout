"""Phase 1 — Bottom-up opponent-adjusted power ratings (Massey / EPA layer)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from sharp_scout.config import get_settings
from sharp_scout.data.nflfastr import load_pbp
from sharp_scout.utils.odds import normalize_team

logger = logging.getLogger(__name__)


@dataclass
class TeamPower:
    team: str
    off_epa: float
    def_epa: float  # positive = good defense (suppresses opponent EPA)
    off_success: float
    def_success: float
    off_ypp: float
    def_ypp: float
    qb_starter_epa: float
    qb_backup_epa: float
    power: float  # overall: off - league_def_ref + def edge


OFFSEASON_GAP_WEEKS = 4.0  # how "stale" last season's finale is when this season kicks off


def _recency_weights(pbp: pd.DataFrame, half_life_weeks: float) -> np.ndarray:
    """Exponential recency in *football weeks played*, not calendar weeks.

    Calendar decay erased prior seasons: with a 6-week half-life, last January's
    games are ~35 calendar weeks old at Week 2 (weight 0.02), so early-season ratings
    were fit on ~2 games per team and ridge-shrunk to nothing (NFL power sd 0.018,
    every game modeled as home-field only). Counting only weeks with games, plus a
    small offseason gap, keeps last season as a real prior that fades as the current
    season accrues.
    """
    if "week" in pbp.columns and "season" in pbp.columns:
        season = pd.to_numeric(pbp["season"], errors="coerce")
        week = pd.to_numeric(pbp["week"], errors="coerce")
        ok = season.notna() & week.notna()
        if ok.any():
            season_max = int(season[ok].max())
            last_week = week[ok].groupby(season[ok]).max()  # final week seen per season
            cur_week = float(last_week.get(season_max, week[ok].max()))
            weeks_ago = np.zeros(len(pbp))
            # Walk back season by season: weeks left in that season + full seasons in
            # between + one offseason gap per season boundary + weeks into this season.
            for s_val, s_last in last_week.items():
                mask = (season == s_val).to_numpy()
                if s_val == season_max:
                    weeks_ago[mask] = (cur_week - week[mask]).to_numpy()
                    continue
                gap_seasons = [
                    float(last_week[s]) for s in last_week.index if s_val < s < season_max
                ]
                between = sum(gap_seasons) + OFFSEASON_GAP_WEEKS * (season_max - s_val)
                weeks_ago[mask] = (
                    (float(s_last) - week[mask]).to_numpy() + between + cur_week
                )
            weeks_ago = np.maximum(np.nan_to_num(weeks_ago, nan=0.0), 0)
            return np.power(0.5, weeks_ago / max(half_life_weeks, 0.1))
    if "game_date" in pbp.columns:
        dates = pd.to_datetime(pbp["game_date"], errors="coerce")
        max_date = dates.max()
        weeks_ago = (max_date - dates).dt.days.fillna(0).to_numpy() / 7.0
        return np.power(0.5, weeks_ago / max(half_life_weeks, 0.1))
    return np.ones(len(pbp))


def _ridge_team_effects(
    pbp: pd.DataFrame,
    value_col: str,
    half_life: float,
    alpha: float = 50.0,
) -> tuple[dict[str, float], dict[str, float]]:
    """Opponent-adjusted offense/defense effects via ridge on play EPA (or success/ypp)."""
    df = pbp.dropna(subset=["posteam", "defteam", value_col]).copy()
    if df.empty:
        return {}, {}

    teams = sorted(set(df["posteam"].unique()) | set(df["defteam"].unique()))
    team_index = {t: i for i, t in enumerate(teams)}
    n = len(df)
    k = len(teams)

    # Design: offense dummy - defense dummy (sum-to-zero via ridge shrinkage)
    X = np.zeros((n, 2 * k))
    for i, (_, row) in enumerate(df.iterrows()):
        oi = team_index[row["posteam"]]
        di = team_index[row["defteam"]]
        X[i, oi] = 1.0
        X[i, k + di] = 1.0

    y = df[value_col].to_numpy(dtype=float)
    w = _recency_weights(df, half_life)

    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(X, y, sample_weight=w)
    coef = model.coef_
    off = {t: float(coef[team_index[t]]) for t in teams}
    # Defense coef: higher means allowing more of value_col → flip sign so higher=better D
    de = {t: float(-coef[k + team_index[t]]) for t in teams}
    return off, de


QB_BACKUP_MIN_DROPBACKS = 80


def _qb_epa_split(pbp: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Per-team *current* starter vs backup dropback EPA.

    Starter = modal QB over the team's last 4 games (not the whole window, which
    would name a prior-era QB and count the current starter as a backup). Backup EPA
    = the team's non-starter dropbacks; when that sample is thin (< 80 dropbacks) it
    is replaced by the league-wide non-starter mean so a handful of garbage-time
    snaps can't make a backup look better than the starter.
    """
    if "passer_player_name" not in pbp.columns:
        return {}
    qb = pbp[pbp["is_dropback"].astype(bool) & pbp["passer_player_name"].notna()].copy()
    if qb.empty:
        return {}
    starters = current_qb_starters(qb)
    is_starter = qb["passer_player_name"] == qb["posteam"].map(starters)
    league_backup = qb.loc[~is_starter, "epa"]
    league_backup_epa = float(league_backup.mean()) if len(league_backup) else 0.0
    out: dict[str, tuple[float, float]] = {}
    for team, g in qb.groupby("posteam"):
        starter = starters.get(str(team))
        if starter is None:
            continue
        s = g.loc[g["passer_player_name"] == starter, "epa"]
        starter_epa = float(s.mean()) if len(s) else 0.0
        backup = g.loc[g["passer_player_name"] != starter, "epa"]
        backup_epa = float(backup.mean()) if len(backup) >= QB_BACKUP_MIN_DROPBACKS else league_backup_epa
        out[str(team)] = (starter_epa, backup_epa)
    return out


def build_power_ratings(pbp: pd.DataFrame | None = None) -> dict[str, TeamPower]:
    settings = get_settings()
    if pbp is None:
        pbp = load_pbp(settings.seasons)
    if pbp.empty:
        logger.warning("Empty PBP — using neutral prior ratings for all 32 teams")
        return _neutral_ratings()

    half = settings.epa_half_life_weeks
    off_epa, def_epa = _ridge_team_effects(pbp, "epa", half, alpha=80.0)

    # Success rate on early downs
    early = pbp[pbp["down"].isin([1, 2])] if "down" in pbp.columns else pbp
    off_sr, def_sr = _ridge_team_effects(early, "success", half, alpha=60.0)

    # Yards per play
    off_ypp, def_ypp = _ridge_team_effects(pbp, "yards_gained", half, alpha=60.0)

    qb = _qb_epa_split(pbp)
    teams = sorted(set(off_epa) | set(def_epa))
    if not teams:
        return _neutral_ratings()

    # Center power around 0
    off_vals = np.array([off_epa.get(t, 0.0) for t in teams])
    def_vals = np.array([def_epa.get(t, 0.0) for t in teams])
    off_c = off_vals - off_vals.mean()
    def_c = def_vals - def_vals.mean()

    ratings: dict[str, TeamPower] = {}
    for i, t in enumerate(teams):
        starter, backup = qb.get(t, (off_c[i], off_c[i]))
        power = float(off_c[i] + def_c[i])  # both already oriented "higher=better"
        ratings[t] = TeamPower(
            team=t,
            off_epa=float(off_c[i]),
            def_epa=float(def_c[i]),
            off_success=float(off_sr.get(t, 0.0)),
            def_success=float(def_sr.get(t, 0.0)),
            off_ypp=float(off_ypp.get(t, 0.0)),
            def_ypp=float(def_ypp.get(t, 0.0)),
            qb_starter_epa=float(starter),
            qb_backup_epa=float(backup),
            power=power,
        )
    logger.info("Built power ratings for %d teams", len(ratings))
    return ratings


QB_DELTA_CLIP = (-0.35, 0.15)  # EPA/dropback; a −0.35 swing ≈ −10 pts at NFL scale


def qb_short_name(full: str | None) -> str | None:
    """'Caleb Williams' → 'C.Williams' (nflverse passer_player_name form)."""
    if not isinstance(full, str) or not full.strip():
        return None
    parts = full.replace(".", " ").split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0][0]}.{parts[-1]}"


def current_qb_starters(pbp: pd.DataFrame, last_n_games: int = 4) -> dict[str, str]:
    """QB with the most dropbacks over each team's last N games (short-name form)."""
    if pbp is None or pbp.empty or "passer_player_name" not in pbp.columns:
        return {}
    qb = pbp[pbp["is_dropback"].astype(bool) & pbp["passer_player_name"].notna()]
    sort_col = "game_date" if "game_date" in qb.columns else "week"
    out: dict[str, str] = {}
    for team, g in qb.groupby("posteam"):
        recent = g.sort_values(sort_col)["game_id"].drop_duplicates().tail(last_n_games)
        counts = g[g["game_id"].isin(recent)].groupby("passer_player_name").size()
        if not counts.empty:
            out[str(team)] = str(counts.idxmax())
    return out


def backups_from_inactives(
    starters: dict[str, str],
    inactive_players: list[str],
) -> dict[str, bool]:
    """Teams whose current starting QB appears on the inactive list."""
    inactive = {qb_short_name(n).lower() for n in inactive_players if qb_short_name(n)}
    return {team: True for team, qb in starters.items() if qb.lower() in inactive}


def apply_qb_adjustment(ratings: dict[str, TeamPower], backups: dict[str, bool]) -> dict[str, TeamPower]:
    """If team is on backup QB, shift off_epa by the starter→backup EPA/dropback delta.

    Backtest 2024–26 (215 QB-change team-games): unadjusted model 46.2% ATS on those
    games → 52.2% adjusted; overall 48.7% → 51.5%.
    """
    out = dict(ratings)
    for team, is_backup in backups.items():
        if not is_backup or team not in out:
            continue
        r = out[team]
        delta = float(np.clip(r.qb_backup_epa - r.qb_starter_epa, *QB_DELTA_CLIP))
        logger.info("QB adjustment %s: backup delta %+.3f EPA/dropback", team, delta)
        out[team] = TeamPower(
            team=r.team,
            off_epa=r.off_epa + delta,
            def_epa=r.def_epa,
            off_success=r.off_success,
            def_success=r.def_success,
            off_ypp=r.off_ypp,
            def_ypp=r.def_ypp,
            qb_starter_epa=r.qb_starter_epa,
            qb_backup_epa=r.qb_backup_epa,
            power=r.power + delta,
        )
    return out


def matchup_means(
    home: str,
    away: str,
    ratings: dict[str, TeamPower],
    home_boost: float = 2.2,
    total_adj: float = 0.0,
    sport: str = "nfl",
    scoring_base: float | None = None,
    epa_scale: float | None = None,
) -> dict[str, float]:
    """Convert power ratings into expected points for home/away."""
    from sharp_scout.sports import get_sport

    cfg = get_sport(sport)
    base = cfg.scoring_base if scoring_base is None else scoring_base
    scale = cfg.epa_scale if epa_scale is None else epa_scale

    hr = ratings.get(normalize_team(home, sport)) or TeamPower(home, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    ar = ratings.get(normalize_team(away, sport)) or TeamPower(away, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    home_off = base + scale * (hr.off_epa - ar.def_epa) + home_boost / 2
    away_off = base + scale * (ar.off_epa - hr.def_epa) - home_boost / 2

    home_off += total_adj / 2
    away_off += total_adj / 2

    home_off = float(np.clip(home_off, 7.0, 45.0))
    away_off = float(np.clip(away_off, 7.0, 45.0))
    return {
        "mu_home": home_off,
        "mu_away": away_off,
        "model_spread": away_off - home_off,  # home perspective: negative => home favored
        "model_total": home_off + away_off,
    }


def _neutral_ratings() -> dict[str, TeamPower]:
    teams = [
        "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
        "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
        "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
        "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
    ]
    return {
        t: TeamPower(t, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        for t in teams
    }


def ratings_as_of_now(ratings: dict[str, TeamPower]) -> list[dict]:
    ts = datetime.now(timezone.utc)
    rows = []
    for r in ratings.values():
        rows.append(
            {
                "as_of": ts,
                "team": r.team,
                "off_epa": r.off_epa,
                "def_epa": r.def_epa,
                "off_success": r.off_success,
                "def_success": r.def_success,
                "off_ypp": r.off_ypp,
                "def_ypp": r.def_ypp,
                "qb_starter_epa": r.qb_starter_epa,
                "qb_backup_epa": r.qb_backup_epa,
                "power": r.power,
            }
        )
    return rows