"""Public GitHub Pages slice for NBA shadow / paper-trading (testing only)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from sharp_scout.config import ROOT, get_settings
from sharp_scout.copy.explain import format_kickoff_compact, format_kickoff_et, kickoff_sort_key, side_team
from sharp_scout.ledger.day_record import (
    filter_graded_on_et_day,
    graded_status,
    play_et_calendar_date,
    summarize_graded_plays,
    yesterday_et,
)
from sharp_scout.nba import paths as nba_paths
from sharp_scout.nba.schedule_guard import NBA_SCAN_SCHEDULE_LABEL, next_nba_scan_et
from sharp_scout.nba.slate_et import (
    format_et_slate_day_label,
    format_kickoff_day_time_et,
    group_items_by_kickoff_et_date,
    kickoff_date_et,
    upcoming_slate_items,
)
from sharp_scout.utils.kickoff import parse_kickoff_utc
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
PLAY_BADGE_LABEL = "Play"
TRACKING_ONLY_BADGE_LABEL = "Tracking only, not a bet"
SHARP_LEANS_SECTION_LABEL = "Near-miss Sharp Scout (tracking only, not bets)"


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
    if market == "h2h":
        return f"{side_team(play)} ML"
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
    kinds: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if cs is not None and (kinds is None or "spread" in kinds):
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
    if ct is not None and (kinds is None or "total" in kinds):
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
        f"gap {abs(gap):.1f} pts."
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
        f"gap {abs(gap):.1f} pts ({side})."
    )


OFFICIAL_PACE_MARKET_KINDS = frozenset({"total"})
PACE_SPREAD_SHADOW_KINDS = frozenset({"spread"})


def score_modeling_display_plays(
    rows: list[dict[str, Any]],
    *,
    min_edge: float = SCORE_MODELING_MIN_EDGE_PT,
    max_edge: float | None = None,
    include_injury_watch: bool = False,
    kinds: frozenset[str] | None = None,
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
            kinds=kinds,
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
            kinds=kinds,
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
    """Near-miss score-model spots: gap in [min_edge, max_edge) vs consensus (research helper)."""
    return score_modeling_display_plays(
        rows,
        min_edge=min_edge,
        max_edge=max_edge,
        include_injury_watch=False,
    )


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


def _open_game_line_plays_today_et(
    ledger: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Unsettled Sharp Scout game-line rows on today's ET slate (board fallback)."""
    now = now or datetime.now(timezone.utc)
    today_et = now.astimezone(ET).date()
    out: list[dict[str, Any]] = []
    for play in (ledger or {}).get("plays") or []:
        if not _is_sharp_game_line_play(play):
            continue
        st = str(play.get("status") or "").lower()
        if st in ("win", "loss", "push", "void"):
            continue
        day = play_et_calendar_date(play)
        if day != today_et:
            continue
        out.append(play)
    return out


def _merge_signals_with_todays_open_ledger(
    signals: list[dict[str, Any]],
    ledger: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    merged = list(signals)
    seen = {str(p.get("event_id") or "") for p in merged if p.get("event_id")}
    for play in _open_game_line_plays_today_et(ledger):
        eid = str(play.get("event_id") or "")
        if eid and eid in seen:
            continue
        merged.append(play)
        if eid:
            seen.add(eid)
    return merged


def _play_in_progress_badge_html(play: dict[str, Any], *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    kick = parse_kickoff_utc(play.get("kickoff"))
    if kick is None:
        return ""
    st = str(play.get("status") or "").lower()
    if st in ("win", "loss", "push", "void"):
        return ""
    if kick >= now - timedelta(minutes=15):
        return ""
    return '<span class="nba-progress-badge">In progress</span>'


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


def _play_badge_label() -> str:
    """Badge text for qualifying paper plays (not tracking / shadow rows)."""
    return PLAY_BADGE_LABEL


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


def _nba_yesterday_totals_summary(pub_ledger: dict[str, Any]) -> dict[str, Any]:
    day = yesterday_et()
    rows: list[dict[str, Any]] = []
    from sharp_scout.config import nba_pace_of_play_active

    if nba_pace_of_play_active():
        from sharp_scout.nba.score_model.official_pace import load_official_pace

        for p in load_official_pace().get("plays") or []:
            if play_et_calendar_date(p) != day or graded_status(p) not in ("win", "loss", "push"):
                continue
            rows.append(
                {
                    "status": graded_status(p),
                    "pnl_units": p.get("units"),
                    "units": 1.0,
                }
            )
    rows.extend(
        filter_graded_on_et_day(
            pub_ledger.get("plays") or [],
            day,
            include=lambda p: (p.get("play_type") or "side") == "side" and p.get("market") == "totals",
        )
    )
    out = summarize_graded_plays(rows)
    out["day_label"] = day.strftime("%a %b %-d")
    return out


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
    market = str(play.get("market") or "")
    line = play.get("line")
    if market == "h2h":
        detail = f"ML {_price(play.get('price'))}".strip()
    else:
        line_s = f"{float(line):g}" if isinstance(line, (int, float)) else "—"
        detail = f"Line {line_s}"
    units = play.get("units")
    units_f = float(units) if isinstance(units, (int, float)) else None
    units_s = f"{units_f:.2f}u" if units_f is not None else "—"
    stake_s = f"${units_f * unit_d:.0f}" if units_f is not None else "—"
    edge = play.get("edge")
    edge_s = _pct(edge)
    fair = play.get("p_true") if play.get("p_true") is not None else play.get("p_fair")
    fair_s = _pct(fair)
    sub_parts = [f"{away} @ {home}", _market_label(play), detail]
    if play.get("play_type") == "prop":
        sub_parts.insert(1, "Prop")
    subtitle = " · ".join(sub_parts)
    if not badge:
        badge = _play_badge_label()
    tags = _model_sharp_tags(play)
    progress_badge = _play_in_progress_badge_html(play)
    stake_block = (
        f'<div class="units-badge">{units_s}<span class="nba-stake-dollars">{stake_s}</span></div>'
        if show_stake
        else (
            '<div class="units-badge nba-lean-units nba-tracking-units">'
            "0u · not a bet</div>"
        )
    )
    return f"""
      <div class="play-card {card_cls} nba-pick-card">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge {badge_cls}">{_esc(badge)}</span>
            {progress_badge}
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
            badge=_play_badge_label(),
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
            badge=TRACKING_ONLY_BADGE_LABEL,
            badge_cls="badge-tracking",
            card_cls="sharp-tracking",
            show_stake=False,
            reference=ref,
        )

    return _render_et_date_grouped_cards(possible, render_one=render_one, reference=ref)


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
    return {"spreads": "Spread", "totals": "Total", "h2h": "H2H"}.get(m, m.title())


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
        # Rejection reasons name internal thresholds — keep them off the public page.
        meta = f"EV {_pct(p.get('edge'))} · Did not qualify · 0u (display only)"
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
            f'<td data-label="Units">{units_s}</td>'
            f'<td data-label="Signals">{tags}</td>'
            "</tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Tip</th><th>Game</th><th>Player</th><th>Market</th>"
        "<th>Pick</th><th>Line</th><th>Book / price</th><th>EV</th><th>Units</th>"
        "<th>Signals</th>"
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

    picks = _merge_signals_with_todays_open_ledger(
        list(pub_signals.get("signals") or []),
        pub_ledger,
    )
    possible = list(pub_signals.get("possible_signals") or [])
    generated = parse_commence(pub_signals.get("generated_at"))
    updated = _format_timestamp_et(generated) if generated else "—"
    next_scan = _format_timestamp_et(next_nba_scan_et())

    body_class = "ss-bottom-bar"
    mode_note = "Live shadow scan" if live_scan else "Awaiting live scan"

    sharp_game_lines = _sharp_scout_record_summary(pub_ledger, game_lines_only=True)

    slate_ref = _slate_reference_date()
    picks_slate = upcoming_slate_items(picks)
    possible_slate = upcoming_slate_items(possible)
    side_picks_slate = [p for p in picks_slate if (p.get("play_type") or "side") != "prop"]
    side_possible_slate = [p for p in possible_slate if (p.get("play_type") or "side") != "prop"]

    sharp_plays_html = (
        _render_price_edge_cards(side_picks_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not sharp_plays_html:
        if not _open_game_line_plays_today_et(pub_ledger):
            sharp_plays_html = _render_picks_empty(
                live_scan=True, updated=updated, next_scan=next_scan
            )
    elif not live_scan:
        sharp_plays_html = _render_picks_empty(live_scan=False, updated=updated, next_scan=next_scan)

    sharp_leans_html = (
        _render_sharp_lean_cards(side_possible_slate, reference=slate_ref) if live_scan else ""
    )
    if live_scan and not sharp_leans_html:
        sharp_leans_html = (
            '<p class="empty nba-leans-empty">No Sharp Scout leans today — near-miss EV spots will show here.</p>'
        )

    sharp_history_html = _render_sharp_graded_history(pub_ledger)

    gl_range = sharp_game_lines.get("date_range_et") or "—"
    sharp_compact_record = _render_compact_record(
        record=sharp_game_lines.get("record") or "—",
        win_pct=sharp_game_lines.get("win_pct") or "—",
        units=float(sharp_game_lines.get("units") or 0),
        label=f"Game lines · {gl_range} ET",
    )
    nba_yest = _nba_yesterday_totals_summary(pub_ledger)
    yest_win = (
        f"{nba_yest['win_pct'] * 100:.0f}%"
        if nba_yest.get("win_pct") is not None
        else "—"
    )
    yesterday_compact_record = _render_compact_record(
        record=nba_yest["record"] if nba_yest.get("n") else "—",
        win_pct=yest_win,
        units=float(nba_yest.get("pnl_units") or 0),
        label=f"Yesterday totals · {nba_yest['day_label']}",
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
            "Spreads and totals only. "
            "Oct 24–26 ET includes pre-window shadow testing; configured paper window starts "
            f"{window.get('start', '—')}."
        ),
        yesterday_compact_record=yesterday_compact_record,
        model_details=model_details,
        sharp_leans_section_label=SHARP_LEANS_SECTION_LABEL,
        play_badge_label=PLAY_BADGE_LABEL,
        tracking_only_badge=TRACKING_ONLY_BADGE_LABEL,
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
        site_tabs=render_site_tabs(active="nba"),
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
        sharp_leans_section_label=SHARP_LEANS_SECTION_LABEL,
        play_badge_label=PLAY_BADGE_LABEL,
        tracking_only_badge=TRACKING_ONLY_BADGE_LABEL,
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
    try:
        from sharp_scout.nba.ledger import save_nba_ledger as _save_led
        from sharp_scout.nba.overrides import apply_nba_ledger_overrides, drop_voided_signals, load_nba_overrides

        _ovs = load_nba_overrides()
        if _ovs:
            if ledger and apply_nba_ledger_overrides(ledger, _ovs):
                _save_led(ledger)
            if signals_payload:
                signals_payload = dict(signals_payload)
                for _k in ("signals", "possible_signals"):
                    if isinstance(signals_payload.get(_k), list):
                        signals_payload[_k] = drop_voided_signals(signals_payload[_k], _ovs)
                signals_payload["n_signals"] = len(signals_payload.get("signals") or [])
                signals_payload["n_possible"] = len(signals_payload.get("possible_signals") or [])
    except Exception:  # noqa: BLE001
        pass
    live_scan = has_live_nba_scan(signals_payload)

    pub_signals = public_nba_signals(signals_payload)
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    # Only the display/result ledger is published. Signals, the paper report and the
    # Score-model / injury files stay in data/ (docs/ is the GitHub Pages root).
    from sharp_scout.site.build import PUBLIC_PLAY_FIELDS

    pub_ledger_out = {
        k: v for k, v in (pub_ledger or {}).items() if k not in ("plays", "calibration_bins")
    }
    pub_ledger_out["plays"] = [
        {k: p[k] for k in PUBLIC_PLAY_FIELDS if k in p} for p in ((pub_ledger or {}).get("plays") or [])
    ]
    (out / "nba_ledger.json").write_text(json.dumps(pub_ledger_out, indent=2, default=str) + "\n")
    for stale_name in (
        "nba_latest_signals.json",
        "nba_paper_report.json",
        "nba_score_model.json",
        "nba_injury_lag.json",
        "nba_pace_of_play_official.json",
        "nba_pace_of_play_official.csv",
    ):
        (out / stale_name).unlink(missing_ok=True)

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
    if get_settings().site_player_props_enabled:
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
  .nba-model-panel.sharp-panel {{ border-top: 4px solid var(--color-win); }}
  .nba-model-panel.props-panel {{ border-top: 4px solid #7c3aed; }}
  .nba-h2 {{ font-family: var(--font-serif); font-size: clamp(24px, 5vw, 28px); font-weight: 500; margin: 0 0 8px; }}
  .nba-h3 {{ font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 18px 0 8px; }}
  .nba-h4 {{ font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .06em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 14px 0 6px; }}
  .nba-section-note {{ font-size: 12.5px; color: var(--color-text-muted); margin: 0 0 12px; line-height: 1.5; }}
  .nba-rec-row {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 14px; }}
  .nba-rec-row .nba-rec-chip {{ flex: 1 1 260px; margin: 0; }}
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
  .nba-tracking-block {{
    border: 1px dashed #cbd5e1; background: #f8fafc; padding: 12px 12px 4px; margin: 0 0 16px;
  }}
  .nba-tracking-block .section-label {{ color: #64748b; }}
  .sharp-tracking {{
    border-left-color: #94a3b8; background: #f8fafc; border-color: #e2e8f0;
  }}
  .sharp-tracking .play-title {{
    color: #475569; font-weight: 600; font-size: clamp(17px, 4.2vw, 22px);
  }}
  .sharp-tracking .nba-card-tip {{ color: #64748b; }}
  .badge-tracking {{
    background: #e2e8f0; color: #475569; border-color: #cbd5e1;
    font-size: 9px; letter-spacing: .04em; line-height: 1.35; max-width: 11rem;
    white-space: normal; text-transform: none;
  }}
  .nba-tracking-units {{ font-size: 10px; color: #64748b; }}
  .badge-play {{ font-weight: 700; letter-spacing: .12em; }}
  .nba-progress-badge {{
    display: inline-block; margin-left: 8px; font-family: var(--font-mono); font-size: 9px;
    font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #b45309;
    background: #fffbeb; border: 1px solid #fcd34d; padding: 2px 6px; border-radius: 4px;
  }}
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
<meta name="description" content="NBA Sharp Scout game-line paper tracking — testing only">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="icon" type="image/png" sizes="32x32" href="assets/favicon-32.png">
<link rel="icon" href="favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
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
      <p>Sharp Scout game-line paper picks (spreads and totals). {window_note}</p>
    </div>
  </div>
</header>
<div class="nba-content">
  <section class="nba-model-panel sharp-panel" aria-labelledby="sharp-scout-heading">
    <h2 class="nba-h2" id="sharp-scout-heading">Sharp Scout model</h2>
    <p class="nba-section-note">Paper plays on spreads and totals. Paper only — never live bets.</p>
    <div class="nba-rec-row">{sharp_compact_record}{yesterday_compact_record}</div>
    <p class="nba-section-note">{sharp_record_note}</p>
    <div class="nba-plays-block">
      <div class="section-label">Upcoming plays</div>
      <p class="nba-section-note">Qualifying picks show a <strong>{play_badge_label}</strong> badge with stake units.</p>
      {sharp_plays_html}
    </div>
    <details class="nba-section-details">
      <summary>Leans &amp; graded history</summary>
      <div class="nba-leans-block nba-tracking-block">
        <div class="section-label">{sharp_leans_section_label}</div>
        <p class="nba-section-note">{tracking_only_badge} — 0u paper tracking, not posted plays.</p>
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
<link rel="icon" type="image/png" sizes="32x32" href="assets/favicon-32.png">
<link rel="icon" href="favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
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
      <p>Sharp Scout price-edge prop picks (max five per game). Game lines are on <a href="nba.html">NBA</a>. {window_note}</p>
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
      <p class="nba-section-note">Qualifying props show a <strong>{play_badge_label}</strong> badge with stake units.</p>
      {prop_plays_html}
    </div>
    <details class="nba-section-details">
      <summary>Leans &amp; prop history</summary>
      <div class="nba-leans-block nba-tracking-block">
        <div class="section-label">{sharp_leans_section_label}</div>
        <p class="nba-section-note">{tracking_only_badge} — 0u paper tracking, not posted plays.</p>
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
