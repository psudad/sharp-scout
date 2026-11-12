"""Re-score locked season plays under pace-scaled margin SD (counterfactual)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.margin_sd_pace import LIVE_MARGIN_SD
from sharp_scout.ncaam.margin_sd_shadow import pace_shadow_sd
from sharp_scout.ncaam.model import p_cover_side, p_ml_side, project_game, simulate_margin
from sharp_scout.ncaam.ratings import load_ratings, ratings_for_team
from sharp_scout.ncaam.rules import RULES, anchor_k_spread, candidate_ev
from sharp_scout.phase3.market import anchor_probability, shift_prob_to_line
from sharp_scout.utils.odds import win_prob_to_conditional

LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    adj = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5)
    lo = (centre - adj) / denom
    hi = (centre + adj) / denom
    return lo, hi


def ratings_path_for_et_day(et_day: str) -> Path | None:
    p = DATA_DIR / "ncaam" / f"ratings_{et_day.replace('-', '')}.csv"
    if p.exists():
        return p
    latest = DATA_DIR / "ncaam" / "ratings_latest.csv"
    return latest if latest.exists() else None


def _ratings_for_day(et: str, cache: dict[str, dict[str, dict[str, float]]]) -> dict[str, dict[str, float]] | None:
    if et not in cache:
        rp = ratings_path_for_et_day(et)
        if not rp:
            return None
        cache[et] = load_ratings(rp)
    return cache[et]


def expected_poss_for_play(play: dict[str, Any], ratings_cache: dict[str, dict[str, dict[str, float]]]) -> float | None:
    if play.get("projected_poss") is not None:
        return float(play["projected_poss"])
    et = str(play.get("et_day") or "")
    ratings = _ratings_for_day(et, ratings_cache)
    if not ratings:
        return None
    hr = ratings_for_team(str(play.get("home_team") or ""), ratings)
    ar = ratings_for_team(str(play.get("away_team") or ""), ratings)
    if not hr or not ar:
        return None
    lg = hr["lg_adjt"]
    return float(hr["adjt"] * ar["adjt"] / max(lg, 1.0))


def replay_play_pace(play: dict[str, Any], ratings_cache: dict[str, dict[str, dict[str, float]]]) -> dict[str, Any] | None:
    status = play.get("status")
    if status in ("void", "no_play", "missed") or not play.get("side"):
        return None
    et = str(play.get("et_day") or "")
    ratings = _ratings_for_day(et, ratings_cache)
    if not ratings:
        return None
    hr = ratings_for_team(str(play.get("home_team") or ""), ratings)
    ar = ratings_for_team(str(play.get("away_team") or ""), ratings)
    if not hr or not ar:
        return None
    proj = project_game(
        home_team=str(play["home_team"]),
        away_team=str(play["away_team"]),
        home_ratings=hr,
        away_ratings=ar,
    )
    poss = expected_poss_for_play(play, ratings_cache)
    if poss is None:
        return None
    sd = pace_shadow_sd(poss)
    market = str(play.get("market"))
    side = str(play.get("side"))
    line = play.get("line")
    price = float(play.get("price") or 0)
    tip = play.get("locked_at") or play.get("created_at")
    try:
        when = datetime.fromisoformat(str(tip).replace("Z", "+00:00"))
    except ValueError:
        when = None
    k = anchor_k_spread(when)

    seed = abs(hash(str(play.get("espn_id")))) % (2**31)
    margins = simulate_margin(proj, sd=sd, rng=np.random.default_rng(seed))
    if market == "spreads" and line is not None:
        p_mod, p_push = p_cover_side(margins, side, float(line))
    else:
        p_mod, p_push = p_ml_side(margins, side)
    p_fair_s = float(play["p_fair"]) if play.get("p_fair") is not None else None
    pin_home = play.get("close_line")
    if (
        market == "spreads"
        and line is not None
        and p_fair_s is not None
        and pin_home is not None
    ):
        p_side_at_pin, _ = shift_prob_to_line(
            p_fair_s,
            market="spreads",
            side=side,
            ref_line=float(line),
            line=float(pin_home) if side == "home" else -float(pin_home),
            sd=LIVE_MARGIN_SD,
        )
        p_home_pin = p_side_at_pin if side == "home" else 1.0 - p_side_at_pin
        p_fair_s, _ = shift_prob_to_line(
            p_home_pin,
            market="spreads",
            side=side,
            ref_line=float(pin_home) if side == "home" else -float(pin_home),
            line=float(line),
            sd=sd,
        )

    p_true = anchor_probability(p_mod, p_fair_s, k, RULES.anchor_tilt_cap)
    p_cond = win_prob_to_conditional(p_true, p_push)
    ev = candidate_ev(p_cond, price, p_push)
    qualifies = ev >= RULES.ev_min
    return {
        "espn_id": play.get("espn_id"),
        "market": market,
        "side": side,
        "status": status,
        "pnl_units": float(play.get("pnl_units") or 0),
        "units": float(play.get("units") or 0),
        "ev_pace": round(ev, 4),
        "ev_live": play.get("ev"),
        "margin_sd_pace": round(sd, 4),
        "margin_sd_live": LIVE_MARGIN_SD,
        "projected_poss": round(poss, 3),
        "would_qualify_pace": qualifies,
    }


def summarize_season_replay(ledger_path: Path | None = None) -> dict[str, Any]:
    path = ledger_path or LEDGER_PATH
    ledger = json.loads(path.read_text())
    cache: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, Any]] = []
    for p in ledger.get("plays") or []:
        if p.get("model_version") != "ncaam-blended-janfeb-v1":
            continue
        rec = replay_play_pace(p, cache)
        if rec:
            rows.append(rec)

    posted_ids = {
        str(p.get("espn_id"))
        for p in ledger.get("plays") or []
        if p.get("status") in ("win", "loss", "push")
        and float(p.get("units") or 0) > 0
        and p.get("side")
    }
    official = [r for r in rows if str(r.get("espn_id")) in posted_ids]
    pace_qual = [r for r in official if r.get("would_qualify_pace")]

    def record(sub: list[dict[str, Any]]) -> dict[str, Any]:
        decided = [r for r in sub if r.get("status") in ("win", "loss")]
        w = sum(1 for r in decided if r.get("status") == "win")
        n = len(decided)
        units = sum(float(r.get("pnl_units") or 0) for r in decided)
        lo, hi = _wilson_ci(w, n)
        return {
            "n_plays": len(sub),
            "n_decided": n,
            "wins": w,
            "losses": n - w,
            "units": round(units, 2),
            "wilson_95": [round(lo, 4), round(hi, 4)],
        }

    return {
        "official_posted": record(official),
        "would_qualify_pace_sd": record(pace_qual),
        "dropped_by_pace_sd": len(official) - len(pace_qual),
        "plays": rows,
    }
