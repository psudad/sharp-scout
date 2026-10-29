"""Public GitHub Pages slice for NBA shadow / paper-trading (testing only)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from sharp_scout.config import ROOT, get_settings
from sharp_scout.copy.explain import format_kickoff_compact, format_kickoff_et, kickoff_sort_key
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.schedule_guard import NBA_SCAN_SCHEDULE_LABEL, next_nba_scan_et
from sharp_scout.nba.slate_et import (
    format_et_slate_day_label,
    format_kickoff_day_time_et,
    group_items_by_kickoff_et_date,
    kickoff_date_et,
    upcoming_slate_items,
)
from sharp_scout.utils.slate import ET, parse_commence

DOCS_DIR = ROOT / "docs"
logger = logging.getLogger(__name__)

NO_LIVE_SCAN_MESSAGE = (
    "No live NBA scan yet. Test plays will appear after the next scan."
)

NBA_PROP_LABELS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "3PM",
    "player_points_rebounds_assists": "PRA",
}

NBA_BOOK_LABELS = {
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
}

# Matches score-model paper grading bucket ge_3 in summarize_score_paper (display only).
SCORE_MODELING_MIN_EDGE_PT = 3.0
PACE_LEAN_MIN_EDGE_PT = 1.5
PACE_WATCH_LIST_LABEL = "Watch List"
PACE_WATCH_LIST_NOTE = (
    "Below the official ≥3 pt Pace bar — tracking only, not part of the official record."
)


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _price(p: Any) -> str:
    try:
        n = float(p)
    except (TypeError, ValueError):
        return "—"
    return f"+{int(round(n))}" if n > 0 else str(int(round(n)))


def _pct(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v * 100:.1f}%"


def _book_label(book: str | None) -> str:
    if not book:
        return "—"
    return NBA_BOOK_LABELS.get(str(book).lower(), str(book).replace("_", " ").title())


def _bet_type_label(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        market = str(play.get("market") or "prop")
        return NBA_PROP_LABELS.get(market, market.replace("player_", "").replace("_", " ").title())
    market = str(play.get("market") or "side")
    if market == "spreads":
        return "Spreads"
    if market == "totals":
        return "Totals"
    return market.title()


def _game_pick(play: dict[str, Any]) -> str:
    side = str(play.get("side") or "").lower()
    line = play.get("line")
    market = str(play.get("market") or "")
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    if market == "spreads":
        team = away if side == "away" else home
        if isinstance(line, (int, float)):
            sign = "+" if float(line) > 0 else ""
            return f"{team} {sign}{line:g}"
        return team
    if market == "totals":
        label = "Over" if side == "over" else "Under"
        if isinstance(line, (int, float)):
            return f"{label} {line:g}"
        return label
    return side.title()


def _prop_pick(play: dict[str, Any]) -> str:
    side = str(play.get("side") or "").title()
    line = play.get("line")
    market = NBA_PROP_LABELS.get(str(play.get("market")), "Prop")
    if isinstance(line, (int, float)):
        return f"{side[0]} {line:g} {market}"
    return f"{side} {market}"


def _possible_lean_line(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        pick = _prop_pick(play)
    else:
        pick = _game_pick(play)
    book = _book_label(play.get("book"))
    price = _price(play.get("price"))
    return f"After more testing, we'd pick: {pick} ({book} {price})"


def _model_alignment_tag(play: dict[str, Any]) -> str:
    al = str(play.get("model_alignment") or "").lower()
    if al == "agree":
        return '<span class="nba-model-tag nba-model-agree">Agrees</span>'
    if al == "disagree":
        return '<span class="nba-model-tag nba-model-disagree">Disagrees</span>'
    if al == "neutral":
        return '<span class="nba-model-tag nba-model-neutral">Neutral</span>'
    return '<span class="nba-model-tag">—</span>'


def _sharp_money_tag(play: dict[str, Any]) -> str:
    tag = str(play.get("sharp_money_tag") or "").lower()
    if tag == "with_sharps":
        return '<span class="nba-sharp-tag nba-sharp-with">With sharps</span>'
    if tag == "against_sharps":
        return '<span class="nba-sharp-tag nba-sharp-against">Against sharps</span>'
    if tag == "no_signal":
        return '<span class="nba-sharp-tag nba-sharp-none">No signal</span>'
    if tag == "no_data":
        return '<span class="nba-sharp-tag nba-sharp-nodata">No data</span>'
    return '<span class="nba-sharp-tag">—</span>'


def _model_sharp_tags(play: dict[str, Any]) -> str:
    return (
        f'<span class="nba-tag-row">{_model_alignment_tag(play)}{_sharp_money_tag(play)}</span>'
    )


def _format_model_spread_pick(home: str, away: str, spread_home: float, margin_edge: float) -> str:
    if margin_edge > 0:
        team, line = home, float(spread_home)
    else:
        team, line = away, -float(spread_home)
    sign = "+" if line > 0 else ""
    return f"{team} {sign}{line:g}"


def _edge_candidates(
    *,
    home: str,
    away: str,
    game: str,
    margin: float,
    total: float,
    cs: float | None,
    ct: float | None,
    min_edge: float,
    label_prefix: str = "",
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if cs is not None:
        margin_edge = margin + float(cs)
        if abs(margin_edge) >= min_edge:
            pick = _format_model_spread_pick(home, away, float(cs), margin_edge)
            candidates.append(
                {
                    "kind": "spread",
                    "gap": abs(margin_edge),
                    "signed_gap": margin_edge,
                    "title": pick,
                    "model_line": f"{label_prefix}Proj margin {margin:+.1f}",
                    "consensus_line": f"Consensus {float(cs):+.1f}",
                }
            )
    if ct is not None:
        total_edge = total - float(ct)
        if abs(total_edge) >= min_edge:
            side = "Over" if total_edge > 0 else "Under"
            pick = f"{side} {float(ct):g}"
            candidates.append(
                {
                    "kind": "total",
                    "gap": abs(total_edge),
                    "signed_gap": total_edge,
                    "title": f"{game}: {pick}",
                    "model_line": f"{label_prefix}Proj total {total:.1f}",
                    "consensus_line": f"Consensus {float(ct):g}",
                }
            )
    return candidates


def _qualifies_play(candidates: list[dict[str, Any]]) -> bool:
    return bool(candidates)


def _adj_candidate_for_raw(
    raw: dict[str, Any],
    adj_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Injury-adj candidate on the same market and side as a raw-qualified play."""
    for adj in adj_candidates:
        if adj.get("kind") != raw.get("kind"):
            continue
        if float(raw.get("signed_gap") or 0) * float(adj.get("signed_gap") or 0) <= 0:
            continue
        return adj
    return None


def _raw_gated_play_candidates(
    raw_candidates: list[dict[str, Any]],
    adj_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Raw gap creates eligibility; injury adj may veto (no adj candidate) but never create."""
    out: list[dict[str, Any]] = []
    for raw in raw_candidates:
        adj = _adj_candidate_for_raw(raw, adj_candidates)
        if adj is None:
            continue
        merged = dict(adj)
        merged["raw_signed_gap"] = raw.get("signed_gap")
        merged["raw_model_line"] = raw.get("model_line")
        out.append(merged)
    return out


def projected_team_scores(
    margin: float,
    total: float,
) -> tuple[float, float]:
    """Home/away points from model margin (home − away) and game total."""
    home_pts = (float(total) + float(margin)) / 2.0
    away_pts = (float(total) - float(margin)) / 2.0
    return round(home_pts, 1), round(away_pts, 1)


def format_projected_scores_line(
    *,
    home: str,
    away: str,
    margin: float,
    total: float,
    inj_margin: float | None = None,
    inj_total: float | None = None,
) -> str:
    h_raw, a_raw = projected_team_scores(margin, total)
    base = f"Projected: {home} {h_raw:g}, {away} {a_raw:g}"
    if inj_margin is None or inj_total is None:
        return base
    h_inj, a_inj = projected_team_scores(inj_margin, inj_total)
    if h_inj == h_raw and a_inj == a_raw:
        return base
    return f"{base} | after injuries: {home} {h_inj:g}, {away} {a_inj:g}"


def spread_gap_plain_english(
    *,
    home: str,
    margin: float,
    consensus_spread_home: float,
    min_edge: float = SCORE_MODELING_MIN_EDGE_PT,
) -> str:
    """One-line spread gap vs consensus (home margin = −spread)."""
    market_margin = -float(consensus_spread_home)
    model_margin = float(margin)
    gap = model_margin - market_margin
    return (
        f"Model has {home} by {model_margin:.1f}; market says {home} by {market_margin:.1f}; "
        f"gap {abs(gap):.1f} pts. A play needs a gap of {min_edge:g}+ pts."
    )


def total_gap_plain_english(
    *,
    total: float,
    consensus_total: float,
    min_edge: float = SCORE_MODELING_MIN_EDGE_PT,
) -> str:
    gap = float(total) - float(consensus_total)
    side = "Over" if gap > 0 else "Under"
    return (
        f"Model total {float(total):.1f}; market {float(consensus_total):g}; "
        f"gap {abs(gap):.1f} pts ({side}). A play needs a gap of {min_edge:g}+ pts."
    )


def score_modeling_display_plays(
    rows: list[dict[str, Any]],
    *,
    min_edge: float = SCORE_MODELING_MIN_EDGE_PT,
    max_edge: float | None = None,
    include_injury_watch: bool = False,
) -> list[dict[str, Any]]:
    """Display cards per game where injury-adj (or raw) gap vs consensus is in [min_edge, max_edge)."""
    from sharp_scout.nba.score_model.injury_adjust import format_absence_line
    from sharp_scout.nba.slate_et import kickoff_date_et

    today_et = datetime.now(ET).date()
    out: list[dict[str, Any]] = []
    for r in rows:
        lines = r.get("lines") or {}
        cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
        margin = float(r.get("margin") or 0)
        total = float(r.get("total") or 0)
        inj_margin = float(r.get("injury_margin") if r.get("injury_margin") is not None else margin)
        inj_total = float(r.get("injury_total") if r.get("injury_total") is not None else total)
        away = str(r.get("away") or "")
        home = str(r.get("home") or "")
        game = f"{away} @ {home}"
        raw_candidates = _edge_candidates(
            home=home,
            away=away,
            game=game,
            margin=margin,
            total=total,
            cs=cs,
            ct=ct,
            min_edge=min_edge,
        )
        adj_candidates = _edge_candidates(
            home=home,
            away=away,
            game=game,
            margin=inj_margin,
            total=inj_total,
            cs=cs,
            ct=ct,
            min_edge=min_edge,
            label_prefix="Injury-adj ",
        )
        absence_lines: list[str] = []
        for team, key in ((home, "home_absences"), (away, "away_absences")):
            for row in r.get(key) or []:
                if row.get("kind") in ("return", "absence"):
                    absence_lines.append(format_absence_line(team, row))
        for team, key in ((home, "home_excluded"), (away, "away_excluded")):
            for row in r.get(key) or []:
                absence_lines.append(format_absence_line(team, row))

        projected_line = format_projected_scores_line(
            home=home,
            away=away,
            margin=margin,
            total=total,
            inj_margin=inj_margin,
            inj_total=inj_total,
        )

        candidates = _raw_gated_play_candidates(raw_candidates, adj_candidates)
        if not candidates:
            if (
                not raw_candidates
                and include_injury_watch
                and absence_lines
                and kickoff_date_et(r.get("kickoff")) == today_et
            ):
                market = ""
                if cs is not None:
                    market = f"Consensus {float(cs):+.1f}"
                elif ct is not None:
                    market = f"Consensus total {float(ct):g}"
                else:
                    market = "Awaiting market line from next scan"
                out.append(
                    {
                        "game": game,
                        "kickoff": r.get("kickoff"),
                        "gap": 0.0,
                        "title": game,
                        "kind": "injury_watch",
                        "model_line": f"Injury-adj margin {inj_margin:+.1f} · total {inj_total:.1f}",
                        "consensus_line": market,
                        "signed_gap": 0.0,
                        "raw_signed_gap": None,
                        "raw_model_line": f"Raw margin {margin:+.1f} · total {total:.1f}",
                        "injury_model_line": f"Injury-adj margin {inj_margin:+.1f} · total {inj_total:.1f}",
                        "projected_scores_line": projected_line,
                        "gap_explain": "",
                        "secondary": [],
                        "absence_lines": absence_lines,
                        "injury_news_after_line": bool(r.get("injury_news_after_line")),
                        "injury_play_flip": False,
                        "injury_watch_only": True,
                    }
                )
            continue
        primary = max(candidates, key=lambda c: c["gap"])
        if float(primary.get("gap") or 0) < min_edge:
            continue
        if max_edge is not None and float(primary.get("gap") or 0) >= max_edge:
            continue
        raw_gap = primary.get("raw_signed_gap")
        raw_primary = (
            max(raw_candidates, key=lambda c: c["gap"])
            if raw_candidates and raw_gap is not None
            else None
        )
        secondary = [c for c in candidates if c is not primary]
        adj_gap = primary["signed_gap"]
        flip = False
        if raw_primary and _qualifies_play(raw_candidates) and not _qualifies_play(adj_candidates):
            flip = True
        elif raw_primary and raw_primary.get("kind") == primary.get("kind"):
            if (raw_gap or 0) * adj_gap < 0 and abs(adj_gap) >= min_edge:
                flip = True
        gap_explain = ""
        if primary.get("kind") == "spread" and cs is not None:
            gap_explain = spread_gap_plain_english(
                home=home,
                margin=inj_margin,
                consensus_spread_home=float(cs),
                min_edge=min_edge,
            )
        elif primary.get("kind") == "total" and ct is not None:
            gap_explain = total_gap_plain_english(
                total=inj_total,
                consensus_total=float(ct),
                min_edge=min_edge,
            )
        out.append(
            {
                "game": game,
                "kickoff": r.get("kickoff"),
                "gap": primary["gap"],
                "title": primary["title"],
                "kind": primary["kind"],
                "model_line": primary["model_line"],
                "consensus_line": primary["consensus_line"],
                "signed_gap": primary["signed_gap"],
                "raw_signed_gap": raw_gap,
                "raw_model_line": primary.get("raw_model_line")
                or (raw_primary["model_line"] if raw_primary else f"Proj margin {margin:+.1f}"),
                "injury_model_line": primary["model_line"],
                "projected_scores_line": projected_line,
                "gap_explain": gap_explain,
                "secondary": secondary,
                "absence_lines": absence_lines,
                "injury_news_after_line": bool(r.get("injury_news_after_line")),
                "injury_play_flip": flip,
            }
        )
    out.sort(key=lambda x: float(x.get("gap") or 0), reverse=True)
    return out


def score_modeling_display_leans(
    rows: list[dict[str, Any]],
    *,
    min_edge: float = PACE_LEAN_MIN_EDGE_PT,
    max_edge: float = SCORE_MODELING_MIN_EDGE_PT,
) -> list[dict[str, Any]]:
    """Near-miss Pace of Play spots: gap in [min_edge, max_edge) vs consensus."""
    return score_modeling_display_plays(
        rows,
        min_edge=min_edge,
        max_edge=max_edge,
        include_injury_watch=False,
    )


def _score_modeling_record_label(summary: dict[str, Any] | None) -> str:
    if not summary or not int(summary.get("n_graded") or 0):
        return ""
    parts: list[str] = []
    ats = (summary.get("ats_vs_close") or {}).get("ge_3") or {}
    ou = (summary.get("ou_vs_close") or {}).get("ge_3") or {}
    for label, row in (("Spread", ats), ("Total", ou)):
        w, l, p = int(row.get("wins") or 0), int(row.get("losses") or 0), int(row.get("pushes") or 0)
        if w + l + p:
            rec = f"{w}-{l}" + (f"-{p}" if p else "")
            parts.append(f"{label} {rec}")
    return " · ".join(parts)


def _win_pct(w: int, l: int, p: int) -> str:
    denom = w + l
    if not denom:
        return "—"
    return f"{100.0 * w / denom:.1f}%"


def _record_str(w: int, l: int, p: int) -> str:
    rec = f"{w}-{l}"
    if p:
        rec += f"-{p}"
    return rec


def _is_sharp_game_line_play(play: dict[str, Any]) -> bool:
    if play.get("play_type") == "prop":
        return False
    market = str(play.get("market") or "")
    return market in ("spreads", "totals")


def _sharp_scout_record_summary(
    ledger: dict[str, Any] | None,
    *,
    game_lines_only: bool = False,
) -> dict[str, Any]:
    from sharp_scout.nba.slate_et import kickoff_date_et

    plays = (ledger or {}).get("plays") or []
    buckets = {
        "all": {"w": 0, "l": 0, "p": 0, "units": 0.0},
        "spreads": {"w": 0, "l": 0, "p": 0, "units": 0.0},
        "totals": {"w": 0, "l": 0, "p": 0, "units": 0.0},
        "prop": {"w": 0, "l": 0, "p": 0, "units": 0.0},
    }

    def bump(key: str, st: str, pnl: float | None) -> None:
        b = buckets[key]
        if st == "win":
            b["w"] += 1
        elif st == "loss":
            b["l"] += 1
        elif st == "push":
            b["p"] += 1
        if pnl is not None:
            b["units"] += float(pnl)

    dates: list[str] = []
    for p in plays:
        st = str(p.get("status") or "").lower()
        if st not in ("win", "loss", "push"):
            continue
        if game_lines_only and not _is_sharp_game_line_play(p):
            continue
        pnl = p.get("pnl_units")
        bump("all", st, pnl if pnl is not None else None)
        day = kickoff_date_et(p.get("kickoff"))
        if day:
            dates.append(day.isoformat())
        if p.get("play_type") == "prop":
            bump("prop", st, pnl if pnl is not None else None)
        elif str(p.get("market") or "") == "totals":
            bump("totals", st, pnl if pnl is not None else None)
        elif str(p.get("market") or "") == "spreads":
            bump("spreads", st, pnl if pnl is not None else None)

    all_b = buckets["all"]
    ds = sorted(set(dates))
    date_range = ds[0] if len(ds) == 1 else (f"{ds[0]} – {ds[-1]}" if ds else "")
    return {
        "record": _record_str(all_b["w"], all_b["l"], all_b["p"]),
        "wins": all_b["w"],
        "losses": all_b["l"],
        "pushes": all_b["p"],
        "units": round(all_b["units"], 2),
        "win_pct": _win_pct(all_b["w"], all_b["l"], all_b["p"]),
        "spreads": buckets["spreads"],
        "totals": buckets["totals"],
        "props": buckets["prop"],
        "date_range_et": date_range,
    }


def _signals_for_today_et(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Signals for today's ET slate only (excludes finished prior-night games)."""
    today_et = datetime.now(ET).date()
    return [s for s in signals if kickoff_date_et(s.get("kickoff")) == today_et]


def _slate_reference_date(now: datetime | None = None) -> date:
    return (now or datetime.now(ET)).astimezone(ET).date()


def _play_tier_badge_label(kickoff: Any, *, reference: date | None = None) -> str:
    day = kickoff_date_et(kickoff)
    ref = reference or _slate_reference_date()
    if day == ref:
        return "Tonight's play"
    if day == ref + timedelta(days=1):
        return "Tomorrow's play"
    return "Slate play"


def _render_et_date_grouped_cards(
    items: list[dict[str, Any]],
    *,
    kickoff_key: str = "kickoff",
    render_one,
    reference: date | None = None,
) -> str:
    if not items:
        return ""
    ref = reference or _slate_reference_date()
    groups = group_items_by_kickoff_et_date(items, kickoff_key=kickoff_key, reference=ref)
    chunks: list[str] = []
    for _day, label, group in groups:
        cards = "\n".join(render_one(item) for item in group)
        chunks.append(
            f'<div class="nba-day-group">'
            f'<h3 class="nba-day-heading">{_esc(label)} '
            f'<span class="nba-day-count">({len(group)})</span></h3>'
            f'<div class="nba-pick-cards">{cards}</div></div>'
        )
    return "\n".join(chunks)


def _score_rows_missing_lines(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for r in rows:
        lines = r.get("lines") or {}
        if lines.get("consensus_spread_home") is None and lines.get("consensus_total") is None:
            return True
    return False


def _render_waiting_for_lines(next_scan: str) -> str:
    return (
        f'<p class="nba-picks-empty nba-picks-empty-soft" role="status">'
        f"Waiting for today&apos;s lines from the odds scan (next scan {_esc(next_scan)}).</p>"
    )


def _pace_record_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    row3s = (summary.get("ats_vs_close") or {}).get("ge_3") or {}
    row3t = (summary.get("ou_vs_close") or {}).get("ge_3") or {}
    row3si = (summary.get("ats_vs_close_injury") or {}).get("ge_3") or {}
    row3ti = (summary.get("ou_vs_close_injury") or {}).get("ge_3") or {}

    def combine(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        w = int(a.get("wins") or 0) + int(b.get("wins") or 0)
        l = int(a.get("losses") or 0) + int(b.get("losses") or 0)
        p = int(a.get("pushes") or 0) + int(b.get("pushes") or 0)
        units = float(a.get("units_at_110") or 0) + float(b.get("units_at_110") or 0)
        return {"w": w, "l": l, "p": p, "units": round(units, 2)}

    raw = combine(row3s, row3t)
    inj = combine(row3si, row3ti)
    return {
        "raw": {
            "record": _record_str(raw["w"], raw["l"], raw["p"]),
            "win_pct": _win_pct(raw["w"], raw["l"], raw["p"]),
            "units": raw["units"],
            "spreads": row3s,
            "totals": row3t,
        },
        "injury": {
            "record": _record_str(inj["w"], inj["l"], inj["p"]),
            "win_pct": _win_pct(inj["w"], inj["l"], inj["p"]),
            "units": inj["units"],
            "spreads": row3si,
            "totals": row3ti,
        },
    }


def _pace_pick_rows_from_store(store: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Graded Pace of Play paper rows (≥3 pt at tip), raw + injury results."""
    from sharp_scout.nba.score_model.paper import (
        _ats_units,
        _game_excluded,
        _grade_ats_margin,
        _grade_ou,
    )

    out: list[dict[str, Any]] = []
    for g in store.get("games") or [] if store else []:
        if _game_excluded(g) or not g.get("graded"):
            continue
        gr = g["graded"]
        frozen = g.get("frozen") or {}
        snap = frozen.get("snapshot") or (g.get("scans") or [{}])[-1]
        lines = snap.get("lines") or {}
        cs, ct = gr.get("close_spread_home"), gr.get("close_total")
        pm = float(snap.get("margin") or 0)
        pt = float(snap.get("total") or 0)
        pm_i = float(snap.get("injury_margin") if snap.get("injury_margin") is not None else pm)
        pt_i = float(snap.get("injury_total") if snap.get("injury_total") is not None else pt)
        home, away = str(g.get("home") or ""), str(g.get("away") or "")
        game = f"{away} @ {home}"
        picks: list[dict[str, Any]] = []
        if cs is not None:
            edge = pm_i + float(cs)
            if abs(edge) >= SCORE_MODELING_MIN_EDGE_PT:
                pick = _format_model_spread_pick(home, away, float(cs), edge)
                picks.append({"kind": "spread", "pick": pick, "line": float(cs), "gap": abs(edge)})
        if ct is not None:
            edge_t = pt_i - float(ct)
            if abs(edge_t) >= SCORE_MODELING_MIN_EDGE_PT:
                side = "Over" if edge_t > 0 else "Under"
                picks.append(
                    {
                        "kind": "total",
                        "pick": f"{game}: {side} {float(ct):g}",
                        "line": float(ct),
                        "gap": abs(edge_t),
                    }
                )
        if not picks:
            continue
        primary = max(picks, key=lambda x: x["gap"])
        raw_res = inj_res = None
        if primary["kind"] == "spread" and cs is not None:
            raw_res = _grade_ats_margin(
                gr["actual_margin"], cs, min_edge=SCORE_MODELING_MIN_EDGE_PT, proj_margin=pm
            )
            inj_res = _grade_ats_margin(
                gr["actual_margin"], cs, min_edge=SCORE_MODELING_MIN_EDGE_PT, proj_margin=pm_i
            )
        elif primary["kind"] == "total" and ct is not None:
            raw_res = _grade_ou(
                gr["actual_total"], ct, min_edge=SCORE_MODELING_MIN_EDGE_PT, proj_total=pt
            )
            inj_res = _grade_ou(
                gr["actual_total"], ct, min_edge=SCORE_MODELING_MIN_EDGE_PT, proj_total=pt_i
            )
        if raw_res is None and inj_res is None:
            continue
        out.append(
            {
                "kickoff": g.get("kickoff"),
                "game": game,
                "market": primary["kind"],
                "pick": primary["pick"],
                "line": primary["line"],
                "gap": primary["gap"],
                "result_raw": raw_res,
                "result_injury": inj_res,
                "units_raw": _ats_units(
                    1 if raw_res == "win" else 0,
                    1 if raw_res == "loss" else 0,
                    1 if raw_res == "push" else 0,
                )
                if raw_res
                else None,
                "units_injury": _ats_units(
                    1 if inj_res == "win" else 0,
                    1 if inj_res == "loss" else 0,
                    1 if inj_res == "push" else 0,
                )
                if inj_res
                else None,
            }
        )
    out.sort(key=lambda r: r.get("kickoff") or "", reverse=True)
    return out


def _group_rows_by_et_day(rows: list[dict[str, Any]], key: str = "kickoff") -> list[tuple[str, list]]:
    from sharp_scout.nba.slate_et import kickoff_date_et

    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        day = kickoff_date_et(r.get(key))
        label = day.isoformat() if day else "Unknown"
        buckets.setdefault(label, []).append(r)
    return sorted(buckets.items(), key=lambda x: x[0], reverse=True)


def _render_stat_grid(items: list[tuple[str, str]], *, extra_cls: str = "") -> str:
    if not items:
        return ""
    cards = []
    for val, lbl in items:
        cls = "stat-val"
        if val.startswith("+") and "u" in val:
            cls += " pos"
        elif val.startswith("-") and "u" in val:
            cls += " neg"
        cards.append(
            f'<div class="stat-card"><div class="{cls}">{_esc(val)}</div>'
            f'<div class="stat-label">{_esc(lbl)}</div></div>'
        )
    return f'<div class="summary-grid {extra_cls}">' + "".join(cards) + "</div>"


def _render_compact_record(
    *,
    record: str,
    win_pct: str,
    units: float,
    label: str = "",
) -> str:
    units_s = f"{float(units):+.2f}u"
    lbl = (
        f'<span class="nba-rec-chip-label">{_esc(label)}</span>'
        if label
        else ""
    )
    return (
        f'<div class="nba-rec-chip">{lbl}'
        f'<strong class="nba-rec-chip-record">{_esc(record)}</strong>'
        f'<span class="nba-rec-chip-meta">{_esc(win_pct)} win · {_esc(units_s)}</span>'
        f"</div>"
    )


def _price_edge_card_title(play: dict[str, Any]) -> str:
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    if play.get("play_type") == "prop":
        player = str(play.get("player_name") or "").strip()
        pick = _prop_pick(play)
        return f"{player}: {pick}" if player else f"{away} @ {home}: {pick}"
    pick = _game_pick(play)
    market = str(play.get("market") or "")
    if market == "spreads":
        return pick
    return f"{away} @ {home}: {pick}"


def _render_nba_play_card(
    play: dict[str, Any],
    *,
    badge: str,
    badge_cls: str,
    card_cls: str,
    show_stake: bool = True,
    reference: date | None = None,
) -> str:
    settings = get_settings()
    unit_d = float(settings.nba_unit_dollars)
    kick = format_kickoff_et(play.get("kickoff"))
    day_time = format_kickoff_day_time_et(play.get("kickoff"))
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    title = _price_edge_card_title(play)
    book = _book_label(play.get("book"))
    price = _price(play.get("price"))
    line = play.get("line")
    line_s = f"{float(line):g}" if isinstance(line, (int, float)) else "—"
    units = play.get("units")
    units_f = float(units) if isinstance(units, (int, float)) else None
    units_s = f"{units_f:.2f}u" if units_f is not None else "—"
    stake_s = f"${units_f * unit_d:.0f}" if units_f is not None else "—"
    edge = play.get("edge")
    edge_s = _pct(edge)
    fair = play.get("p_true") if play.get("p_true") is not None else play.get("p_fair")
    fair_s = _pct(fair)
    sub_parts = [f"{away} @ {home}", _market_label(play), f"Line {line_s}"]
    if play.get("play_type") == "prop":
        sub_parts.insert(1, "Prop")
    subtitle = " · ".join(sub_parts)
    if not badge:
        badge = _play_tier_badge_label(play.get("kickoff"), reference=reference)
    tags = _model_sharp_tags(play)
    stake_block = (
        f'<div class="units-badge">{units_s}<span class="nba-stake-dollars">{stake_s}</span></div>'
        if show_stake
        else '<div class="units-badge nba-lean-units">Lean · 0u</div>'
    )
    return f"""
      <div class="play-card {card_cls} nba-pick-card">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge {badge_cls}">{_esc(badge)}</span>
            <div class="nba-card-tip">{_esc(day_time)}</div>
            <div class="play-title">{_esc(title)}</div>
            <div class="play-subtitle">{_esc(subtitle)}</div>
          </div>
          {stake_block}
        </div>
        {tags}
        <details class="nba-pick-details">
          <summary>Odds &amp; detail</summary>
          <div class="play-meta">
            <div class="meta-item"><span class="meta-label">EV </span><span class="meta-val pos">{edge_s}</span></div>
            <div class="meta-item"><span class="meta-label">Fair </span><span class="meta-val">{fair_s}</span></div>
            <div class="meta-item"><span class="meta-label">Book </span><span class="meta-val">{_esc(book)} {_esc(price)}</span></div>
            <div class="meta-item"><span class="meta-label">Tip </span><span class="meta-val">{_esc(kick)}</span></div>
          </div>
        </details>
      </div>"""


def _render_price_edge_cards(
    picks: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    ref = reference or _slate_reference_date()

    def render_one(p: dict[str, Any]) -> str:
        return _render_nba_play_card(
            p,
            badge=_play_tier_badge_label(p.get("kickoff"), reference=ref),
            badge_cls="badge-play",
            card_cls="sharp-play",
            reference=ref,
        )

    return _render_et_date_grouped_cards(picks, render_one=render_one, reference=ref)


def _render_sharp_lean_cards(
    possible: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    ref = reference or _slate_reference_date()

    def render_one(p: dict[str, Any]) -> str:
        return _render_nba_play_card(
            p,
            badge="Lean",
            badge_cls="badge-lean",
            card_cls="sharp-lean",
            show_stake=False,
            reference=ref,
        )

    return _render_et_date_grouped_cards(possible, render_one=render_one, reference=ref)


def _render_score_modeling_card(item: dict[str, Any], *, reference: date | None = None) -> str:
    kick = format_kickoff_et(item.get("kickoff"))
    day_time = format_kickoff_day_time_et(item.get("kickoff"))
    ref = reference or _slate_reference_date()
    badge = _play_tier_badge_label(item.get("kickoff"), reference=ref)
    gap = float(item.get("signed_gap") or 0)
    gap_s = f"{gap:+.1f} pt vs consensus (injury-adj)"
    raw_gap = item.get("raw_signed_gap")
    raw_gap_s = f"{float(raw_gap):+.1f} pt unadj" if raw_gap is not None else ""
    secondary = item.get("secondary") or []
    extra = ""
    if secondary:
        bits = []
        for s in secondary:
            bits.append(f"{s['title']} ({s['signed_gap']:+.1f} pt)")
        extra = f'<div class="nba-score-secondary">Also: {_esc(" · ".join(bits))}</div>'
    absences = item.get("absence_lines") or []
    abs_html = ""
    if absences:
        abs_html = (
            '<div class="nba-score-absences">'
            + "<br>".join(_esc(line) for line in absences[:6])
            + "</div>"
        )
    stale = ""
    if item.get("injury_news_after_line"):
        stale = '<div class="nba-score-stale">Injury news may have landed after the line we compared to.</div>'
    flip = ""
    if item.get("injury_play_flip"):
        flip = '<div class="nba-score-flip">Injury adjustment changes or removes this display play vs the raw model.</div>'
    projected = item.get("projected_scores_line") or ""
    proj_html = ""
    if projected:
        proj_html = f'<div class="nba-score-projected">{_esc(projected)}</div>'
    gap_explain = str(item.get("gap_explain") or "").strip()
    gap_html = ""
    if gap_explain:
        gap_html = f'<div class="nba-score-gap-explain">{_esc(gap_explain)}</div>'
    detail_inner = f"""
          <div class="play-meta">
            <div class="meta-item"><span class="meta-label">Injury </span><span class="meta-val">{_esc(item.get("injury_model_line") or item.get("model_line") or "")}</span></div>
            <div class="meta-item"><span class="meta-label">Raw </span><span class="meta-val">{_esc(item.get("raw_model_line") or "")}</span></div>
            <div class="meta-item"><span class="meta-label">Market </span><span class="meta-val">{_esc(item.get("consensus_line") or "")}</span></div>
            <div class="meta-item"><span class="meta-label">Gap </span><span class="meta-val">{_esc(gap_s)}{(" · " + _esc(raw_gap_s)) if raw_gap_s else ""}</span></div>
          </div>
          {proj_html}
          {gap_html}
          {abs_html}
          {stale}
          {flip}
          {extra}"""
    return f"""
      <div class="play-card sharp-play nba-pick-card nba-score-card">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge badge-play">{_esc(badge)}</span>
            <div class="nba-card-tip">{_esc(day_time)}</div>
            <div class="play-title">{_esc(str(item.get("title") or ""))}</div>
            <div class="play-subtitle">{_esc(item.get("game") or "")}</div>
          </div>
          <div class="units-badge nba-gap-badge">{"Injuries" if item.get("injury_watch_only") else f"{float(item.get('gap') or 0):.1f} pt"}</div>
        </div>
        <details class="nba-pick-details">
          <summary>Projections &amp; detail</summary>
          {detail_inner}
        </details>
      </div>"""


def _render_score_modeling_cards(
    plays: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    ref = reference or _slate_reference_date()
    return _render_et_date_grouped_cards(
        plays,
        render_one=lambda p: _render_score_modeling_card(p, reference=ref),
        reference=ref,
    )


def _render_score_lean_card(item: dict[str, Any], *, reference: date | None = None) -> str:
    html = _render_score_modeling_card(item, reference=reference)
    return (
        html.replace("badge-play", "badge-lean", 1)
        .replace("sharp-play", "sharp-lean", 1)
        .replace("Tonight's play", PACE_WATCH_LIST_LABEL, 1)
        .replace("Tomorrow's play", PACE_WATCH_LIST_LABEL, 1)
        .replace("Slate play", PACE_WATCH_LIST_LABEL, 1)
    )


def _render_score_lean_cards(
    leans: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    ref = reference or _slate_reference_date()
    return _render_et_date_grouped_cards(
        leans,
        render_one=lambda p: _render_score_lean_card(p, reference=ref),
        reference=ref,
    )


def _render_props_empty(*, live_scan: bool, updated: str, next_scan: str) -> str:
    if not live_scan:
        return (
            f'<div class="nba-picks-empty" role="status">'
            f"<p>{_esc(NO_LIVE_SCAN_MESSAGE)}</p>"
            f"<p class=\"nba-picks-empty-sub\">Prop picks appear after a live scan with props enabled. "
            f"Next scan {_esc(next_scan)}.</p></div>"
        )
    return (
        f'<div class="nba-picks-empty" role="status">'
        f"<p><strong>No NBA prop picks on today&apos;s slate.</strong></p>"
        f"<p class=\"nba-picks-empty-sub\">Scheduled scans may skip props until the paper window opens. "
        f"Last updated {_esc(updated)}. Next scan {_esc(next_scan)} ({_esc(NBA_SCAN_SCHEDULE_LABEL)}).</p></div>"
    )


def _render_picks_empty(*, live_scan: bool, updated: str, next_scan: str) -> str:
    if not live_scan:
        return (
            f'<div class="nba-picks-empty" role="status">'
            f"<p>{_esc(NO_LIVE_SCAN_MESSAGE)}</p>"
            f"<p class=\"nba-picks-empty-sub\">Scheduled scans: {_esc(NBA_SCAN_SCHEDULE_LABEL)}. "
            f"Next scan {_esc(next_scan)}.</p></div>"
        )
    return (
        f'<div class="nba-picks-empty" role="status">'
        f"<p><strong>No NBA price-edge picks yet today.</strong></p>"
        f"<p class=\"nba-picks-empty-sub\">Last updated {_esc(updated)}. "
        f"Next scan {_esc(next_scan)} ({_esc(NBA_SCAN_SCHEDULE_LABEL)}).</p></div>"
    )


def _render_score_modeling_empty(*, live_scan: bool) -> str:
    if not live_scan:
        return ""
    return (
        '<div class="nba-picks-empty nba-picks-empty-soft" role="status">'
        f"<p>No Pace of Play plays right now (need ≥{SCORE_MODELING_MIN_EDGE_PT:g} pt gap vs consensus).</p>"
        "</div>"
    )


def _injury_list_summary(r: dict[str, Any]) -> str:
    from sharp_scout.nba.score_model.injury_adjust import format_absence_line

    bits: list[str] = []
    home, away = str(r.get("home") or ""), str(r.get("away") or "")
    for team, key in ((home, "home_excluded"), (away, "away_excluded")):
        for row in r.get(key) or []:
            bits.append(format_absence_line(team, row))
    for team, key in ((home, "home_absences"), (away, "away_absences")):
        for row in r.get(key) or []:
            if row.get("kind") in ("return", "absence"):
                bits.append(format_absence_line(team, row))
    if not bits:
        return "—"
    if len(bits) > 3:
        return _esc("; ".join(bits[:3]) + f" (+{len(bits) - 3} more)")
    return _esc("; ".join(bits))


def _pace_projection_row_html(r: dict[str, Any]) -> str:
    game = f"{r.get('away', '')} @ {r.get('home', '')}"
    home, away = str(r.get("home") or ""), str(r.get("away") or "")
    margin = float(r.get("margin") or 0)
    total = float(r.get("total") or 0)
    inj_m = float(r.get("injury_margin") if r.get("injury_margin") is not None else margin)
    inj_t = float(r.get("injury_total") if r.get("injury_total") is not None else total)
    h_raw, a_raw = projected_team_scores(margin, total)
    h_inj, a_inj = projected_team_scores(inj_m, inj_t)
    raw_score = f"{away} {a_raw:g} – {home} {h_raw:g}"
    inj_score = f"{away} {a_inj:g} – {home} {h_inj:g}"
    lines = r.get("lines") or {}
    spr = lines.get("consensus_spread_home")
    tot = lines.get("consensus_total")
    spr_gap = ""
    tot_gap = ""
    if spr is not None:
        spr_gap = f"{inj_m + float(spr):+.1f}"
    if tot is not None:
        tot_gap = f"{inj_t - float(tot):+.1f}"
    if spr is None and tot is None:
        market_s = "Waiting for lines"
        gap_s = "—"
    else:
        market_s = f"{spr if spr is not None else '—'} / {tot if tot is not None else '—'}"
        gap_s = f"{spr_gap or '—'} / {tot_gap or '—'}"
    tip = format_kickoff_day_time_et(r.get("kickoff"))
    return (
        "<tr>"
        f'<td data-label="Tip">{_esc(tip)}</td>'
        f'<td data-label="Game">{_esc(game)}</td>'
        f'<td data-label="Raw score">{_esc(raw_score)}</td>'
        f'<td data-label="Injury-adj score">{_esc(inj_score)}</td>'
        f'<td data-label="Margin (raw / inj)">{margin:+.1f} / {inj_m:+.1f}</td>'
        f'<td data-label="Total (raw / inj)">{total:.1f} / {inj_t:.1f}</td>'
        f'<td data-label="Market">{_esc(market_s)}</td>'
        f'<td data-label="Gap spr / tot">{_esc(gap_s)}</td>'
        f'<td data-label="Injuries">{_injury_list_summary(r)}</td>'
        "</tr>"
    )


def _render_pace_projections_table(
    rows: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    if not rows:
        return '<p class="empty">No Pace of Play projections on the upcoming slate yet (logged on live scans).</p>'
    ref = reference or _slate_reference_date()
    groups = group_items_by_kickoff_et_date(rows, kickoff_key="kickoff", reference=ref)
    table_head = (
        "<thead><tr><th>Tip</th><th>Game</th><th>Raw score</th><th>Injury-adj score</th>"
        "<th>Margin (raw / inj)</th><th>Total (raw / inj)</th><th>Market spr/tot</th>"
        "<th>Gap spr / tot</th><th>Injuries</th></tr></thead>"
    )
    chunks: list[str] = []
    for _day, label, group in groups:
        body = "".join(_pace_projection_row_html(r) for r in group)
        chunks.append(
            f'<h4 class="nba-h4">{_esc(label)}</h4>'
            f'<div class="table-wrap"><table class="export-table plays-table nba-table nba-proj-table">'
            f"{table_head}<tbody>{body}</tbody></table></div>"
        )
    return "\n".join(chunks)


def _render_current_season_totals_tracking(
    score_rows: list[dict[str, Any]],
    *,
    reference: date | None = None,
) -> str:
    """Shadow-only 2026-27 totals experiment — not official Pace plays."""
    from sharp_scout.nba.score_model.totals_shadow import (
        load_totals_shadow,
        summarize_totals_shadow,
    )
    from sharp_scout.nba.slate_et import kickoff_date_et
    from sharp_scout.nba.teams import normalize_nba_team

    summary = summarize_totals_shadow()
    record_line = (
        f"Shadow record (2026-27 totals method, tracking only): "
        f"{summary.get('record', '—')} · {summary.get('win_pct', '—')} · "
        f"{float(summary.get('units') or 0):+.2f}u · n={summary.get('n_plays', 0)}"
    )
    store = load_totals_shadow()
    pending_by_slot = {
        (
            str(p.get("date_et") or ""),
            normalize_nba_team(str(p.get("away") or "")),
            normalize_nba_team(str(p.get("home") or "")),
        ): p
        for p in store.get("pending") or []
    }
    if not score_rows:
        return (
            '<div class="nba-shadow-totals-note">'
            "<p><strong>Current-season totals (tracking only, not plays)</strong> — "
            "2026-27 game-log totals run in shadow alongside live projections. "
            "Nothing here is an official Pace play.</p>"
            f"<p>{_esc(record_line)}</p>"
            '<p class="empty">No open slate rows for sample-size diagnostics.</p></div>'
        )
    ref = reference or _slate_reference_date()
    groups = group_items_by_kickoff_et_date(score_rows, kickoff_key="kickoff", reference=ref)
    table_head = (
        "<thead><tr><th>Tip</th><th>Game</th><th>Live total (raw / inj)</th>"
        "<th>Shadow total (raw / inj)</th><th>2026-27 sample</th>"
        "<th>Shadow gap (not a play)</th></tr></thead>"
    )
    chunks: list[str] = [
        '<div class="nba-shadow-totals-note">',
        "<p><strong>Current-season totals (tracking only, not plays)</strong> — "
        "Experimental totals from 2026-27 games only (no prior-season blend). "
        "Official Pace card still uses legacy totals above.</p>",
        f"<p>{_esc(record_line)}</p>",
    ]
    for _day, label, group in groups:
        body_rows: list[str] = []
        for r in group:
            home, away = str(r.get("home") or ""), str(r.get("away") or "")
            day = kickoff_date_et(r.get("kickoff"))
            slot = (
                day.isoformat() if day else "",
                normalize_nba_team(away),
                normalize_nba_team(home),
            )
            pending = pending_by_slot.get(slot) or {}
            live_t = float(r.get("total") or 0)
            live_inj = float(
                r.get("injury_total") if r.get("injury_total") is not None else live_t
            )
            sh_t = pending.get("shadow_total")
            sh_inj = pending.get("shadow_injury_total")
            sh_raw_s = f"{float(sh_t):.1f}" if sh_t is not None else "—"
            sh_inj_s = f"{float(sh_inj):.1f}" if sh_inj is not None else "—"
            diag = pending.get("shadow_diagnostics") or {}
            sample_s = "—"
            if diag:
                h = diag.get("home") or {}
                a = diag.get("away") or {}
                sample_s = (
                    f"{h.get('team', home)} {h.get('games', 0)}g · "
                    f"{a.get('team', away)} {a.get('games', 0)}g · "
                    f"pace {diag.get('expected_pace', '—')}"
                )
            would = pending.get("would_play") or {}
            gap_s = "—"
            if would:
                gap_s = f"{would.get('pick', '—')} ({float(would.get('gap') or 0):+.1f} pt shadow)"
            tip = format_kickoff_day_time_et(r.get("kickoff"))
            game = f"{away} @ {home}"
            body_rows.append(
                "<tr>"
                f'<td data-label="Tip">{_esc(tip)}</td>'
                f'<td data-label="Game">{_esc(game)}</td>'
                f'<td data-label="Live total">{live_t:.1f} / {live_inj:.1f}</td>'
                f'<td data-label="Shadow total">{sh_raw_s} / {sh_inj_s}</td>'
                f'<td data-label="Sample">{_esc(sample_s)}</td>'
                f'<td data-label="Shadow gap">{_esc(gap_s)}</td>'
                "</tr>"
            )
        body = "".join(body_rows)
        chunks.append(
            f'<h4 class="nba-h4">{_esc(label)}</h4>'
            f'<div class="table-wrap"><table class="export-table plays-table nba-table nba-proj-table">'
            f"{table_head}<tbody>{body}</tbody></table></div>"
        )
    chunks.append("</div>")
    return "\n".join(chunks)


def _render_official_pace_history(store: dict[str, Any] | None) -> str:
    rows = sorted(
        (store or {}).get("plays") or [],
        key=lambda r: (r.get("date_et") or "", r.get("kickoff") or ""),
        reverse=True,
    )
    if not rows:
        return '<p class="empty">No official Pace of Play plays logged yet.</p>'
    body = []
    for r in rows:
        st = str(r.get("result") or "").upper()
        units = r.get("units")
        units_s = f"{float(units):+.2f}u" if units is not None else "—"
        body.append(
            "<tr>"
            f'<td data-label="Date (ET)">{_esc(r.get("date_et") or "")}</td>'
            f'<td data-label="Game">{_esc(r.get("away", ""))} @ {_esc(r.get("home", ""))}</td>'
            f'<td data-label="Pick"><b>{_esc(r.get("pick") or "")}</b></td>'
            f'<td data-label="Line">{_esc(r.get("line", "—"))}</td>'
            f'<td data-label="Price">{_esc(_price(r.get("price")))}</td>'
            f'<td data-label="Gap">{float(r.get("gap_pts") or 0):.2f} pt</td>'
            f'<td data-label="Result" class="{st.lower()}">{_esc(st)}</td>'
            f'<td data-label="Units" class="{"pos" if (units or 0) >= 0 else "neg"}">{units_s}</td>'
            f'<td data-label="Final">{_esc(r.get("espn_away_score", "—"))}–{_esc(r.get("espn_home_score", "—"))}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table nba-official-pace">'
        "<thead><tr><th>Date (ET)</th><th>Game</th><th>Pick</th><th>Line</th><th>Price</th>"
        "<th>Gap</th><th>Result</th><th>Units</th><th>Final</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_sharp_props_history(ledger: dict[str, Any] | None) -> str:
    plays = [
        p
        for p in (ledger or {}).get("plays") or []
        if p.get("play_type") == "prop"
        and str(p.get("status") or "").lower() in ("win", "loss", "push")
    ]
    plays = sorted(plays, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    if not plays:
        return '<p class="empty">No graded prop paper plays yet.</p>'
    body = []
    for p in plays:
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        pick = _prop_pick(p)
        pnl = p.get("pnl_units")
        pnl_s = f"{float(pnl):+.2f}u" if pnl is not None else "—"
        st = str(p.get("status") or "").lower()
        body.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Result" class="{st}">{_esc(st.upper())}</td>'
            f'<td data-label="P/L" class="{"pos" if (pnl or 0) >= 0 else "neg"}">{pnl_s}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Game</th><th>Pick</th><th>Result</th><th>P/L</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_pace_graded_history(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No graded Pace of Play paper plays yet (≥3 pt vs close at tip).</p>'
    body = []
    for r in rows:
        ur = r.get("units_raw")
        ui = r.get("units_injury")
        ur_s = f"{float(ur):+.2f}u" if ur is not None else "—"
        ui_s = f"{float(ui):+.2f}u" if ui is not None else "—"
        rr = str(r.get("result_raw") or "—").upper()
        ri = str(r.get("result_injury") or "—").upper()
        body.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(r.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(r.get("game") or "")}</td>'
            f'<td data-label="Pick"><b>{_esc(r.get("pick") or "")}</b></td>'
            f'<td data-label="Line">{_esc(r.get("line", "—"))}</td>'
            f'<td data-label="Gap">{float(r.get("gap") or 0):.1f} pt</td>'
            f'<td data-label="Raw result" class="{rr.lower()}">{_esc(rr)}</td>'
            f'<td data-label="Raw units" class="{"pos" if (ur or 0) >= 0 else "neg"}">{ur_s}</td>'
            f'<td data-label="Inj-adj result" class="{ri.lower()}">{_esc(ri)}</td>'
            f'<td data-label="Inj-adj units" class="{"pos" if (ui or 0) >= 0 else "neg"}">{ui_s}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Game</th><th>Pick</th><th>Line</th><th>Gap</th>"
        "<th>Raw result</th><th>Raw units</th><th>Inj-adj result</th><th>Inj-adj units</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_sharp_graded_history(ledger: dict[str, Any] | None) -> str:
    plays = (ledger or {}).get("plays") or []
    graded = [
        p
        for p in plays
        if str(p.get("status") or "").lower() in ("win", "loss", "push") and _is_sharp_game_line_play(p)
    ]
    graded = sorted(graded, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    if not graded:
        return '<p class="empty">No graded Sharp Scout paper plays yet.</p>'
    body = []
    for p in graded:
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        pick = _prop_pick(p) if p.get("play_type") == "prop" else _game_pick(p)
        line = p.get("line")
        line_s = f"{float(line):g}" if isinstance(line, (int, float)) else "—"
        pnl = p.get("pnl_units")
        pnl_s = f"{float(pnl):+.2f}u" if pnl is not None else "—"
        st = str(p.get("status") or "").lower()
        book = _book_label(p.get("book"))
        body.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Line">{_esc(line_s)}</td>'
            f'<td data-label="Book / price">{_esc(book)} {_esc(_price(p.get("price")))}</td>'
            f'<td data-label="Units">{float(p.get("units") or 0):.2f}u</td>'
            f'<td data-label="Result" class="{st}">{_esc(st.upper())}</td>'
            f'<td data-label="P/L" class="{"pos" if (pnl or 0) >= 0 else "neg"}">{pnl_s}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Game</th><th>Pick</th><th>Line</th><th>Book / price</th>"
        "<th>Units</th><th>Result</th><th>P/L</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_history_by_day(
    grouped: list[tuple[str, list[dict[str, Any]]]],
    *,
    renderer,
) -> str:
    if not grouped:
        return ""
    chunks = []
    for day, day_rows in grouped:
        chunks.append(f'<h4 class="nba-h4">{_esc(day)}</h4>{renderer(day_rows)}')
    return "\n".join(chunks)


def _render_injury_lag_block(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<p class="empty">No open injury-lag leans.</p>'
    body = []
    for e in entries:
        body.append(
            "<tr>"
            f'<td data-label="When">{_esc(format_kickoff_compact(e.get("detected_at")))}</td>'
            f'<td data-label="Player">{_esc(e.get("player"))} ({_esc(e.get("team"))})</td>'
            f'<td data-label="Status">{_esc(e.get("status"))}</td>'
            f'<td data-label="Impact">{float(e.get("impact_pts") or 0):.1f} pts</td>'
            f'<td data-label="Expected move">{float(e.get("expected_move_pts") or 0):.1f}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>When</th><th>Player</th><th>Status</th><th>Impact</th><th>Expected move</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _market_label(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        return NBA_PROP_LABELS.get(str(play.get("market")), str(play.get("market")))
    m = str(play.get("market") or "")
    return {"spreads": "Spread", "totals": "Total"}.get(m, m.title())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _is_demo_play(play: dict[str, Any]) -> bool:
    from sharp_scout.nba.ledger import is_demo_nba_row

    return is_demo_nba_row(play)


def has_live_nba_scan(signals_payload: dict[str, Any] | None) -> bool:
    """True when the latest shadow scan is a non-demo live run (signals may still be empty)."""
    if not signals_payload:
        return False
    if signals_payload.get("demo"):
        return False
    return bool(signals_payload.get("ok", True))


def _empty_public_signals() -> dict[str, Any]:
    return {
        "ok": False,
        "demo": False,
        "generated_at": None,
        "n_events": 0,
        "n_signals": 0,
        "signals": [],
        "n_possible": 0,
        "possible_signals": [],
    }


def public_nba_signals(signals_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not has_live_nba_scan(signals_payload):
        return _empty_public_signals()
    out = dict(signals_payload or {})
    out["demo"] = False
    picks = [
        s
        for s in (out.get("signals") or [])
        if (s.get("pick_class") or "pick") != "possible"
        and not s.get("display_only")
        and not _is_demo_play(s)
    ]
    possible = [p for p in (out.get("possible_signals") or []) if not _is_demo_play(p)]
    from sharp_scout.nba.possible import cap_props_per_game

    picks, possible = cap_props_per_game(picks, possible)
    out["signals"] = picks
    out["n_signals"] = len(picks)
    out["possible_signals"] = possible
    out["n_possible"] = len(possible)
    return out


def public_nba_ledger(ledger: dict[str, Any] | None) -> dict[str, Any]:
    from sharp_scout.nba.ledger import empty_nba_ledger

    if not ledger:
        return empty_nba_ledger()
    plays = [p for p in ledger.get("plays") or [] if not _is_demo_play(p)]
    out = dict(ledger)
    out["plays"] = plays
    return out


def public_nba_report(
    report: dict[str, Any] | None,
    *,
    ledger: dict[str, Any] | None,
    live_scan: bool,
) -> dict[str, Any]:
    if not live_scan:
        settings = get_settings()
        return {
            "generated_at": None,
            "paper_window": {"start": settings.nba_paper_start, "end": settings.nba_paper_end},
            "in_window": False,
            "clv_summary": {},
            "calibration": [],
            "pass_fail": [],
            "n_plays": 0,
        }
    from sharp_scout.nba.report import build_paper_report

    return build_paper_report(public_nba_ledger(ledger))


def _record_by_bet_type(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    plays = (ledger or {}).get("plays") or []
    buckets: dict[str, dict[str, Any]] = {}

    def bucket(key: str) -> dict[str, Any]:
        if key not in buckets:
            buckets[key] = {
                "label": key,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "pending": 0,
                "pnl_units": 0.0,
                "clv_probs": [],
            }
        return buckets[key]

    for p in plays:
        label = _bet_type_label(p)
        b = bucket(label)
        st = str(p.get("status") or "paper").lower()
        if st == "win":
            b["wins"] += 1
        elif st == "loss":
            b["losses"] += 1
        elif st == "push":
            b["pushes"] += 1
        elif st in ("paper", "pending"):
            b["pending"] += 1
        if p.get("pnl_units") is not None:
            b["pnl_units"] += float(p["pnl_units"])
        if p.get("clv_prob") is not None:
            b["clv_probs"].append(float(p["clv_prob"]))

    out = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        graded = b["wins"] + b["losses"] + b["pushes"]
        wl = f"{b['wins']}-{b['losses']}"
        if b["pushes"]:
            wl += f"-{b['pushes']}"
        avg_clv = sum(b["clv_probs"]) / len(b["clv_probs"]) if b["clv_probs"] else None
        out.append(
            {
                "label": key,
                "record": wl if graded else "—",
                "graded": graded,
                "pending": b["pending"],
                "pnl_units": b["pnl_units"] if graded else None,
                "avg_clv_prob": avg_clv,
            }
        )
    return out


def _render_sharp_money_table(sharp: dict[str, Any]) -> str:
    labels = {
        "with_sharps": "With sharps",
        "against_sharps": "Against sharps",
        "no_signal": "No signal",
    }
    body = []
    for key in ("with_sharps", "against_sharps", "no_signal"):
        row = sharp.get(key) or {}
        n = int(row.get("n") or 0)
        if not n:
            continue
        body.append(
            "<tr>"
            f'<td data-label="Tag">{_esc(labels[key])}</td>'
            f'<td data-label="Graded">{n}</td>'
            f'<td data-label="Record">{_esc(row.get("record") or "—")}</td>'
            f'<td data-label="Units">{float(row.get("units") or 0):+.2f}u</td>'
            "</tr>"
        )
    if not body:
        return (
            '<p class="empty">Sharp-money splits appear after graded side/total plays are tagged.</p>'
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table nba-sharp-table">'
        "<thead><tr><th>Tag</th><th>Graded</th><th>Record</th><th>Units</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_record_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    cards = []
    for r in rows:
        pnl = r.get("pnl_units")
        pnl_s = "—"
        if pnl is not None:
            pnl_s = f"{pnl:+.2f}u"
        clv = r.get("avg_clv_prob")
        clv_s = _pct(clv) if clv is not None else "—"
        pending = int(r.get("pending") or 0)
        extra = f" · {pending} open" if pending else ""
        cards.append(
            '<div class="nba-rec-card">'
            f'<div class="nba-rec-lbl">{_esc(r["label"])}</div>'
            f'<div class="nba-rec-val">{_esc(r["record"])}</div>'
            f'<div class="nba-rec-sub">Units {pnl_s} · CLV {clv_s}{extra}</div>'
            "</div>"
        )
    return '<div class="nba-record-grid">' + "".join(cards) + "</div>"


def _render_possible_rows(rows: list[dict[str, Any]], *, kind: str) -> str:
    filtered = [s for s in rows if (s.get("play_type") or "side") == kind]
    filtered = sorted(filtered, key=lambda p: float(p.get("edge") or 0), reverse=True)
    if not filtered:
        return '<p class="empty">No near-miss game-line candidates right now.</p>' if kind != "prop" else (
            '<p class="empty">No near-miss prop candidates right now.</p>'
        )
    body = []
    for i, p in enumerate(filtered, 1):
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        player = str(p.get("player_name") or "—") if kind == "prop" else "—"
        lean = _possible_lean_line(p)
        reason = str(p.get("reject_reason") or "Did not qualify")
        meta = f"EV {_pct(p.get('edge'))} · {reason} · 0u (display only)"
        body.append(
            "<tr>"
            f'<td data-label="#">{i}</td>'
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Player">{_esc(player)}</td>'
            f'<td data-label="Tentative lean" class="nba-lean-cell">'
            f'<div class="nba-lean-main"><b>{_esc(lean)}</b></div>'
            f'<div class="nba-lean-meta">{_esc(meta)}</div></td>'
            "</tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Tip</th><th>Game</th><th>Player</th>"
        "<th>Tentative lean</th></tr></thead>"
    )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table nba-possible-table">'
        f"{head}<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_candidate_rows(signals: list[dict[str, Any]], *, kind: str) -> str:
    filtered = [s for s in signals if (s.get("play_type") or "side") == kind]
    filtered = sorted(filtered, key=lambda p: kickoff_sort_key(p.get("kickoff")))
    if not filtered:
        return (
            '<p class="empty">No qualifying picks right now.</p>'
            if kind != "prop"
            else '<p class="empty">No qualifying prop picks right now.</p>'
        )
    rows = []
    for i, p in enumerate(filtered, 1):
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        if kind == "prop":
            pick = _prop_pick(p)
            player = str(p.get("player_name") or "—")
        else:
            pick = _game_pick(p)
            player = "—"
        units = p.get("units")
        units_s = f"{float(units):.2f}u" if isinstance(units, (int, float)) else "—"
        fair = p.get("p_true") if p.get("p_true") is not None else p.get("p_fair")
        tags = _model_sharp_tags(p)
        rows.append(
            "<tr>"
            f'<td data-label="#">{i}</td>'
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Player">{_esc(player)}</td>'
            f'<td data-label="Market">{_esc(_market_label(p))}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Line">{_esc(p.get("line", "—"))}</td>'
            f'<td data-label="Book / price">{_esc(_price(p.get("price")))} '
            f'<span class="nba-book">{_esc(_book_label(p.get("book")))}</span></td>'
            f'<td data-label="EV">{_pct(p.get("edge"))}</td>'
            f'<td data-label="Fair %">{_pct(fair)}</td>'
            f'<td data-label="Units">{units_s}</td>'
            f'<td data-label="Model / sharp">{tags}</td>'
            "</tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Tip</th><th>Game</th><th>Player</th><th>Market</th>"
        "<th>Pick</th><th>Line</th><th>Book / price</th><th>EV</th><th>Fair %</th><th>Units</th>"
        "<th>Model / sharp</th>"
        "</tr></thead>"
    )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        f"{head}<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_ledger_rows(ledger: dict[str, Any] | None) -> str:
    plays = (ledger or {}).get("plays") or []
    graded = [p for p in plays if str(p.get("status") or "").lower() in ("win", "loss", "push")]
    graded = sorted(graded, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    if not graded:
        return '<p class="empty">No graded paper plays yet. Records appear after games finish and settle.</p>'
    rows = []
    for p in graded:
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        pick = _prop_pick(p) if p.get("play_type") == "prop" else _game_pick(p)
        pnl = p.get("pnl_units")
        pnl_s = f"{float(pnl):+.2f}u" if pnl is not None else "—"
        clv = p.get("clv_prob")
        st = str(p.get("status") or "").lower()
        st_cls = st if st in ("win", "loss", "push") else "pending"
        rows.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Type">{_esc(_bet_type_label(p))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Result" class="{st_cls}">{_esc(st.upper())}</td>'
            f'<td data-label="P/L" class="{"pos" if (pnl or 0) >= 0 else "neg"}">{pnl_s}</td>'
            f'<td data-label="CLV">{_pct(clv) if clv is not None else "—"}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Type</th><th>Game</th><th>Pick</th><th>Result</th>"
        "<th>P/L</th><th>CLV</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_pace_v1_v2_shadow_table(rows: list[dict[str, Any]]) -> str:
    """Side-by-side v1 production pick vs v2 shadow (never official card)."""
    if not rows:
        return ""
    trs: list[str] = []
    for r in rows:
        scans = r.get("scans") or []
        snap = scans[-1] if scans else r
        away, home = str(r.get("away") or ""), str(r.get("home") or "")
        v1_pick = snap.get("pace_v1_pick") or "—"
        v1_gap = snap.get("pace_v1_gap")
        v1_gap_s = f"{float(v1_gap):.1f}" if v1_gap is not None else "—"
        units = snap.get("pace_v1_recommended_units")
        units_s = f"{float(units):g}u" if units is not None else "—"
        sv2 = snap.get("shadow_v2") or {}
        v2_pick = sv2.get("pick") or sv2.get("would_be_pick") or "—"
        v2_gap = sv2.get("gap") if sv2.get("pick") else sv2.get("would_be_gap")
        v2_gap_s = f"{float(v2_gap):.1f}" if v2_gap is not None else "—"
        trs.append(
            f"<tr><td>{_esc(f'{away} @ {home}')}</td>"
            f"<td>{_esc(str(v1_pick))}</td><td>{v1_gap_s}</td><td>{units_s}</td>"
            f"<td>{_esc(str(v2_pick))}</td><td>{v2_gap_s}</td></tr>"
        )
    if not trs:
        return ""
    return (
        '<div class="nba-pace-shadow" aria-labelledby="pace-shadow-heading">'
        '<h3 class="nba-h3" id="pace-shadow-heading">Pace v1 vs v2 shadow (paper only)</h3>'
        '<p class="nba-section-note">v1 drives the official card (3 pt bar). v2 is experimental; '
        "promotion requires ~100 shadow plays beating v1 on CLV (<a href=\"nba_pace_v2_shadow.md\">rule</a>).</p>"
        '<table class="nba-table"><thead><tr><th>Game</th><th>v1 pick</th><th>v1 gap</th>'
        "<th>v1 rec</th><th>v2 shadow</th><th>v2 gap</th></tr></thead><tbody>"
        + "".join(trs)
        + "</tbody></table></div>"
    )


def render_nba_page_html(
    *,
    signals_payload: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    report: dict[str, Any] | None,
    analytics_head: str,
    score_model_rows: list[dict[str, Any]] | None = None,
    injury_lag_rows: list[dict[str, Any]] | None = None,
    score_model_summary: dict[str, Any] | None = None,
    score_model_store: dict[str, Any] | None = None,
) -> str:
    from sharp_scout.site.bottom_bar import BOTTOM_BAR_SCRIPT, bottom_bar_css, render_bottom_bar
    from sharp_scout.site.build import _SITE_CSS, _format_timestamp_et, _ssq_logo_svg

    live_scan = has_live_nba_scan(signals_payload)
    pub_signals = public_nba_signals(signals_payload)
    if live_scan:
        try:
            from sharp_scout.nba.sharp_splits.filter import annotate_signals_with_sharp_money

            pool = list(pub_signals.get("signals") or []) + list(
                pub_signals.get("possible_signals") or []
            )
            annotate_signals_with_sharp_money([], pool)
        except Exception:  # noqa: BLE001
            pass
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    picks = list(pub_signals.get("signals") or [])
    possible = list(pub_signals.get("possible_signals") or [])
    generated = parse_commence(pub_signals.get("generated_at"))
    updated = _format_timestamp_et(generated) if generated else "—"
    next_scan = _format_timestamp_et(next_nba_scan_et())

    body_class = "ss-bottom-bar"
    mode_note = "Live shadow scan" if live_scan else "Awaiting live scan"

    from sharp_scout.nba.score_model.official_pace import load_official_pace, summarize_official_pace

    official_pace = load_official_pace()
    official_summary = summarize_official_pace(official_pace)
    sharp_game_lines = _sharp_scout_record_summary(pub_ledger, game_lines_only=True)
    pace_summary = _pace_record_summary(score_model_summary)
    pace_graded = _pace_pick_rows_from_store(score_model_store)

    slate_ref = _slate_reference_date()
    picks_slate = upcoming_slate_items(picks)
    possible_slate = upcoming_slate_items(possible)
    side_picks_slate = [p for p in picks_slate if (p.get("play_type") or "side") != "prop"]
    side_possible_slate = [p for p in possible_slate if (p.get("play_type") or "side") != "prop"]

    sharp_plays_html = (
        _render_price_edge_cards(side_picks_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not sharp_plays_html:
        sharp_plays_html = _render_picks_empty(live_scan=True, updated=updated, next_scan=next_scan)
    elif not live_scan:
        sharp_plays_html = _render_picks_empty(live_scan=False, updated=updated, next_scan=next_scan)

    sharp_leans_html = (
        _render_sharp_lean_cards(side_possible_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not sharp_leans_html:
        sharp_leans_html = (
            '<p class="empty nba-leans-empty">No Sharp Scout leans today — near-miss EV spots will show here.</p>'
        )

    score_rows = score_model_rows or []
    waiting_lines = live_scan and _score_rows_missing_lines(score_rows)
    pace_plays = (
        score_modeling_display_plays(score_rows, include_injury_watch=False) if live_scan else []
    )
    pace_plays = [p for p in pace_plays if not p.get("injury_watch_only")]
    pace_leans = score_modeling_display_leans(score_rows) if live_scan else []

    pace_plays_html = (
        _render_score_modeling_cards(pace_plays, reference=slate_ref)
        if live_scan and pace_plays
        else ""
    )
    if live_scan and not pace_plays_html:
        if waiting_lines:
            pace_plays_html = _render_waiting_for_lines(next_scan)
        else:
            pace_plays_html = _render_score_modeling_empty(live_scan=True)
    elif not live_scan:
        pace_plays_html = _render_picks_empty(live_scan=False, updated=updated, next_scan=next_scan)

    pace_leans_html = (
        _render_score_lean_cards(pace_leans, reference=slate_ref) if live_scan and pace_leans else ""
    )
    if live_scan and not pace_leans_html:
        if waiting_lines:
            pace_leans_html = _render_waiting_for_lines(next_scan)
        else:
            pace_leans_html = (
                f'<p class="empty nba-leans-empty">No Pace of Play {PACE_WATCH_LIST_LABEL.lower()} '
                f"entries today (need {PACE_LEAN_MIN_EDGE_PT:g}–{SCORE_MODELING_MIN_EDGE_PT:g} pt "
                "gap vs consensus).</p>"
            )

    pace_shadow_html = _render_pace_v1_v2_shadow_table(score_rows) if live_scan else ""
    pace_projections_html = (
        _render_pace_projections_table(score_rows, reference=slate_ref) if live_scan else ""
    )
    pace_totals_shadow_html = ""
    if live_scan:
        try:
            pace_totals_shadow_html = _render_current_season_totals_tracking(
                score_rows, reference=slate_ref
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("NBA totals shadow page section skipped: %s", exc)
            pace_totals_shadow_html = (
                '<p class="empty">Current-season totals tracking temporarily unavailable.</p>'
            )
    from sharp_scout.nba.manual_lines import manual_lines_page_note

    pace_lines_note = manual_lines_page_note()
    pace_history_html = _render_official_pace_history(official_pace)
    raw_p = pace_summary.get("raw") or {}
    inj_p = pace_summary.get("injury") or {}
    pace_auto_secondary = (
        f"Secondary — repo auto-track at ≥3 pt vs close: raw {raw_p.get('record', '—')} "
        f"({raw_p.get('units', 0):+.2f}u), injury-adj {inj_p.get('record', '—')} "
        f"({inj_p.get('units', 0):+.2f}u); {len(pace_graded)} pick-rows in store vs "
        f"{official_summary.get('n_plays', 0)} official card plays."
    )

    sharp_history_html = _render_sharp_graded_history(pub_ledger)

    gl_range = sharp_game_lines.get("date_range_et") or "—"
    sharp_compact_record = _render_compact_record(
        record=sharp_game_lines.get("record") or "—",
        win_pct=sharp_game_lines.get("win_pct") or "—",
        units=float(sharp_game_lines.get("units") or 0),
        label=f"Game lines · {gl_range} ET",
    )
    off_range = official_summary.get("date_range_et") or "—"
    pace_compact_record = _render_compact_record(
        record=official_summary.get("record") or "—",
        win_pct=official_summary.get("win_pct") or "—",
        units=float(official_summary.get("units") or 0),
        label=f"Official card · {off_range} ET",
    )

    side_picks = [p for p in picks if (p.get("play_type") or "side") != "prop"]
    side_possible = [p for p in possible if (p.get("play_type") or "side") != "prop"]
    game_picks_table = _render_candidate_rows(side_picks, kind="side") if live_scan else ""
    game_possible_table = _render_possible_rows(side_possible, kind="side") if live_scan else ""
    record_rows = _record_by_bet_type(pub_ledger)
    record_block = _render_record_cards(record_rows)
    injury_block = _render_injury_lag_block(injury_lag_rows or []) if live_scan else ""
    sm = pub_report.get("sharp_money") or {}
    sharp_money_block = _render_sharp_money_table(sm) if live_scan else ""

    model_details = f"""
    <h3 class="nba-h3">Export tables</h3>
    <h4 class="nba-h4">Sharp Scout game lines</h4>
    {game_picks_table}
    <h3 class="nba-h3">Near-miss tables (game lines)</h3>
    {game_possible_table}
    <h3 class="nba-h3">Paper record by bet type</h3>
    {record_block or '<p class="empty">No ledger rows yet.</p>'}
    <h3 class="nba-h3">Injury lag (paper)</h3>
    {injury_block}
    <h3 class="nba-h3">Sharp money tags</h3>
    {sharp_money_block}
    """

    in_window = pub_report.get("in_window")
    window = pub_report.get("paper_window") or {}
    window_s = ""
    if window.get("start") and window.get("end"):
        window_s = f"Paper window {window['start']} – {window['end']}. "
    window_flag = "In paper window." if in_window else "Outside paper window (testing only)."

    from sharp_scout.site.site_nav import render_site_tabs

    return NBA_PAGE_TEMPLATE.format(
        site_tabs=render_site_tabs(active="nba"),
        site_css=_SITE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        ssq_logo=_ssq_logo_svg(embedded=True),
        body_class=body_class,
        updated=_esc(updated),
        mode_note=_esc(mode_note),
        next_scan=_esc(next_scan),
        window_note=_esc(window_s + window_flag),
        sharp_compact_record=sharp_compact_record,
        sharp_plays_html=sharp_plays_html,
        sharp_leans_html=sharp_leans_html,
        sharp_history_html=sharp_history_html,
        sharp_record_note=(
            "Spreads/totals only (props on "
            '<a href="nba-props.html">NBA Props</a>). '
            "Oct 24–26 ET includes pre-window shadow testing; configured paper window starts "
            f"{window.get('start', '—')}."
        ),
        pace_compact_record=pace_compact_record,
        pace_auto_secondary=_esc(pace_auto_secondary),
        pace_plays_html=pace_plays_html,
        pace_shadow_html=pace_shadow_html,
        pace_leans_html=pace_leans_html,
        pace_projections_html=pace_projections_html,
        pace_totals_shadow_html=pace_totals_shadow_html,
        pace_history_html=pace_history_html,
        model_details=model_details,
        pace_play_threshold=f"{SCORE_MODELING_MIN_EDGE_PT:g}",
        pace_lean_range=f"{PACE_LEAN_MIN_EDGE_PT:g}–{SCORE_MODELING_MIN_EDGE_PT:g}",
        pace_watch_list_label=PACE_WATCH_LIST_LABEL,
        pace_watch_list_note=PACE_WATCH_LIST_NOTE,
        pace_lines_note=pace_lines_note,
        bottom_bar=render_bottom_bar(active="plays"),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
    )


def render_nba_props_page_html(
    *,
    signals_payload: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    report: dict[str, Any] | None,
    analytics_head: str,
) -> str:
    from sharp_scout.site.bottom_bar import BOTTOM_BAR_SCRIPT, bottom_bar_css, render_bottom_bar
    from sharp_scout.site.build import _SITE_CSS, _format_timestamp_et, _ssq_logo_svg

    live_scan = has_live_nba_scan(signals_payload)
    pub_signals = public_nba_signals(signals_payload)
    if live_scan:
        try:
            from sharp_scout.nba.sharp_splits.filter import annotate_signals_with_sharp_money

            pool = list(pub_signals.get("signals") or []) + list(
                pub_signals.get("possible_signals") or []
            )
            annotate_signals_with_sharp_money([], pool)
        except Exception:  # noqa: BLE001
            pass
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    picks = list(pub_signals.get("signals") or [])
    possible = list(pub_signals.get("possible_signals") or [])
    generated = parse_commence(pub_signals.get("generated_at"))
    updated = _format_timestamp_et(generated) if generated else "—"
    next_scan = _format_timestamp_et(next_nba_scan_et())

    props_ledger_summary = _sharp_scout_record_summary(pub_ledger, game_lines_only=False)
    props_summary = props_ledger_summary["props"]
    pr_range = props_ledger_summary.get("date_range_et") or "—"
    props_compact_record = _render_compact_record(
        record=_record_str(
            props_summary.get("w", 0),
            props_summary.get("l", 0),
            props_summary.get("p", 0),
        ),
        win_pct=_win_pct(
            props_summary.get("w", 0),
            props_summary.get("l", 0),
            props_summary.get("p", 0),
        ),
        units=float(props_summary.get("units") or 0),
        label=f"Player props · {pr_range} ET",
    )

    slate_ref = _slate_reference_date()
    picks_slate = upcoming_slate_items(picks)
    possible_slate = upcoming_slate_items(possible)
    prop_picks_slate = [p for p in picks_slate if p.get("play_type") == "prop"]
    prop_possible_slate = [p for p in possible_slate if p.get("play_type") == "prop"]

    prop_plays_html = (
        _render_price_edge_cards(prop_picks_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not prop_plays_html:
        prop_plays_html = _render_props_empty(live_scan=True, updated=updated, next_scan=next_scan)
    elif not live_scan:
        prop_plays_html = _render_props_empty(live_scan=False, updated=updated, next_scan=next_scan)

    prop_leans_html = (
        _render_sharp_lean_cards(prop_possible_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not prop_leans_html:
        prop_leans_html = (
            '<p class="empty nba-leans-empty">No prop leans today — near-miss EV spots will show here.</p>'
        )

    prop_history_html = _render_sharp_props_history(pub_ledger)
    prop_picks_table = _render_candidate_rows(picks, kind="prop") if live_scan else ""
    prop_possible_table = _render_possible_rows(possible, kind="prop") if live_scan else ""

    in_window = pub_report.get("in_window")
    window = pub_report.get("paper_window") or {}
    window_s = ""
    if window.get("start") and window.get("end"):
        window_s = f"Paper window {window['start']} – {window['end']}. "
    window_flag = "In paper window." if in_window else "Outside paper window (testing only)."

    from sharp_scout.site.site_nav import render_site_tabs

    return NBA_PROPS_PAGE_TEMPLATE.format(
        site_tabs=render_site_tabs(active="nba_props"),
        site_css=_SITE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        ssq_logo=_ssq_logo_svg(embedded=True),
        body_class="ss-bottom-bar",
        updated=_esc(updated),
        mode_note=_esc("Live shadow scan" if live_scan else "Awaiting live scan"),
        next_scan=_esc(next_scan),
        window_note=_esc(window_s + window_flag),
        props_compact_record=props_compact_record,
        prop_plays_html=prop_plays_html,
        prop_leans_html=prop_leans_html,
        prop_history_html=prop_history_html,
        prop_picks_table=prop_picks_table,
        prop_possible_table=prop_possible_table,
        bottom_bar=render_bottom_bar(active="plays"),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
    )


def build_nba_page(*, docs_dir: Path | None = None) -> Path | None:
    """Write docs/nba.html and shadow JSON copies. Does not touch football artifacts."""
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    signals_payload = _load_json(nba_paths.NBA_LATEST_SIGNALS_PATH)
    ledger = _load_json(nba_paths.NBA_LEDGER_PATH)
    report = _load_json(nba_paths.NBA_REPORT_PATH)
    try:
        from sharp_scout.nba.ledger import load_nba_ledger, save_nba_ledger
        from sharp_scout.nba.sharp_splits.filter import refresh_open_ledger_sharp_tags

        led = load_nba_ledger()
        if refresh_open_ledger_sharp_tags(led):
            save_nba_ledger(led)
            ledger = led
    except Exception:  # noqa: BLE001
        pass
    live_scan = has_live_nba_scan(signals_payload)

    pub_signals = public_nba_signals(signals_payload)
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    (out / "nba_latest_signals.json").write_text(
        json.dumps(pub_signals, indent=2, default=str) + "\n"
    )
    (out / "nba_ledger.json").write_text(json.dumps(pub_ledger, indent=2, default=str) + "\n")
    (out / "nba_paper_report.json").write_text(
        json.dumps(pub_report, indent=2, default=str) + "\n"
    )
    for src_name in (
        "nba_score_model.json",
        "nba_injury_lag.json",
        "nba_pace_of_play_official.json",
        "nba_pace_of_play_official.csv",
    ):
        src = nba_paths.PAPER_DIR / src_name
        if src.exists():
            (out / src_name).write_text(src.read_text())

    from sharp_scout.site.build import _render_analytics_head

    score_model_rows: list[dict[str, Any]] = []
    injury_lag_rows: list[dict[str, Any]] = []
    score_model_summary: dict[str, Any] = {}
    if live_scan:
        try:
            from sharp_scout.nba.score_model.injury_lag import open_entries_for_page
            from sharp_scout.nba.score_model.paper import load_paper_store, slate_projections_for_page

            score_model_rows = slate_projections_for_page()
            injury_lag_rows = open_entries_for_page()
            score_model_summary = load_paper_store().get("summary") or {}
        except Exception:  # noqa: BLE001
            pass

    paper_store: dict[str, Any] = {}
    try:
        from sharp_scout.nba.score_model.paper import load_paper_store

        paper_store = load_paper_store()
        if not score_model_summary:
            score_model_summary = paper_store.get("summary") or {}
    except Exception:  # noqa: BLE001
        pass

    analytics_head = _render_analytics_head(get_settings().ga_measurement_id)
    html = render_nba_page_html(
        signals_payload=signals_payload,
        ledger=ledger,
        report=report,
        analytics_head=analytics_head,
        score_model_rows=score_model_rows,
        injury_lag_rows=injury_lag_rows,
        score_model_summary=score_model_summary,
        score_model_store=paper_store,
    )
    (out / "nba.html").write_text(html)
    props_html = render_nba_props_page_html(
        signals_payload=signals_payload,
        ledger=ledger,
        report=report,
        analytics_head=analytics_head,
    )
    (out / "nba-props.html").write_text(props_html)
    return out / "nba.html"


_NBA_SHARED_PAGE_CSS = """
  .nba-test-banner {{
    background: #fef3c7; border: 2px solid #d97706; color: #92400e;
    text-align: center; font-weight: 800; font-size: clamp(14px, 3.5vw, 16px);
    padding: 12px 16px; margin: 0;
  }}
  .nba-content {{ max-width: 1240px; margin: 0 auto; padding: 16px 16px 48px; }}
  .nba-note {{ font-size: 13px; color: var(--color-text-muted); margin: 0 0 20px; line-height: 1.55; }}
  .nba-note a {{ color: var(--color-navy); font-weight: 600; }}
  .nba-model-panel {{
    border: 2px solid var(--color-border); background: var(--color-bg);
    padding: 16px 14px 18px; margin: 0 0 24px; border-radius: 2px;
  }}
  .nba-model-panel.pace-panel {{ border-top: 4px solid var(--color-navy); }}
  .nba-model-panel.sharp-panel {{ border-top: 4px solid var(--color-win); }}
  .nba-model-panel.props-panel {{ border-top: 4px solid #7c3aed; }}
  .nba-h2 {{ font-family: var(--font-serif); font-size: clamp(24px, 5vw, 28px); font-weight: 500; margin: 0 0 8px; }}
  .nba-h3 {{ font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 18px 0 8px; }}
  .nba-h4 {{ font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .06em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 14px 0 6px; }}
  .nba-section-note {{ font-size: 12.5px; color: var(--color-text-muted); margin: 0 0 12px; line-height: 1.5; }}
  .nba-rec-chip {{
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px;
    background: var(--color-bg-soft); border: 1px solid var(--color-border);
    padding: 10px 12px; margin: 0 0 14px; font-size: 13px;
  }}
  .nba-rec-chip-label {{ font-family: var(--font-mono); font-size: 10px; font-weight: 700;
    letter-spacing: .06em; text-transform: uppercase; color: var(--color-text-muted); width: 100%; }}
  .nba-rec-chip-record {{ font-size: 20px; font-weight: 700; color: var(--color-text); }}
  .nba-rec-chip-meta {{ color: var(--color-text-muted); font-size: 13px; }}
  .nba-plays-block {{ margin: 4px 0 16px; }}
  .nba-plays-block .section-label {{ margin-bottom: 10px; font-size: 13px; }}
  .nba-day-group {{ margin: 0 0 18px; }}
  .nba-day-heading {{
    font-family: var(--font-serif); font-size: clamp(18px, 4vw, 22px); font-weight: 600;
    margin: 0 0 10px; color: var(--color-navy);
  }}
  .nba-day-count {{ font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--color-text-muted); }}
  .nba-card-tip {{
    font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .03em;
    color: var(--color-navy); margin: 6px 0 4px;
  }}
  .nba-section-details {{
    margin: 16px 0 0; border: 1px dashed #cbd5e1; background: var(--color-bg-soft);
    padding: 2px 12px 12px;
  }}
  .nba-section-details > summary {{
    cursor: pointer; font-family: var(--font-mono); font-size: 11px; font-weight: 700;
    letter-spacing: .06em; text-transform: uppercase; color: var(--color-text-muted);
    padding: 12px 0; list-style: none;
  }}
  .nba-section-details > summary::-webkit-details-marker {{ display: none; }}
  .nba-leans-block {{ padding: 4px 0 0; }}
  .nba-leans-empty {{ font-size: 13px; margin: 0 0 8px; }}
  .nba-picks-empty {{
    border: 2px solid var(--color-border); background: var(--color-bg);
    padding: 16px 14px; margin: 0 0 12px; line-height: 1.55; font-size: 15px;
  }}
  .nba-picks-empty-soft {{ border-style: dashed; font-size: 14px; color: var(--color-text-muted); }}
  .nba-picks-empty-sub {{ font-size: 13px; color: var(--color-text-muted); margin-top: 8px; font-weight: 400; }}
  .nba-pick-cards {{ margin: 0; }}
  .nba-pick-card {{ margin-bottom: 12px; }}
  .nba-pick-card .play-title {{ font-size: clamp(20px, 5vw, 26px); font-weight: 700; line-height: 1.2; }}
  .nba-stake-dollars {{ display: block; font-size: 10px; font-weight: 500; color: var(--color-text-muted); margin-top: 2px; }}
  .nba-lean-units {{ font-size: 11px; color: var(--color-text-muted); }}
  .nba-tag-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .nba-gap-badge {{ font-size: 11px; letter-spacing: 0.04em; }}
  .nba-pick-details {{ margin-top: 8px; font-size: 12px; }}
  .nba-pick-details > summary {{
    cursor: pointer; color: var(--color-navy); font-weight: 600; list-style: none; padding: 4px 0;
  }}
  .nba-pick-details > summary::-webkit-details-marker {{ display: none; }}
  .nba-score-secondary {{ font-size: 12px; color: var(--color-text-muted); margin-top: 10px; line-height: 1.45; }}
  .nba-score-absences {{ font-size: 12px; line-height: 1.5; margin-top: 10px; color: var(--color-text); }}
  .nba-score-projected, .nba-score-gap-explain {{ font-size: 12px; line-height: 1.45; margin-top: 8px; color: var(--color-text-muted); }}
  .nba-score-stale {{ font-size: 11px; color: #92400e; margin-top: 8px; }}
  .nba-score-flip {{ font-size: 11px; color: #1e40af; margin-top: 6px; font-weight: 600; }}
  .nba-model-details {{ margin: 8px 0 16px; border: 1px solid var(--color-border); background: var(--color-bg); padding: 4px 16px 16px; }}
  .nba-model-details > summary {{
    cursor: pointer; font-family: var(--font-serif); font-size: 18px; font-weight: 500;
    padding: 14px 0; list-style: none; color: var(--color-text-muted);
  }}
  .nba-model-details > summary::-webkit-details-marker {{ display: none; }}
  .nba-model-tag {{ font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }}
  .nba-model-agree {{ background: #dcfce7; color: #166534; }}
  .nba-model-disagree {{ background: #fee2e2; color: #991b1b; }}
  .nba-model-neutral {{ background: #f3f4f6; color: #374151; }}
  .nba-sharp-tag {{ font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }}
  .nba-sharp-with {{ background: #dbeafe; color: #1e40af; }}
  .nba-sharp-against {{ background: #ffedd5; color: #9a3412; }}
  .nba-sharp-none {{ background: #f3f4f6; color: #4b5563; }}
  .nba-sharp-nodata {{ background: transparent; color: #9ca3af; font-weight: 600; }}
  .nba-content .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  @media (max-width: 640px) {{
    .nba-content .plays-table thead {{ display: none; }}
    .nba-content .plays-table tr {{ display: block; border: 1px solid var(--color-border); margin-bottom: 10px; padding: 8px 10px; }}
    .nba-content .plays-table td {{ display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border: none; }}
    .nba-content .plays-table td::before {{ content: attr(data-label); font-weight: 700; font-size: 10px; text-transform: uppercase; color: var(--color-text-muted); }}
  }}
"""

NBA_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBA tracking (testing) · Sharp Scout Quant</title>
<meta name="description" content="NBA Sharp Scout and Pace of Play paper tracking — testing only">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="apple-touch-icon" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{site_css}
{bottom_bar_css}
""" + _NBA_SHARED_PAGE_CSS + """
</style>
</head>
<body class="{body_class}">
<div class="nba-test-banner" role="alert">NBA paper tracking — testing only. Not NFL Sharp Plays.</div>
<div class="board-nav">
  {site_tabs}
  <div class="board-updated-bar" role="status">
    <span class="board-updated-label">NBA shadow board</span>
    <span class="board-updated-time">{mode_note} · Updated {updated} · Next scan {next_scan}</span>
  </div>
</div>
<header class="header">
  <div class="header-inner">
    <div class="header-logo">{ssq_logo}</div>
    <div class="header-text">
      <h1>NBA tracking board</h1>
      <p>Pace of Play and Sharp Scout game-line paper picks. Player props live on <a href="nba-props.html">NBA Props</a>. {window_note}</p>
    </div>
  </div>
</header>
<div class="nba-content">
  <section class="nba-model-panel pace-panel" aria-labelledby="pace-heading">
    <h2 class="nba-h2" id="pace-heading">Pace of Play model</h2>
    <p class="nba-section-note">Possession-pace projections vs consensus (injury-adjusted when available). Plays need ≥{pace_play_threshold} pt gap.</p>
    {pace_lines_note}
    {pace_compact_record}
    <div class="nba-plays-block">
      <div class="section-label">Upcoming plays</div>
      {pace_plays_html}
    </div>
    {pace_shadow_html}
    <details class="nba-section-details">
      <summary>{pace_watch_list_label}, projections &amp; history</summary>
      <p class="nba-section-note">{pace_auto_secondary}</p>
      <div class="nba-leans-block">
        <div class="section-label">{pace_watch_list_label} ({pace_lean_range} pt gap)</div>
        <p class="nba-section-note">{pace_watch_list_note}</p>
        {pace_leans_html}
      </div>
      <div class="section-label">Today&apos;s slate projections</div>
      {pace_projections_html}
      {pace_totals_shadow_html}
      <div class="section-label">Results tracking</div>
      {pace_history_html}
    </details>
  </section>

  <section class="nba-model-panel sharp-panel" aria-labelledby="sharp-scout-heading">
    <h2 class="nba-h2" id="sharp-scout-heading">Sharp Scout model</h2>
    <p class="nba-section-note">Price-edge paper plays on spreads and totals (EV floor, Kelly sizing). Paper only — never live bets.</p>
    {sharp_compact_record}
    <p class="nba-section-note">{sharp_record_note}</p>
    <div class="nba-plays-block">
      <div class="section-label">Upcoming plays</div>
      {sharp_plays_html}
    </div>
    <details class="nba-section-details">
      <summary>Leans &amp; graded history</summary>
      <div class="nba-leans-block">
        <div class="section-label">Leans (near-miss EV, 0u)</div>
        {sharp_leans_html}
      </div>
      <div class="section-label">Results tracking (game lines)</div>
      {sharp_history_html}
    </details>
  </section>

  <details class="nba-model-details">
    <summary>Diagnostics &amp; export tables</summary>
    {model_details}
  </details>
</div>
<div class="footer">
  Sharp Scout Quant · research and entertainment only · not betting advice.
</div>
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""

NBA_PROPS_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBA Props (testing) · Sharp Scout Quant</title>
<meta name="description" content="NBA Sharp Scout player prop paper tracking — testing only">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="apple-touch-icon" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{site_css}
{bottom_bar_css}
""" + _NBA_SHARED_PAGE_CSS + """
</style>
</head>
<body class="{body_class}">
<div class="nba-test-banner" role="alert">NBA paper tracking — testing only. Not NFL Sharp Plays.</div>
<div class="board-nav">
  {site_tabs}
  <div class="board-updated-bar" role="status">
    <span class="board-updated-label">NBA props board</span>
    <span class="board-updated-time">{mode_note} · Updated {updated} · Next scan {next_scan}</span>
  </div>
</div>
<header class="header">
  <div class="header-inner">
    <div class="header-logo">{ssq_logo}</div>
    <div class="header-text">
      <h1>NBA player props</h1>
      <p>Sharp Scout price-edge prop picks (max five per game). Game lines and Pace of Play are on <a href="nba.html">NBA</a>. {window_note}</p>
    </div>
  </div>
</header>
<div class="nba-content">
  <section class="nba-model-panel props-panel" aria-labelledby="nba-props-heading">
    <h2 class="nba-h2" id="nba-props-heading">Today&apos;s prop plays</h2>
    <p class="nba-section-note">Props may be skipped on scheduled scans until the paper window opens; this page updates when props are included in a scan.</p>
    {props_compact_record}
    <div class="nba-plays-block">
      <div class="section-label">Upcoming plays</div>
      {prop_plays_html}
    </div>
    <details class="nba-section-details">
      <summary>Leans &amp; prop history</summary>
      <div class="nba-leans-block">
        <div class="section-label">Leans (near-miss EV, 0u)</div>
        {prop_leans_html}
      </div>
      <div class="section-label">Graded prop plays</div>
      {prop_history_html}
    </details>
  </section>

  <details class="nba-model-details">
    <summary>Export tables</summary>
    <h4 class="nba-h4">Qualifying prop picks</h4>
    {prop_picks_table}
    <h4 class="nba-h4">Near-miss props</h4>
    {prop_possible_table}
  </details>
</div>
<div class="footer">
  Sharp Scout Quant · research and entertainment only · not betting advice.
</div>
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""
