"""Graded play record for a single Eastern game date (yesterday box on boards)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from sharp_scout.nba.slate_et import kickoff_date_et
from sharp_scout.utils.slate import ET

KICKOFF_FIELDS = ("kickoff", "commence_time", "tip")


def yesterday_et() -> date:
    return datetime.now(ET).date() - timedelta(days=1)


def play_kickoff_et_date(play: dict[str, Any]) -> date | None:
    raw = next((play.get(k) for k in KICKOFF_FIELDS if play.get(k)), None)
    return kickoff_date_et(raw)


def play_et_calendar_date(play: dict[str, Any]) -> date | None:
    raw = play.get("date_et")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    return play_kickoff_et_date(play)


def graded_status(play: dict[str, Any]) -> str:
    return str(play.get("status") or play.get("result") or "").lower()


def filter_graded_on_et_day(
    plays: list[dict[str, Any]],
    day: date,
    *,
    include: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in plays:
        if play_et_calendar_date(p) != day:
            continue
        st = graded_status(p)
        if st not in ("win", "loss", "push"):
            continue
        if include and not include(p):
            continue
        out.append(p)
    return out


def summarize_graded_plays(plays: list[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = pushes = 0
    pnl = 0.0
    for p in plays:
        st = graded_status(p)
        if st == "win":
            wins += 1
        elif st == "loss":
            losses += 1
        elif st == "push":
            pushes += 1
        if p.get("pnl_units") is not None:
            pnl += float(p["pnl_units"])
        elif st == "win":
            pnl += float(p.get("units") or 1.0)
        elif st == "loss":
            pnl -= float(p.get("units") or 1.0)
    decided = wins + losses
    record = f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")
    if not plays:
        record = "—"
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record": record,
        "pnl_units": round(pnl, 2),
        "win_pct": (wins / decided) if decided else None,
        "n": len(plays),
    }


def summarize_yesterday(
    plays: list[dict[str, Any]],
    *,
    day: date | None = None,
    include: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    day = day or yesterday_et()
    subset = filter_graded_on_et_day(plays, day, include=include)
    summary = summarize_graded_plays(subset)
    summary["day"] = day.isoformat()
    summary["day_label"] = day.strftime("%a %b %-d")
    return summary


def format_yesterday_stat_value(summary: dict[str, Any]) -> str:
    if not summary.get("n"):
        return "—"
    rec = summary["record"]
    pnl = float(summary.get("pnl_units") or 0)
    pnl_s = f"{pnl:+.2f}u"
    return f"{rec} ({pnl_s})"
