"""Scheme / matchup tendency features for the interaction engine.

Tom's matchup-interaction engine needs to know *how a specific offense interacts with a
specific defense* — pressure sensitivity, man/zone, explosive-play rates, etc. The richest
of that (coverage shell, man/zone, charted pressure) lives in nflverse FTN charting /
participation data, but that only publishes **after the season ends**, so it can only serve
as prior-season tendency priors in-season.

This module therefore builds features in two tiers:

1. **Base tendencies** derivable from the play-by-play we already load every run (pass rate,
   early-down pass rate, explosive pass/rush rates on offense and allowed on defense, pace).
   These are always available and keep the engine running offline / in CI.
2. **Optional enrichment** from nflverse FTN charting / participation (man/zone, blitz,
   pressure, coverage shells) when ``nflreadpy`` is installed and the data exists. Missing
   enrichment degrades gracefully to the base tendencies.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Feature names produced per team (order stable for the model).
BASE_FEATURES = (
    "off_pass_rate",
    "off_early_down_pass_rate",
    "off_explosive_pass_rate",
    "off_explosive_rush_rate",
    "def_explosive_pass_allowed",
    "def_explosive_rush_allowed",
    "off_epa",
    "def_epa",
    "pace_plays",
)

ENRICH_FEATURES = (
    "def_blitz_rate",
    "def_man_rate",
    "def_zone_rate",
    "def_pressure_rate",
    "off_pressure_allowed",
)

ALL_FEATURES = BASE_FEATURES + ENRICH_FEATURES


def _safe_mean(series: pd.Series) -> float:
    try:
        val = float(series.mean())
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if val != val else val  # NaN guard


def build_base_features(
    pbp: pd.DataFrame,
    ratings: dict[str, Any] | None = None,
) -> dict[str, dict[str, float]]:
    """Team tendency features from normalized play-by-play (always available)."""
    if pbp is None or pbp.empty:
        return {}

    df = pbp.copy()
    if "is_dropback" not in df.columns and "pass" in df.columns:
        df["is_dropback"] = df["pass"].fillna(0).astype(bool)
    if "is_rush" not in df.columns and "rush" in df.columns:
        df["is_rush"] = df["rush"].fillna(0).astype(bool)
    df["yards_gained"] = df.get("yards_gained", pd.Series([0.0] * len(df))).fillna(0.0)

    teams = sorted(set(df["posteam"].dropna()) | set(df["defteam"].dropna()))
    out: dict[str, dict[str, float]] = {}
    n_games_by_team: dict[str, int] = {}
    if "game_id" in df.columns:
        for team in teams:
            games = df.loc[df["posteam"] == team, "game_id"].nunique()
            n_games_by_team[team] = max(int(games), 1)

    for team in teams:
        off = df[df["posteam"] == team]
        deff = df[df["defteam"] == team]
        off_pass = off[off.get("is_dropback", False) == True]  # noqa: E712
        off_rush = off[off.get("is_rush", False) == True]  # noqa: E712
        early = off[off["down"].isin([1, 2])] if "down" in off.columns else off

        feats = {
            "off_pass_rate": _safe_mean(off.get("is_dropback", pd.Series(dtype=float)).astype(float)),
            "off_early_down_pass_rate": _safe_mean(
                early.get("is_dropback", pd.Series(dtype=float)).astype(float)
            ),
            "off_explosive_pass_rate": _safe_mean((off_pass["yards_gained"] >= 20).astype(float))
            if len(off_pass)
            else 0.0,
            "off_explosive_rush_rate": _safe_mean((off_rush["yards_gained"] >= 10).astype(float))
            if len(off_rush)
            else 0.0,
            "def_explosive_pass_allowed": _safe_mean(
                (deff[deff.get("is_dropback", False) == True]["yards_gained"] >= 20).astype(float)  # noqa: E712
            )
            if len(deff)
            else 0.0,
            "def_explosive_rush_allowed": _safe_mean(
                (deff[deff.get("is_rush", False) == True]["yards_gained"] >= 10).astype(float)  # noqa: E712
            )
            if len(deff)
            else 0.0,
            "off_epa": 0.0,
            "def_epa": 0.0,
            "pace_plays": float(len(off) / n_games_by_team.get(team, 1)),
        }
        if ratings and team in ratings:
            r = ratings[team]
            feats["off_epa"] = float(getattr(r, "off_epa", 0.0))
            feats["def_epa"] = float(getattr(r, "def_epa", 0.0))
        # Enrichment placeholders (filled if FTN/participation available)
        for k in ENRICH_FEATURES:
            feats[k] = 0.0
        out[team] = feats
    return out


def enrich_with_ftn(
    features: dict[str, dict[str, float]],
    seasons: list[int] | None = None,
) -> dict[str, dict[str, float]]:
    """Best-effort man/zone/blitz/pressure enrichment from nflverse (prior-season priors).

    Silently returns ``features`` unchanged if nflreadpy or the data is unavailable
    (e.g. current season not yet published — FTN releases post-season only).
    """
    try:
        import nflreadpy as nfl  # type: ignore
    except Exception:  # noqa: BLE001
        logger.info("nflreadpy not installed — scheme enrichment skipped (base features only)")
        return features

    try:
        part = nfl.load_participation(seasons=seasons) if seasons else nfl.load_participation()
        pdf = part.to_pandas() if hasattr(part, "to_pandas") else pd.DataFrame(part)
    except Exception as exc:  # noqa: BLE001
        logger.info("participation data unavailable (%s) — base features only", exc)
        return features

    if pdf is None or pdf.empty:
        return features

    # Defensive tendencies by team (man/zone/blitz/pressure) — column names per FTN dict.
    try:
        for team, g in pdf.groupby(pdf.get("defteam", pdf.get("defense_team"))):
            if team not in features:
                continue
            if "defense_man_zone_type" in g:
                man = (g["defense_man_zone_type"].astype(str).str.upper() == "MAN_COVERAGE").mean()
                zone = (g["defense_man_zone_type"].astype(str).str.upper() == "ZONE_COVERAGE").mean()
                features[team]["def_man_rate"] = float(man) if man == man else 0.0
                features[team]["def_zone_rate"] = float(zone) if zone == zone else 0.0
            if "number_of_pass_rushers" in g:
                blitz = (pd.to_numeric(g["number_of_pass_rushers"], errors="coerce") >= 5).mean()
                features[team]["def_blitz_rate"] = float(blitz) if blitz == blitz else 0.0
            if "was_pressure" in g:
                pr = pd.to_numeric(g["was_pressure"], errors="coerce").mean()
                features[team]["def_pressure_rate"] = float(pr) if pr == pr else 0.0
        logger.info("Scheme features enriched from nflverse participation data")
    except Exception as exc:  # noqa: BLE001
        logger.info("participation enrichment failed (%s) — base features only", exc)
    return features


def build_scheme_features(
    pbp: pd.DataFrame,
    ratings: dict[str, Any] | None = None,
    *,
    enrich: bool = True,
    seasons: list[int] | None = None,
) -> dict[str, dict[str, float]]:
    feats = build_base_features(pbp, ratings)
    if enrich and feats:
        feats = enrich_with_ftn(feats, seasons=seasons)
    return feats


def matchup_feature_vector(
    home_feats: dict[str, float],
    away_feats: dict[str, float],
) -> dict[str, float]:
    """Interaction-oriented features: offense vs opposing defense, both directions."""
    hv = home_feats or {}
    av = away_feats or {}
    vec: dict[str, float] = {}
    # Home offense attacking away defense
    vec["h_off_pass_vs_a_def_press"] = hv.get("off_pass_rate", 0.0) * av.get("def_pressure_rate", 0.0)
    vec["h_off_expl_pass_vs_a_def_pass_allowed"] = (
        hv.get("off_explosive_pass_rate", 0.0) + av.get("def_explosive_pass_allowed", 0.0)
    )
    vec["h_off_expl_rush_vs_a_def_rush_allowed"] = (
        hv.get("off_explosive_rush_rate", 0.0) + av.get("def_explosive_rush_allowed", 0.0)
    )
    # Away offense attacking home defense
    vec["a_off_pass_vs_h_def_press"] = av.get("off_pass_rate", 0.0) * hv.get("def_pressure_rate", 0.0)
    vec["a_off_expl_pass_vs_h_def_pass_allowed"] = (
        av.get("off_explosive_pass_rate", 0.0) + hv.get("def_explosive_pass_allowed", 0.0)
    )
    vec["a_off_expl_rush_vs_h_def_rush_allowed"] = (
        av.get("off_explosive_rush_rate", 0.0) + hv.get("def_explosive_rush_allowed", 0.0)
    )
    # Pace and rating diffs
    vec["pace_diff"] = hv.get("pace_plays", 0.0) - av.get("pace_plays", 0.0)
    vec["off_epa_diff"] = hv.get("off_epa", 0.0) - av.get("off_epa", 0.0)
    vec["def_epa_diff"] = hv.get("def_epa", 0.0) - av.get("def_epa", 0.0)
    vec["blitz_diff"] = hv.get("def_blitz_rate", 0.0) - av.get("def_blitz_rate", 0.0)
    vec["man_diff"] = hv.get("def_man_rate", 0.0) - av.get("def_man_rate", 0.0)
    return vec


MATCHUP_VECTOR_KEYS = (
    "h_off_pass_vs_a_def_press",
    "h_off_expl_pass_vs_a_def_pass_allowed",
    "h_off_expl_rush_vs_a_def_rush_allowed",
    "a_off_pass_vs_h_def_press",
    "a_off_expl_pass_vs_h_def_pass_allowed",
    "a_off_expl_rush_vs_h_def_rush_allowed",
    "pace_diff",
    "off_epa_diff",
    "def_epa_diff",
    "blitz_diff",
    "man_diff",
)
