"""Public GitHub Pages slice for NBA shadow / paper-trading (testing only)."""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from sharp_scout.config import ROOT, get_settings
from sharp_scout.copy.explain import format_kickoff_compact, format_kickoff_et, kickoff_sort_key
from sharp_scout.nba import paths as nba_paths
from sharp_scout.utils.slate import ET, parse_commence

DOCS_DIR = ROOT / "docs"

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

NBA_SCAN_SLOTS_ET = ((10, 30), (17, 30))


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


def score_modeling_display_plays(
    rows: list[dict[str, Any]],
    *,
    min_edge: float = SCORE_MODELING_MIN_EDGE_PT,
) -> list[dict[str, Any]]:
    """One display card per game where model vs consensus spread/total gap >= min_edge."""
    from sharp_scout.nba.score_model.injury_adjust import format_absence_line

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
        candidates = adj_candidates or raw_candidates
        if not candidates and not raw_candidates:
            continue
        primary = max(candidates, key=lambda c: c["gap"])
        raw_primary = max(raw_candidates, key=lambda c: c["gap"]) if raw_candidates else None
        secondary = [c for c in candidates if c is not primary]
        absence_lines: list[str] = []
        for team, key in ((home, "home_absences"), (away, "away_absences")):
            for row in r.get(key) or []:
                if row.get("kind") == "return" or abs(float(row.get("margin_pts") or 0)) >= 0.3:
                    absence_lines.append(format_absence_line(team, row))
        raw_gap = raw_primary["signed_gap"] if raw_primary else None
        adj_gap = primary["signed_gap"]
        flip = False
        if raw_primary and _qualifies_play(raw_candidates) != _qualifies_play(adj_candidates):
            flip = True
        elif raw_primary and raw_primary.get("kind") == primary.get("kind"):
            if (raw_gap or 0) * adj_gap < 0 and abs(adj_gap) >= min_edge:
                flip = True
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
                "raw_model_line": raw_primary["model_line"] if raw_primary else f"Proj margin {margin:+.1f}",
                "injury_model_line": primary["model_line"],
                "secondary": secondary,
                "absence_lines": absence_lines,
                "injury_news_after_line": bool(r.get("injury_news_after_line")),
                "injury_play_flip": flip,
            }
        )
    out.sort(key=lambda x: float(x.get("gap") or 0), reverse=True)
    return out


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


def _next_nba_scan_et(now: datetime | None = None) -> datetime:
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(ET)
    else:
        now = now.astimezone(ET)
    for hour, minute in NBA_SCAN_SLOTS_ET:
        slot = datetime.combine(now.date(), time(hour, minute), tzinfo=ET)
        if slot > now:
            return slot
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(NBA_SCAN_SLOTS_ET[0][0], NBA_SCAN_SLOTS_ET[0][1]), tzinfo=ET)


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


def _render_nba_play_card(play: dict[str, Any], *, badge: str, badge_cls: str, card_cls: str) -> str:
    settings = get_settings()
    unit_d = float(settings.nba_unit_dollars)
    kick = format_kickoff_et(play.get("kickoff"))
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    title = _price_edge_card_title(play)
    book = _book_label(play.get("book"))
    price = _price(play.get("price"))
    units = play.get("units")
    units_f = float(units) if isinstance(units, (int, float)) else None
    units_s = f"{units_f:.2f}u" if units_f is not None else "—"
    stake_s = f"${units_f * unit_d:.0f}" if units_f is not None else "—"
    edge = play.get("edge")
    edge_s = _pct(edge)
    fair = play.get("p_true") if play.get("p_true") is not None else play.get("p_fair")
    fair_s = _pct(fair)
    sub_parts = [kick, f"{away} @ {home}", f"{book} {price}"]
    if play.get("play_type") == "prop":
        sub_parts.insert(1, "Prop")
    subtitle = " · ".join(sub_parts)
    tags = _model_sharp_tags(play)
    return f"""
      <div class="play-card {card_cls} nba-pick-card">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge {badge_cls}">{_esc(badge)}</span>
            <div class="play-title">{_esc(title)}</div>
            <div class="play-subtitle">{_esc(subtitle)}</div>
          </div>
          <div class="units-badge">{units_s}<span class="nba-stake-dollars">{stake_s}</span></div>
        </div>
        {tags}
        <div class="play-meta">
          <div class="meta-item"><span class="meta-label">EV </span><span class="meta-val pos">{edge_s}</span></div>
          <div class="meta-item"><span class="meta-label">Fair </span><span class="meta-val">{fair_s}</span></div>
          <div class="meta-item"><span class="meta-label">Tip </span><span class="meta-val">{_esc(kick)}</span></div>
          <div class="meta-item"><span class="meta-label">Book </span><span class="meta-val">{_esc(book)} {_esc(price)}</span></div>
        </div>
      </div>"""


def _render_price_edge_cards(picks: list[dict[str, Any]]) -> str:
    ordered = sorted(picks, key=lambda p: kickoff_sort_key(p.get("kickoff")))
    if not ordered:
        return ""
    return "\n".join(
        _render_nba_play_card(p, badge="Price-edge pick", badge_cls="badge-play", card_cls="sharp-play")
        for p in ordered
    )


def _render_score_modeling_card(item: dict[str, Any]) -> str:
    kick = format_kickoff_et(item.get("kickoff"))
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
    return f"""
      <div class="play-card candidate nba-pick-card nba-score-card">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge badge-cand">Pace of Play model</span>
            <div class="play-title">{_esc(str(item.get("title") or ""))}</div>
            <div class="play-subtitle">{_esc(item.get("game") or "")} · {_esc(kick)}</div>
          </div>
          <div class="units-badge nba-gap-badge">{float(item.get("gap") or 0):.1f} pt</div>
        </div>
        <div class="play-meta">
          <div class="meta-item"><span class="meta-label">Injury </span><span class="meta-val">{_esc(item.get("injury_model_line") or item.get("model_line") or "")}</span></div>
          <div class="meta-item"><span class="meta-label">Raw </span><span class="meta-val">{_esc(item.get("raw_model_line") or "")}</span></div>
          <div class="meta-item"><span class="meta-label">Market </span><span class="meta-val">{_esc(item.get("consensus_line") or "")}</span></div>
          <div class="meta-item"><span class="meta-label">Gap </span><span class="meta-val">{_esc(gap_s)}{(" · " + _esc(raw_gap_s)) if raw_gap_s else ""}</span></div>
        </div>
        {abs_html}
        {stale}
        {flip}
        {extra}
      </div>"""


def _render_score_modeling_cards(plays: list[dict[str, Any]]) -> str:
    if not plays:
        return ""
    return "\n".join(_render_score_modeling_card(p) for p in plays)


def _render_picks_empty(*, live_scan: bool, updated: str, next_scan: str) -> str:
    if not live_scan:
        return (
            f'<div class="nba-picks-empty" role="status">'
            f"<p>{_esc(NO_LIVE_SCAN_MESSAGE)}</p>"
            f"<p class=\"nba-picks-empty-sub\">Scans run at 10:30 AM and 5:30 PM ET. "
            f"Next scan {_esc(next_scan)}.</p></div>"
        )
    return (
        f'<div class="nba-picks-empty" role="status">'
        f"<p><strong>No NBA price-edge picks yet today.</strong></p>"
        f"<p class=\"nba-picks-empty-sub\">Last updated {_esc(updated)}. "
        f"Next scan {_esc(next_scan)} (10:30 AM &amp; 5:30 PM ET).</p></div>"
    )


def _render_score_modeling_empty(*, live_scan: bool) -> str:
    if not live_scan:
        return ""
    return (
        '<div class="nba-picks-empty nba-picks-empty-soft" role="status">'
        f"<p>No Pace of Play plays right now (need ≥{SCORE_MODELING_MIN_EDGE_PT:g} pt gap vs consensus).</p>"
        "</div>"
    )


def _render_score_model_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No score-model projections yet (logged on live scans).</p>'
    body = []
    for r in rows:
        game = f"{r.get('away', '')} @ {r.get('home', '')}"
        score = f"{r.get('away_pts', '—')}-{r.get('home_pts', '—')}"
        lines = r.get("lines") or {}
        spr = lines.get("consensus_spread_home")
        tot = lines.get("consensus_total")
        body.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(r.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Proj score">{_esc(score)}</td>'
            f'<td data-label="Margin">{float(r.get("margin") or 0):+.1f}</td>'
            f'<td data-label="Total">{float(r.get("total") or 0):.1f}</td>'
            f'<td data-label="Consensus">{_esc(spr)} / {_esc(tot)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Game</th><th>Proj score</th><th>Margin</th><th>Total</th>"
        "<th>Consensus spr/tot</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


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


def render_nba_page_html(
    *,
    signals_payload: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    report: dict[str, Any] | None,
    analytics_head: str,
    score_model_rows: list[dict[str, Any]] | None = None,
    injury_lag_rows: list[dict[str, Any]] | None = None,
    score_model_summary: dict[str, Any] | None = None,
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
    next_scan = _format_timestamp_et(_next_nba_scan_et())

    body_class = "ss-bottom-bar"
    mode_note = "Live shadow scan" if live_scan else "Awaiting live scan"

    price_edge_cards = _render_price_edge_cards(picks) if live_scan else ""
    if live_scan and not price_edge_cards:
        price_edge_section = _render_picks_empty(live_scan=True, updated=updated, next_scan=next_scan)
    elif not live_scan:
        price_edge_section = _render_picks_empty(live_scan=False, updated=updated, next_scan=next_scan)
    else:
        price_edge_section = price_edge_cards

    score_rows = score_model_rows or []
    score_plays = score_modeling_display_plays(score_rows) if live_scan else []
    score_modeling_cards = _render_score_modeling_cards(score_plays) if live_scan else ""
    if live_scan and not score_modeling_cards:
        score_modeling_section = _render_score_modeling_empty(live_scan=True)
    else:
        score_modeling_section = score_modeling_cards

    score_record = _score_modeling_record_label(score_model_summary)
    score_record_html = (
        f'<span class="nba-section-record">{_esc(score_record)}</span>' if score_record else ""
    )

    game_picks_table = _render_candidate_rows(picks, kind="side") if live_scan else ""
    game_possible_table = _render_possible_rows(possible, kind="side") if live_scan else ""
    prop_picks_table = _render_candidate_rows(picks, kind="prop") if live_scan else ""
    prop_possible_table = _render_possible_rows(possible, kind="prop") if live_scan else ""

    record_rows = _record_by_bet_type(pub_ledger)
    record_block = _render_record_cards(record_rows)
    if not record_block:
        record_block = (
            '<p class="empty">No paper ledger yet. Run the NBA shadow scan to log test plays.</p>'
        )
    ledger_table = _render_ledger_rows(pub_ledger)
    score_block = _render_score_model_block(score_rows) if live_scan else ""
    injury_block = _render_injury_lag_block(injury_lag_rows or []) if live_scan else ""
    mf = pub_report.get("model_filter") or {}
    mf_bits = []
    for key in ("agree", "disagree", "neutral"):
        row = mf.get(key)
        if row and row.get("n"):
            mf_bits.append(f"{key}: {row.get('record')} ({row.get('units')}u)")
    model_filter_note = " · ".join(mf_bits) if mf_bits else "Model filter splits appear after graded side/total plays."
    sm = pub_report.get("sharp_money") or {}
    sharp_money_block = _render_sharp_money_table(sm) if live_scan else ""
    sm_bits = []
    for key, label in (
        ("with_sharps", "with sharps"),
        ("against_sharps", "against sharps"),
        ("no_signal", "no signal"),
    ):
        row = sm.get(key)
        if row and row.get("n"):
            sm_bits.append(f"{label}: {row.get('record')} ({row.get('units')}u)")
    sharp_money_note = (
        " · ".join(sm_bits)
        if sm_bits
        else "Sharp-money tag uses latest Action Network snapshot before tip (display only)."
    )

    model_details = f"""
    <h3 class="nba-h3">Paper record by bet type</h3>
    {record_block}
    <p class="nba-section-note">Price-gap plays vs score model (side-by-side): {_esc(model_filter_note)}</p>
    <h3 class="nba-h3">Sharp money (display only)</h3>
    <p class="nba-section-note">Action Network bet% vs money% — {_esc(sharp_money_note)}</p>
    {sharp_money_block}
    <h3 class="nba-h3">Score model paper track</h3>
    <p class="nba-section-note">Stage-3 possession ridge projections vs consensus/Pinnacle — frozen at tip, graded after ESPN finals.</p>
    {score_block}
    <h3 class="nba-h3">Injury lag (paper)</h3>
    <p class="nba-section-note">ESPN Out/Doubtful changes where the line may not have fully adjusted yet.</p>
    {injury_block}
    <h3 class="nba-h3">Near-miss candidates</h3>
    <p class="nba-section-note">Positive EV that did not qualify for the price-edge paper card. Not logged or graded.</p>
    <h4 class="nba-h4">Game lines</h4>
    {game_possible_table}
    <h4 class="nba-h4">Player props</h4>
    {prop_possible_table}
    <h3 class="nba-h3">Price-edge tables (export)</h3>
    <h4 class="nba-h4">Game line picks</h4>
    {game_picks_table}
    <h4 class="nba-h4">Prop picks</h4>
    {prop_picks_table}
    """

    in_window = pub_report.get("in_window")
    window = pub_report.get("paper_window") or {}
    window_s = ""
    if window.get("start") and window.get("end"):
        window_s = f"Paper window {window['start']} – {window['end']}. "
    window_flag = "In paper window." if in_window else "Outside paper window (testing only)."

    return NBA_PAGE_TEMPLATE.format(
        site_css=_SITE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        ssq_logo=_ssq_logo_svg(embedded=True),
        body_class=body_class,
        updated=_esc(updated),
        mode_note=_esc(mode_note),
        next_scan=_esc(next_scan),
        price_edge_section=price_edge_section,
        score_modeling_section=score_modeling_section,
        score_record_html=score_record_html,
        ledger_table=ledger_table,
        model_details=model_details,
        window_note=_esc(window_s + window_flag),
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
    for src_name in ("nba_score_model.json", "nba_injury_lag.json"):
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

    html = render_nba_page_html(
        signals_payload=signals_payload,
        ledger=ledger,
        report=report,
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        score_model_rows=score_model_rows,
        injury_lag_rows=injury_lag_rows,
        score_model_summary=score_model_summary,
    )
    (out / "nba.html").write_text(html)
    return out / "nba.html"


NBA_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBA (testing) · Sharp Scout Quant</title>
<meta name="description" content="NBA game lines and player props — paper testing only">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="apple-touch-icon" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{site_css}
{bottom_bar_css}
  .nba-wrap {{ max-width: 1200px; margin: 0 auto; padding: 0 20px 48px; }}
  .nba-test-banner {{
    background: #fef3c7; border: 2px solid #d97706; color: #92400e;
    text-align: center; font-weight: 800; font-size: 16px; padding: 14px 16px; margin: 0;
  }}
  .nba-hero {{ text-align: center; padding: 24px 16px 8px; }}
  .nba-hero h1 {{ font-family: var(--font-serif); font-size: 38px; font-weight: 500; margin: 10px 0 4px; }}
  .nba-hero p {{ color: var(--color-text-muted); font-size: 14px; font-weight: 300; }}
  .nba-note {{ font-size: 13px; color: var(--color-text-muted); margin: 8px 0 20px; line-height: 1.55; }}
  .nba-h2 {{ font-family: var(--font-serif); font-size: 24px; font-weight: 500; margin: 28px 0 8px; display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 12px; }}
  .nba-h2-sub {{ font-family: var(--font-sans); font-size: 13px; font-weight: 600; color: var(--color-text-muted); letter-spacing: 0.02em; }}
  .nba-h3 {{ font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 18px 0 8px; }}
  .nba-h4 {{ font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: .06em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 14px 0 6px; }}
  .nba-section-note {{ font-size: 12.5px; color: var(--color-text-muted); margin: 0 0 10px; line-height: 1.5; }}
  .nba-section-record {{ font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--color-text-muted); }}
  .nba-lean-cell {{ max-width: 520px; }}
  .nba-lean-main {{ font-size: 14px; line-height: 1.45; margin-bottom: 4px; }}
  .nba-lean-meta {{ font-size: 12px; color: var(--color-text-muted); line-height: 1.4; }}
  .nba-book {{ font-family: var(--font-mono); font-size: 11px; color: var(--color-text-muted); }}
  .nba-record-grid {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; margin: 16px 0; }}
  .nba-rec-card {{ border: 1px solid var(--color-border); border-radius: 8px; padding: 12px 16px; min-width: 140px; text-align: center; }}
  .nba-rec-lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--color-text-muted); }}
  .nba-rec-val {{ font-size: 22px; font-weight: 800; margin: 4px 0; }}
  .nba-rec-sub {{ font-size: 11px; color: var(--color-text-muted); }}
  .nba-wrap .table-wrap {{ overflow-x: auto; }}
  .nba-picks-empty {{
    border: 2px solid var(--color-border); background: var(--color-bg);
    padding: 18px 16px; margin: 0 0 12px; line-height: 1.55; font-size: 15px;
  }}
  .nba-picks-empty-soft {{ border-style: dashed; font-size: 14px; color: var(--color-text-muted); }}
  .nba-picks-empty-sub {{ font-size: 13px; color: var(--color-text-muted); margin-top: 8px; font-weight: 400; }}
  .nba-pick-cards {{ margin: 0 0 8px; }}
  .nba-pick-card {{ margin-bottom: 12px; }}
  .nba-pick-card .play-title {{ font-size: clamp(20px, 5vw, 24px); }}
  .nba-stake-dollars {{ display: block; font-size: 10px; font-weight: 500; color: var(--color-text-muted); margin-top: 2px; }}
  .nba-tag-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }}
  .nba-gap-badge {{ font-size: 11px; letter-spacing: 0.04em; }}
  .nba-score-secondary {{ font-size: 12px; color: var(--color-text-muted); margin-top: 10px; line-height: 1.45; }}
  .nba-score-absences {{ font-size: 12px; line-height: 1.5; margin-top: 10px; color: var(--color-text); }}
  .nba-score-stale {{ font-size: 11px; color: #92400e; margin-top: 8px; }}
  .nba-score-flip {{ font-size: 11px; color: #1e40af; margin-top: 6px; font-weight: 600; }}
  .nba-model-details {{ margin: 28px 0 16px; border: 1px solid var(--color-border); background: var(--color-bg); padding: 4px 16px 16px; }}
  .nba-model-details > summary {{
    cursor: pointer; font-family: var(--font-serif); font-size: 20px; font-weight: 500;
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
  @media (max-width: 640px) {{
    .nba-hero h1 {{ font-size: 29px; }}
    .nba-wrap .plays-table thead {{ display: none; }}
    .nba-wrap .plays-table tr {{ display: block; border: 1px solid var(--color-border); margin-bottom: 10px; padding: 8px 10px; }}
    .nba-wrap .plays-table td {{ display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border: none; }}
    .nba-wrap .plays-table td::before {{ content: attr(data-label); font-weight: 700; font-size: 10px; text-transform: uppercase; color: var(--color-text-muted); }}
  }}
</style>
</head>
<body class="{body_class}">
<div class="nba-test-banner" role="alert">This is just for testing.</div>
<div class="tabs" role="navigation" aria-label="Sections">
  <a class="tab tab-home" href="index.html">Today's plays</a>
  <a class="tab" href="board.html#tab-plays">Results</a>
  <a class="tab" href="board.html#tab-guide">How it works</a>
  <a class="tab tab-aux" href="comments.html">Comments</a>
  <a class="tab tab-aux" href="props.html">NFL Props</a>
  <span class="tab active">NBA (test)</span>
</div>
<div class="nba-wrap">
  <div class="nba-hero">
    {ssq_logo}
    <h1>NBA — paper testing</h1>
    <p>{mode_note} · updated {updated} · next scan {next_scan}</p>
  </div>
  <p class="nba-note">
    Paper/test plays only — not Sharp Plays, not on the NFL card, and not graded on football records.
    {window_note}
    Price-edge picks use quarter-Kelly staking with caps ($10/unit). Pace of Play model is display-only (≥3 pt vs consensus).
  </p>
  <h2 class="nba-h2">Price-edge picks <span class="nba-h2-sub">Sharp Scout model</span></h2>
  <p class="nba-section-note">Qualifying paper card plays (EV floor, sharp fair, Kelly sizing, portfolio caps).</p>
  <div class="nba-pick-cards">{price_edge_section}</div>
  <h2 class="nba-h2">Pace of Play model {score_record_html}</h2>
  <p class="nba-section-note">Pace-of-play score model vs consensus — raw and injury-adjusted gaps (≥3 pt, display only). Player teams from live ESPN rosters.</p>)
  <div class="nba-pick-cards">{score_modeling_section}</div>
  <h2 class="nba-h2">Graded paper results</h2>
  {ledger_table}
  <details class="nba-model-details">
    <summary>Model details</summary>
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
