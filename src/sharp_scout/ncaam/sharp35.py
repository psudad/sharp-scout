"""Sharp 3.5: the quant rules (public name "Sharp 3.5").

Phase 1 needs two or more of: whale gap, reverse line movement, bubble / slumping home dog,
bounce-back. Phase 2 runs a 1,000-draw Monte Carlo on the Torvik projection with the
situational coefficients and compares the cover probability with Shin's no-vig price.
Spreads only. Bounce-back is tagged only (no math change).
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from sharp_scout.ncaam.lab_stakes import cap_lab_stake
from sharp_scout.ncaam.model import p_cover_side, project_game
from sharp_scout.ncaam.ratings import ratings_for_team
from sharp_scout.ncaam.shin import implied, shin_two_way
from sharp_scout.ncaam.splits import has_splits

ENGINE = "sharp35"
PUBLIC_NAME = "Sharp 3.5"
MODEL_VERSION = "sharp35-v1"

WHALE_GAP = 20.0
WHALE_GAP_MID_MAJOR = 15.0
RLM_PUBLIC_TICKETS = 60.0
RLM_POINTS = 1.0
BASE_HCA = 3.0
CONF_HCA_CUT = 0.4
HOSTILE_DE_MULT = 0.95
STAR_MARGIN = 2.5
SIMS = 1000
SIM_SD = 10.5
ANOMALY_EDGE = 15.0
MIN_EDGE = 2.5
VERIFY_BOOKS = ("fanduel", "draftkings")
TIER_RANK = {"LEAN": 0, "GOLD": 2, "DIAMOND": 3, "DOUBLE_DIAMOND": 4}


def tier_and_units(edge: float) -> tuple[str | None, float]:
    """Returns (tier, units). tier None = data anomaly (discard); LEAN = 0u, not played."""
    if edge > ANOMALY_EDGE:
        return None, 0.0
    if edge < MIN_EDGE:
        return "LEAN", 0.0
    if edge >= 5.0:
        units = min(10.0, max(5.0, edge))
        return "DOUBLE_DIAMOND", cap_lab_stake(units)
    if edge >= 3.5:
        return "DIAMOND", cap_lab_stake(min(4.0, max(2.0, 2.0 + (edge - 3.5) / 1.5 * 2.0)))
    return "GOLD", cap_lab_stake(min(2.0, max(1.0, 1.0 + (edge - 2.5))))


def _seed(espn_id: str) -> int:
    return int(hashlib.sha256(f"sharp35|{espn_id}".encode()).hexdigest()[:12], 16)


def _verify_market(event: dict[str, Any] | None, splits: dict[str, Any] | None) -> dict[str, Any] | None:
    """Two-way spread from FanDuel, else DraftKings. Falls back to the AN line for previews."""
    books = (event or {}).get("bookmakers") or {}
    for b in VERIFY_BOOKS:
        outs = ((books.get(b) or {}).get("markets") or {}).get("spreads") or []
        by = {o.get("side"): o for o in outs if o.get("point") is not None and o.get("price") is not None}
        if "home" in by and "away" in by:
            return {
                "book": b,
                "source": "odds_api",
                "home": (float(by["home"]["point"]), float(by["home"]["price"])),
                "away": (float(by["away"]["point"]), float(by["away"]["price"])),
            }
    sp = (splits or {}).get("spread") or {}
    h, a = sp.get("home") or {}, sp.get("away") or {}
    if None not in (h.get("line"), h.get("price"), a.get("line"), a.get("price")):
        return {
            "book": "actionnetwork",
            "source": "actionnetwork",
            "home": (float(h["line"]), float(h["price"])),
            "away": (float(a["line"]), float(a["price"])),
        }
    return None


def phase1(
    game: dict[str, Any],
    splits: dict[str, Any],
    market: dict[str, Any] | None,
    *,
    is_mid_major_by_side: dict[str, bool],
    situational: Any | None,
) -> dict[str, Any]:
    sp = splits.get("spread") or {}
    signals: dict[str, list[str]] = {"home": [], "away": []}
    gaps: dict[str, float] = {}
    for s in ("home", "away"):
        d = sp.get(s) or {}
        gaps[s] = float(d.get("money_pct") or 0) - float(d.get("ticket_pct") or 0)
        need = WHALE_GAP_MID_MAJOR if is_mid_major_by_side.get(s, True) else WHALE_GAP
        if gaps[s] >= need:
            signals[s].append("WHALE_GAP")
    # Reverse line movement: the >60% ticket side's line moved >= 1 point against it.
    opener = splits.get("open_line") or {}
    for pub in ("home", "away"):
        other = "away" if pub == "home" else "home"
        t = (sp.get(pub) or {}).get("ticket_pct")
        if t is None or float(t) <= RLM_PUBLIC_TICKETS:
            continue
        o = opener.get(pub)
        cur = market[pub][0] if market else (sp.get(pub) or {}).get("line")
        if o is not None and cur is not None and float(cur) - float(o) >= RLM_POINTS:
            signals[other].append("RLM")
    home_line = market["home"][0] if market else (sp.get("home") or {}).get("line")
    streaks: dict[str, int] = {}
    if situational is not None:
        for s in ("home", "away"):
            team = game.get(f"{s}_team")
            tid = str(game.get(f"{s}_espn_team_id") or "")
            try:
                bubble = bool(team and situational.on_bubble(team))
                streak = situational.losing_streak(tid) if tid else 0
                bounce = situational.bounce_back(tid) if tid else False
            except Exception:  # noqa: BLE001
                bubble, streak, bounce = False, 0, False
            streaks[s] = streak
            home_dog = s == "home" and home_line is not None and float(home_line) > 0 and not game.get("neutral_site")
            if bubble:
                signals[s].append("BUBBLE")
            elif home_dog and streak >= 3:
                signals[s].append("HOME_DOG_SLUMP")
            if bounce:
                signals[s].append("BOUNCE_BACK")
    shortlisted = any(len(v) >= 2 for v in signals.values())
    pick = max(("home", "away"), key=lambda s: (gaps[s], s == "home"))
    return {
        "signals": signals,
        "gaps": gaps,
        "streaks": streaks,
        "shortlisted": shortlisted,
        "side": pick,
        "gap": round(max(gaps.values()), 2),
        "home_line": home_line,
    }


def phase2(
    game: dict[str, Any],
    side: str,
    market: dict[str, Any],
    ratings: dict[str, dict[str, float]],
    *,
    hostile: bool,
    star_out: dict[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    hr = ratings_for_team(str(game.get("home_team") or ""), ratings)
    ar = ratings_for_team(str(game.get("away_team") or ""), ratings)
    if not hr or not ar:
        return None
    neutral = bool(game.get("neutral_site"))
    hca = BASE_HCA - (CONF_HCA_CUT if game.get("conference_game") else 0.0)
    if hostile:
        hr = {**hr, "adjde": hr["adjde"] * HOSTILE_DE_MULT}
    proj = project_game(
        home_team=str(game["home_team"]),
        away_team=str(game["away_team"]),
        home_ratings=hr,
        away_ratings=ar,
        neutral_site=neutral,
        hfa=hca,
    )
    margin = proj.margin_model
    star_out = star_out or {}
    if star_out.get("home"):
        margin -= STAR_MARGIN
    if star_out.get("away"):
        margin += STAR_MARGIN
    rng = np.random.default_rng(_seed(str(game.get("espn_id") or "")))
    margins = margin + rng.normal(0.0, SIM_SD, size=SIMS)
    line, price = market[side]
    other = "away" if side == "home" else "home"
    conf, _push = p_cover_side(margins, side, line)
    p_side, p_other, _z = shin_two_way(implied(price), implied(market[other][1]))
    edge = (conf - p_side) * 100.0
    return {
        "margin_model": round(margin, 2),
        "conf": round(conf, 4),
        "novig": round(p_side, 4),
        "edge": round(edge, 2),
        "line": line,
        "price": price,
        "sim_rec": f"{int(round(conf * SIMS))}-{SIMS - int(round(conf * SIMS))}",
    }


def evaluate(
    game: dict[str, Any],
    splits: dict[str, Any] | None,
    event: dict[str, Any] | None,
    ratings: dict[str, dict[str, float]],
    *,
    is_mid_major_by_side: dict[str, bool],
    situational: Any | None = None,
    with_star: bool = False,
) -> dict[str, Any]:
    base = {
        "engine": ENGINE,
        "espn_id": str(game.get("espn_id") or ""),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "market": "spreads",
    }
    sp = (splits or {}).get("spread") or {}
    if not has_splits(splits):
        return {**base, "result": "no_splits", "reason": "No splits data"}
    market = _verify_market(event, splits)
    p1 = phase1(game, splits or {}, market, is_mid_major_by_side=is_mid_major_by_side, situational=situational)
    side = p1["side"]
    tags = sorted(set(p1["signals"]["home"] + p1["signals"]["away"]))
    out = {
        **base,
        "side": side,
        "gap": p1["gap"],
        "signals": p1["signals"],
        "flags": tags,
        "money_pct": sp[side].get("money_pct"),
        "ticket_pct": sp[side].get("ticket_pct"),
        "splits_source": (splits or {}).get("splits_source"),
        "shortlisted": p1["shortlisted"],
    }
    if not p1["shortlisted"]:
        return {**out, "result": "not_shortlisted", "reason": "Fewer than 2 signals"}
    if market is None:
        return {**out, "result": "warning", "reason": "No verifying book line"}
    home_line = market["home"][0]
    hostile = (
        not game.get("neutral_site")
        and home_line > 0
        and ("BUBBLE" in p1["signals"]["home"] or p1["streaks"].get("home", 0) >= 3)
    )
    stars: dict[str, list[str]] = {}
    if with_star and situational is not None:
        for s in ("home", "away"):
            try:
                stars[s] = situational.star_out(
                    str(game.get(f"{s}_team") or ""), str(game.get(f"{s}_espn_team_id") or "")
                )
            except Exception:  # noqa: BLE001
                stars[s] = []
    p2 = phase2(game, side, market, ratings, hostile=hostile, star_out=stars)
    if p2 is None:
        return {**out, "result": "warning", "reason": "No ratings"}
    flags = list(tags)
    if hostile:
        flags.append("HOSTILE_ENV")
    for s, names in stars.items():
        if names:
            flags.append(f"STAR_OUT_{s.upper()}")
    tier, units = tier_and_units(p2["edge"])
    out.update(p2)
    out.update(
        {
            "flags": flags,
            "book": market["book"],
            "line_source": market["source"],
            "tier": tier or "ANOMALY",
            "units": units,
            "price_estimated": False,
        }
    )
    if tier is None:
        out.update(result="anomaly", reason="Data anomaly (edge above 15%)")
    elif tier == "LEAN":
        out.update(result="lean", reason="System lean (edge below 2.5%)")
    else:
        out["result"] = "play"
    return out
