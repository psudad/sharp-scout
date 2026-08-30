"""Plain-English explanations for plays, splits, and stage picks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

STAGE_LABELS: dict[str, str] = {
    "model": "Model",
    "sharp": "Sharp line",
    "public": "Public tickets",
    "money": "Sharp money",
    "sharp_edge": "Money vs tickets",
    "rlm": "Reverse line move",
    "hybrid": "Full system",
}

STAGE_INTROS: dict[str, str] = {
    "model": "Our EPA ratings + Monte Carlo simulation favor",
    "sharp": "Pinnacle / sharp books lean toward",
    "public": "Most bet tickets are on",
    "money": "Most handle (dollars) is on",
    "sharp_edge": "Sharp money signal (handle minus tickets) points to",
    "rlm": "Line moved against the public toward",
    "hybrid": "Validated system play:",
}

# Short header labels on the pregame stage table → hover tooltip on the eye icon.
STAGE_COLUMN_TIPS: dict[str, str] = {
    "Mkt": "Spread, moneyline (ML), or total — one row per market per game.",
    "Model": "EPA ratings + Monte Carlo simulation — our independent lean before splits.",
    "Sharp": "Pinnacle / Betfair consensus — where sharp books price this market.",
    "Public": "Action Network ticket % — which side most bettors are taking.",
    "Money": "Action Network handle % — where the dollars are flowing.",
    "Diff": "Money minus tickets on a side; a ≥20% gap flags sharp-money interest.",
    "RLM": "Reverse line movement — the line moved against the public toward this side.",
    "Hybrid": "Full system pick — validated play when filters pass, else best model + market lean.",
}

# Summary stat cards on the board → hover tooltip on the eye icon next to the label.
BOARD_STAT_TIPS: dict[str, str] = {
    "sharp_vs_public": (
        "Games on the current slate where sharp books (Pinnacle no-vig) favor a different side "
        "than the public ticket majority on spread. Counts disagreement spots — not our bet record."
    ),
    "rlm_games": (
        "Games with reverse line movement: the line moved against where most tickets are, "
        "suggesting sharp money on the other side. Needs an opening line stored from an earlier run."
    ),
    "clv_avg_pts": "Average closing-line value in points vs the line we bet. Positive means we beat the close.",
    "clv_beat_pct": "Share of graded plays that beat the closing line (price or spread/total).",
    "clv_beat_record": "Win-loss count vs the closing line across graded plays — not the same as bet W-L.",
    "clv_n_plays": "Number of graded plays with a captured closing line (T-1h pre-kick snapshot).",
    "stage_ungraded": (
        "Stage picks still waiting on a final score — one per stage per game/market row. "
        "Drops after games finish and the settle step runs."
    ),
    "cfb_record": "Validated Sharp Plays only — our actual bets, not every stage pick on the slate.",
    "cfb_profit": "Net units won or lost on validated Sharp Plays (starting bankroll 100u).",
}

# Stage Records table — what each lens is and what its W-L counts.
STAGE_RECORD_TIPS: dict[str, str] = {
    "hybrid": (
        "Hybrid = our full system pick (spread, ML, or total) for that game. Uses validated "
        "edge when filters pass; otherwise the best model + market lean. The hybrid record "
        "grades every hybrid pick on the slate — not the same as Sharp Plays in the ledger."
    ),
    "model": (
        "Model = EPA power ratings + Monte Carlo simulation — our math-only lean before "
        "splits or tickets. Record = win rate if you bet the model's side on every graded row."
    ),
    "sharp": (
        "Sharp = Pinnacle / Betfair no-vig favorite on that market. Record = how often "
        "following sharp books would have won across all graded game/market rows."
    ),
    "public": (
        "Public = Action Network ticket-% majority (which side most bettors took). "
        "Record = win rate if you faded or followed the public on every graded row."
    ),
    "money": (
        "Money = Action Network handle-% majority (where the dollars went). "
        "Record = win rate if you bet the money side on every graded row."
    ),
    "sharp_edge": (
        "Sharp edge (Diff) = the side with the largest money-minus-tickets gap (≥20% flags "
        "sharp interest). Record = win rate betting that diff side every time."
    ),
    "rlm": (
        "RLM = reverse line movement — the side the line moved toward vs the public. "
        "Only graded when an opening line exists. Record = RLM-side win rate when available."
    ),
}

STAGE_RECORD_SECTION_NOTE = (
    "Each lens picks a side independently on every game (spread, ML, and total rows). "
    "Stage records currently grade spread + ML rows only (16 picks on an 8-game slate). "
    "The record shows how that lens would have performed if you bet every one of its picks — "
    "useful for comparing signals. This is not the same as validated Sharp Plays in the ledger."
)

HYBRID_LEANS_SECTION_NOTE = (
    "Hybrid leans are system ideas the model liked but did not post as Sharp Plays — "
    "usually because EV or split filters did not clear the bet bar. They appear in the "
    "hybrid stage scorecard (12-4) but are not in your ledger (1-2). "
    "Validated plays above are the only rows we actually bet."
)


def parse_kickoff(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str) and raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_kickoff_et(raw: Any) -> str:
    dt = parse_kickoff(raw)
    if dt is None:
        return "Time TBD"
    local = dt.astimezone(ET)
    return local.strftime("%a %b %-d, %-I:%M %p ET")


def format_kickoff_date_et(raw: Any) -> str:
    dt = parse_kickoff(raw)
    if dt is None:
        return "TBD"
    return dt.astimezone(ET).strftime("%a %b %-d")


def format_kickoff_time_et(raw: Any) -> str:
    dt = parse_kickoff(raw)
    if dt is None:
        return "TBD"
    return dt.astimezone(ET).strftime("%-I:%M %p ET")


def format_kickoff_compact(raw: Any) -> str:
    """Short kickoff for dense stage tables, e.g. Sat 12:00 PM."""
    dt = parse_kickoff(raw)
    if dt is None:
        return "TBD"
    return dt.astimezone(ET).strftime("%a %-I:%M %p")


def kickoff_sort_key(raw: Any) -> str:
    dt = parse_kickoff(raw)
    return dt.isoformat() if dt else "9999"


def side_team(play: dict[str, Any]) -> str:
    side = str(play.get("side") or "").lower()
    if side == "home":
        return str(play.get("home_team") or "HOME")
    if side == "away":
        return str(play.get("away_team") or "AWAY")
    return str(play.get("side") or "").upper()


def _market_label(market: str | None) -> str:
    return {"spreads": "spread", "totals": "total", "h2h": "moneyline"}.get(market or "", market or "bet")


def _line_phrase(play: dict[str, Any]) -> str:
    market = play.get("market")
    side = str(play.get("side") or "").lower()
    line = play.get("line")
    team = side_team(play)
    if market == "spreads" and line is not None:
        return f"{team} {float(line):+g}"
    if market == "totals" and line is not None:
        return f"{side.upper()} {line}"
    if market == "h2h":
        return f"{team} ML"
    return team


def format_play_rationale(play: dict[str, Any]) -> str:
    """Multi-line plain English for a play card."""
    lines: list[str] = []
    p_true = play.get("p_true")
    p_mkt = play.get("p_mkt")
    edge = play.get("edge")
    book = play.get("book") or "the book"
    pick = _line_phrase(play)
    mkt = _market_label(play.get("market"))

    if p_true is not None and p_mkt is not None and edge is not None:
        lines.append(
            f"We project {pick} on the {mkt} at {p_true * 100:.1f}% true probability "
            f"vs {p_mkt * 100:.1f}% implied at {book} — about {edge * 100:.1f}% expected value."
        )
    elif edge is not None:
        lines.append(f"Best price at {book}: {edge * 100:.1f}% edge on {pick} ({mkt}).")

    flags = play.get("flags") or {}
    notes = play.get("filter_notes") or []
    if not notes and play.get("rationale"):
        notes = [play["rationale"]]

    for note in notes:
        text = _translate_filter_note(str(note), play)
        if text and text not in lines:
            lines.append(text)

    if flags.get("money_split"):
        lines.append("Sharp money confirms this side (handle % well above ticket %).")
    if flags.get("rlm"):
        lines.append("Reverse line movement supports this side — line moved against the public.")
    if flags.get("steam"):
        lines.append("Steam move detected — the line jumped across multiple sharp books toward this side.")
    if flags.get("ev_ok") and not flags.get("money_split") and not flags.get("rlm"):
        if any("splits incomplete" in str(n).lower() for n in notes):
            lines.append(
                "Money/ticket splits were not available — add ACTION_NETWORK_COOKIE for Phase 4 confirmation."
            )

    return "\n".join(lines) if lines else "No rationale recorded."


def _translate_filter_note(note: str, play: dict[str, Any]) -> str:
    n = note.strip()
    if not n:
        return ""

    if n.startswith("EV="):
        return ""  # covered in opening line

    if "money-ticket gap" in n:
        m = re.search(
            r"money-ticket gap ([+-]?\d+%) on (\w+).*money=([\d.]+%).*tickets=([\d.]+%)",
            n,
        )
        if m:
            gap, side, money, tickets = m.groups()
            team = side_team(play) if side in ("home", "away") and play.get("side") == side else side
            return (
                f"On this side, {money} of handle vs {tickets} of tickets "
                f"({gap} handle-minus-tickets gap) — sharp money signal."
            )
        if "only" in n and "need" in n:
            return "Handle did not exceed tickets enough on this side to confirm sharp money."
        return n

    if n.startswith("RLM:"):
        return n.replace("RLM:", "Reverse line movement:").strip()

    if "no open/current line" in n:
        return (
            "No opening line stored yet for RLM. The first pipeline run of the week "
            "records the current line as the open; later runs compare movement against it."
        )

    if "no Action Network" in n or "splits incomplete" in n:
        return (
            "Action Network money % missing — log in to Pro and set ACTION_NETWORK_COOKIE "
            "in GitHub secrets for full split data."
        )

    if "edge lacks RLM or money" in n:
        return "Did not pass Phase 4: needs either sharp-money or reverse-line confirmation."

    if "no RLM" in n or "line flat" in n:
        return "No clear reverse line movement on this market."

    return n


def format_edge_rationale(signal: dict[str, Any]) -> str:
    return format_play_rationale(signal)


def describe_splits_board(board: dict[str, Any]) -> str:
    """Plain English summary of which side sharp money favors."""
    if not board.get("available"):
        reason = board.get("reason") or "No Action Network data for this game."
        if "cookie" not in reason.lower():
            reason += " Set ACTION_NETWORK_COOKIE if money % is locked."
        return reason

    parts: list[str] = []
    markets = board.get("markets") or {}
    for mkey, mdata in markets.items():
        edge = (mdata.get("sharp_edge") or {})
        if edge.get("available"):
            team = edge.get("team") or edge.get("side")
            diff = edge.get("diff_pct")
            diff_s = f"{diff * 100:+.0f}%" if diff is not None else "—"
            parts.append(
                f"{mkey.capitalize()}: sharp money leans {team} "
                f"(handle minus tickets {diff_s} on that side)."
            )
        else:
            sides = mdata.get("sides") or {}
            readable = []
            for side_key, row in sides.items():
                t = row.get("tickets_pct")
                m = row.get("money_pct")
                if t is None or m is None:
                    continue
                label = row.get("label") or side_key
                readable.append(f"{label}: {t * 100:.0f}% tickets / {m * 100:.0f}% money")
            if readable:
                parts.append(f"{mkey.capitalize()}: " + "; ".join(readable) + ".")
            else:
                parts.append(f"{mkey.capitalize()}: ticket and money % not available.")

    return " ".join(parts) if parts else "Split data loaded but no clear sharp-money lean."


def describe_stage_pick(stage: str, pick: dict[str, Any], home: str, away: str) -> str:
    if not pick.get("available"):
        reason = pick.get("reason") or "Not available for this game."
        return reason

    team = pick.get("team") or pick.get("side") or "—"
    intro = STAGE_INTROS.get(stage, STAGE_LABELS.get(stage, stage))
    line = pick.get("line")
    line_s = ""
    if line is not None and stage in ("model", "sharp", "public", "money", "rlm"):
        line_s = f" (line {float(line):+g})"

    conf = pick.get("confidence")
    conf_s = f" · {conf * 100:.0f}% confidence" if conf is not None else ""

    if stage == "model":
        spread = pick.get("line")
        if spread is not None:
            return (
                f"{intro} {team}{line_s}. Model spread (home) is {float(spread):+.2f} "
                f"(negative = home favored).{conf_s}"
            )
    if stage == "hybrid" and "validated" in str(pick.get("reason") or ""):
        return f"{intro} {team}{line_s}. {pick.get('reason')}{conf_s}"

    detail = pick.get("reason") or ""
    if detail and detail != team:
        return f"{intro} {team}{line_s}. {detail}{conf_s}"
    return f"{intro} {team}{line_s}{conf_s}"


def _signal_group_key(signal: dict[str, Any]) -> tuple[Any, ...]:
    """Group key for one actionable play (alternate lines collapse to one)."""
    market = signal.get("market")
    if signal.get("player_name") or str(market or "").startswith("player_"):
        return (
            signal.get("event_id"),
            signal.get("player_name"),
            market,
            signal.get("side"),
            signal.get("line"),
        )
    return (
        signal.get("event_id"),
        market,
        signal.get("side"),
    )


def _signal_rank(signal: dict[str, Any]) -> tuple[float, float, float]:
    """Sort key: highest EV, then better spread line, then better price."""
    edge = float(signal.get("edge") or 0)
    price = float(signal.get("price") or -110)
    line = signal.get("line")
    line_bonus = 0.0
    if signal.get("market") == "spreads" and line is not None:
        side = str(signal.get("side") or "").lower()
        lv = float(line)
        if side == "home" and lv > 0:
            line_bonus = lv * 0.001
        elif side == "away" and lv < 0:
            line_bonus = abs(lv) * 0.001
    return (edge, line_bonus, price)


def collapse_best_signals(
    signals: list[dict[str, Any]],
    *,
    only_passed: bool = False,
) -> list[dict[str, Any]]:
    """One best play per game/market/side (alternate lines collapsed)."""
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for s in signals:
        if only_passed and not s.get("filter_passed"):
            continue
        key = _signal_group_key(s)
        prev = best.get(key)
        if prev is None or _signal_rank(s) > _signal_rank(prev):
            best[key] = s
    return sorted(best.values(), key=lambda x: -_signal_rank(x)[0])
