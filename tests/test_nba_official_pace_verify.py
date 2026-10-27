"""Verify official Pace picks against ESPN finals (display ledger audit)."""

from __future__ import annotations

from sharp_scout.nba.score_model.official_pace import load_official_pace


def _grade_play(p: dict, *, home_score: int, away_score: int) -> str:
    margin = home_score - away_score
    total = home_score + away_score
    market = p.get("market")
    line = float(p.get("line") or 0)
    if market == "spread":
        side = p.get("side")
        spread_home = line if side == "home" else -line
        adj = margin + spread_home
        if adj == 0:
            return "push"
        picked_home = side == "home"
        home_covers = adj > 0
        return "win" if picked_home == home_covers else "loss"
    if market == "total":
        side = p.get("side")
        if total == line:
            return "push"
        over_hits = total > line
        return "win" if (side == "over") == over_hits else "loss"
    return "skip"


def test_official_results_match_espn():
    store = load_official_pace()
    for p in store.get("plays") or []:
        hs = int(p["espn_home_score"])
        aw = int(p["espn_away_score"])
        expected = _grade_play(p, home_score=hs, away_score=aw)
        assert expected == p["result"], f"{p['pick']} expected {expected} got {p['result']}"
