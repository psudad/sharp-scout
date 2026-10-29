"""Rest days + travel tags from ESPN finals schedule (backtest-only)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.kickoff import parse_kickoff_utc


def _arena_team(home: str, away: str, team: str) -> str:
    return home if team == home else away


def rest_days_between(prev_day: date | None, cur_day: date) -> int | None:
    if prev_day is None:
        return None
    return max(0, (cur_day - prev_day).days - 1)


def rest_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days == 0:
        return "0_b2b"
    if days == 1:
        return "1"
    if days == 2:
        return "2"
    return "3_plus"


def build_team_game_log(games: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for g in games:
        kick = parse_kickoff_utc(g.get("kickoff"))
        day = kickoff_date_et(kick)
        if kick is None or day is None:
            continue
        home, away = str(g["home"]), str(g["away"])
        rows.append({"kickoff": kick, "date_et": day, "home": home, "away": away})
    rows.sort(key=lambda r: r["kickoff"])

    log: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        for team in (r["home"], r["away"]):
            log.setdefault(team, []).append(
                {
                    "date_et": r["date_et"],
                    "kickoff": r["kickoff"],
                    "home": r["home"],
                    "away": r["away"],
                    "site": _arena_team(r["home"], r["away"], team),
                }
            )
    return log


def tag_game_rest_travel(
    *,
    home: str,
    away: str,
    kickoff: Any,
    team_log: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    kick_dt = parse_kickoff_utc(kickoff)
    day = kickoff_date_et(kick_dt)
    out: dict[str, Any] = {}
    for side, team in (("home", home), ("away", away)):
        hist = [h for h in (team_log.get(team) or []) if h["kickoff"] < kick_dt]
        prev = hist[-1] if hist else None
        rd = rest_days_between(prev["date_et"] if prev else None, day) if day else None
        cur_site = _arena_team(home, away, team)
        prev_site = prev["site"] if prev else None
        out[f"{side}_rest_days"] = rd
        out[f"{side}_rest_bucket"] = rest_bucket(rd)
        out[f"{side}_traveled"] = bool(prev_site and prev_site != cur_site)
    hr, ar = out.get("home_rest_days"), out.get("away_rest_days")
    out["either_b2b"] = hr == 0 or ar == 0
    out["both_b2b"] = hr == 0 and ar == 0
    out["rest_mismatch"] = (
        hr is not None
        and ar is not None
        and ((hr == 0 and ar >= 2) or (ar == 0 and hr >= 2) or abs(hr - ar) >= 3)
    )
    return out
