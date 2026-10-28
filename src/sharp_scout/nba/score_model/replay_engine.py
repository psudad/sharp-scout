"""Rebuild score engine ratings as of an ET slate date (for offline Pace replay)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any

from sharp_scout.data.espn_nba import fetch_espn_nba_finals_by_event
from sharp_scout.nba.score_model.engine import V2Engine, V2Params
from sharp_scout.nba.score_model.engine_v2 import ShadowV2Engine, ShadowV2Params
from sharp_scout.nba.score_model.state import (
    _games_from_scores,
    _replay_games,
    _season_start_date,
    apply_committed_priors,
    load_committed_priors,
    load_state_file,
)
from sharp_scout.nba.score_model.state_v2 import (
    PRIORS_PATH as PRIORS_V2_PATH,
    apply_committed_priors as apply_v2_priors,
    load_committed_priors as load_v2_priors,
)
from sharp_scout.nba.score_model import state_v2 as state_v2_mod
from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.slate import ET

logger = logging.getLogger(__name__)


def _games_from_paper_graded(store: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for g in store.get("games") or []:
        gr = g.get("graded")
        if not gr:
            continue
        kick_raw = g.get("kickoff")
        kick = kick_raw
        from sharp_scout.utils.kickoff import parse_kickoff_utc

        kick_dt = parse_kickoff_utc(kick_raw)
        if kick_dt is None:
            continue
        act_m = int(gr["actual_margin"])
        act_t = int(gr["actual_total"])
        hs = (act_t + act_m) // 2
        as_ = (act_t - act_m) // 2
        home = g["home"]
        away = g["away"]
        from sharp_scout.nba.score_model.state import _season_label  # noqa: PLC0415

        out.append(
            {
                "home": home,
                "away": away,
                "home_pts": float(hs),
                "away_pts": float(as_),
                "date": kick_dt,
                "season": _season_label(kick_dt),
                "game_poss": max(act_t / 2.2, 90.0),
                "event_id": g.get("event_id"),
            }
        )
    out.sort(key=lambda x: x["date"])
    return out


def engine_at_start_of_et_date(
    slate_day: date,
    *,
    paper_store: dict[str, Any] | None = None,
    use_espn: bool = True,
) -> V2Engine:
    """Ratings after all games with ET date strictly before ``slate_day``."""
    engine = V2Engine(params=V2Params(), stage=3)
    priors = load_committed_priors()
    if priors:
        apply_committed_priors(engine, priors)
    else:
        logger.warning("replay engine: no committed priors")

    state_raw = load_state_file()
    poss_cache: dict[str, float] = {}
    if state_raw:
        poss_cache = {str(k): float(v) for k, v in (state_raw.get("poss_cache") or {}).items()}

    games: list[dict[str, Any]] = []
    if use_espn:
        season_start = _season_start_date(datetime.combine(slate_day, time(12, 0), tzinfo=ET))
        since = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
        until = datetime.combine(slate_day, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
        try:
            scores = fetch_espn_nba_finals_by_event(since=since, until=until)
            games = _games_from_scores(scores, poss_cache=poss_cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("replay engine: ESPN fetch failed (%s)", exc)
            games = []

    if paper_store:
        paper_games = _games_from_paper_graded(paper_store)
        seen = {f"{g['away']}@{g['home']}@{kickoff_date_et(g['date'])}" for g in games}
        for pg in paper_games:
            day = kickoff_date_et(pg["date"])
            if day is None or day >= slate_day:
                continue
            key = f"{pg['away']}@{pg['home']}@{day}"
            if key not in seen:
                games.append(pg)
                seen.add(key)
    games = [g for g in games if (kickoff_date_et(g["date"]) or date.max) < slate_day]
    games.sort(key=lambda g: g["date"])
    processed: set[str] = set()
    _replay_games(engine, games, processed)
    return engine


def shadow_engine_at_start_of_et_date(
    slate_day: date,
    *,
    paper_store: dict[str, Any] | None = None,
    use_espn: bool = True,
) -> ShadowV2Engine:
    """v2 shadow ratings (look-ahead-free priors file) before ``slate_day``."""
    engine = ShadowV2Engine(params=ShadowV2Params(), stage=3)
    priors = load_v2_priors(PRIORS_V2_PATH)
    if priors:
        apply_v2_priors(engine, priors)
    else:
        logger.warning("replay shadow: no v2 priors at %s", PRIORS_V2_PATH)

    state_raw = state_v2_mod.load_state_file()
    poss_cache: dict[str, float] = {}
    if state_raw:
        poss_cache = {str(k): float(v) for k, v in (state_raw.get("poss_cache") or {}).items()}

    games: list[dict[str, Any]] = []
    if use_espn:
        season_start = _season_start_date(datetime.combine(slate_day, time(12, 0), tzinfo=ET))
        since = datetime.combine(season_start, datetime.min.time(), tzinfo=timezone.utc)
        until = datetime.combine(slate_day, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc)
        try:
            scores = fetch_espn_nba_finals_by_event(since=since, until=until)
            games = _games_from_scores(scores, poss_cache=poss_cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("replay shadow: ESPN fetch failed (%s)", exc)
            games = []

    if paper_store:
        paper_games = _games_from_paper_graded(paper_store)
        seen = {f"{g['away']}@{g['home']}@{kickoff_date_et(g['date'])}" for g in games}
        for pg in paper_games:
            day = kickoff_date_et(pg["date"])
            if day is None or day >= slate_day:
                continue
            key = f"{pg['away']}@{pg['home']}@{day}"
            if key not in seen:
                games.append(pg)
                seen.add(key)
    games = [g for g in games if (kickoff_date_et(g["date"]) or date.max) < slate_day]
    games.sort(key=lambda g: g["date"])
    processed: set[str] = set()
    state_v2_mod._replay_games(engine, games, processed)
    return engine
