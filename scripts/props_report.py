#!/usr/bin/env python3
"""Render the latest player-props run as a shareable HTML/PDF card.

Reads artifacts/latest_props.json (written by scripts/run_props.py) and collapses the
raw rows — one per book, line, and side — down to the best available price per logical
bet.

    python scripts/run_props.py
    python scripts/props_report.py                    # full slate + Action splits
    python scripts/props_report.py --game NE@SEA      # single game
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import ARTIFACTS_DIR, get_settings  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

STYLES = """
  @page { margin: 14mm; }
  body { font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
          color: #111827; margin: 32px; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  h2.game { font-size: 18px; margin: 28px 0 8px; padding-top: 8px;
            border-top: 2px solid #e5e7eb; }
  h2.game:first-of-type { border-top: none; margin-top: 12px; }
  .sub { color: #6b7280; font-size: 13px; }
  .hdr { border-bottom: 3px solid #1d4ed8; padding-bottom: 14px; margin-bottom: 18px; }
  .warn { background: #fffbeb; border-left: 4px solid #d97706; padding: 12px 16px;
           border-radius: 4px; margin: 18px 0; font-size: 13px; }
  .stats { display: flex; gap: 28px; margin: 16px 0 26px; flex-wrap: wrap; }
  .stat b { display: block; font-size: 21px; }
  .stat span { color: #6b7280; font-size: 12px; text-transform: uppercase;
                letter-spacing: .04em; }
  .player { margin: 16px 0 22px; page-break-inside: avoid; }
  .player h3 { font-size: 15px; margin: 0 0 6px; }
  .player h3 small { color: #6b7280; font-weight: 400; margin-left: 8px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
  th { background: #111827; color: #fff; font-size: 11px; text-transform: uppercase;
        letter-spacing: .05em; padding: 8px; text-align: left; }
  td { padding: 8px; border-bottom: 1px solid #e5e7eb; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .side { font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 3px; }
  .over { background: #fee2e2; color: #991b1b; }
  .under { background: #dbeafe; color: #1e40af; }
  .alt { color: #b45309; font-size: 11px; font-weight: 600; }
  .splits { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
            padding: 10px 12px; margin: 8px 0 14px; font-size: 13px; }
  .splits h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase;
               letter-spacing: .06em; color: #475569; }
  .splits table th { background: #334155; }
  .muted { color: #94a3b8; font-size: 12px; }
  .foot { margin-top: 30px; padding-top: 14px; border-top: 2px solid #e5e7eb;
           color: #6b7280; font-size: 12px; }
  .idx td { font-size: 13px; }
"""


def collapse_best(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (player, market, side, line) — keep the best-priced book."""
    best: dict[tuple, dict[str, Any]] = {}
    for p in plays:
        key = (p.get("player_name"), p.get("market"), p.get("side"), p.get("line"))
        cur = best.get(key)
        if cur is None or (p.get("edge") or 0) > (cur.get("edge") or 0):
            best[key] = p
    return sorted(best.values(), key=lambda p: p.get("edge") or 0, reverse=True)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _an_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    if v <= 1.0:
        v *= 100.0
    return f"{v:.0f}%"


def _market_label(market: str) -> str:
    return market.replace("player_", "").replace("_", " ").title()


def _group_games(plays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for p in plays:
        away, home = str(p.get("away_team") or ""), str(p.get("home_team") or "")
        key = (away, home)
        if key not in buckets:
            buckets[key] = {
                "away_team": away,
                "home_team": home,
                "kickoff": p.get("kickoff") or p.get("commence_time"),
                "plays": [],
            }
        buckets[key]["plays"].append(p)
        if not buckets[key].get("kickoff") and p.get("kickoff"):
            buckets[key]["kickoff"] = p.get("kickoff")
    return sorted(buckets.values(), key=lambda g: str(g.get("kickoff") or ""))


def _fetch_action_splits(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from sharp_scout.data.action_network import ActionNetworkClient, slate_dates_et

    events = [
        {
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "commence_time": g.get("kickoff"),
        }
        for g in games
    ]
    dates = slate_dates_et(events)
    client = ActionNetworkClient()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in dates:
        for row in client.fetch_scoreboard(d):
            gid = str(row.get("game_id") or row.get("id") or "")
            key = gid or f"{row.get('away_team')}@{row.get('home_team')}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _load_odds_lines() -> dict[tuple[str, str], dict[str, Any]]:
    from sharp_scout.data.odds_api import OddsClient
    from sharp_scout.props.pipeline import _within_horizon

    client = OddsClient()
    events = _within_horizon(client.fetch_odds(), get_settings().prop_horizon_days)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for ev in events:
        key = (ev["away_team"], ev["home_team"])
        out[key] = {
            "kickoff": ev.get("commence_time"),
            "spread": client.pick_sharp_line(ev, "spreads"),
            "total": client.pick_sharp_line(ev, "totals"),
            "h2h": client.pick_sharp_line(ev, "h2h"),
        }
    return out


def _line_from_odds_pick(
    pick: dict[str, Any] | None, home: str, away: str, market: str
) -> str:
    if not pick:
        return "n/a"
    book = pick.get("book") or "?"
    parts: list[str] = []
    for o in pick.get("outcomes") or []:
        side = o.get("side")
        pt = o.get("point")
        price = o.get("price")
        if market == "spreads" and pt is not None:
            team = home if side == "home" else away
            parts.append(f"{team} {pt:+.1f} ({price:+.0f})" if price else f"{team} {pt:+.1f}")
        elif market == "totals" and pt is not None:
            parts.append(f"{str(side).title()} {pt} ({price:+.0f})" if price else f"{str(side).title()} {pt}")
        elif market == "h2h" and price is not None:
            team = home if side == "home" else away
            parts.append(f"{team} {price:+.0f}")
    label = " · ".join(parts) if parts else "n/a"
    return f"{label} <span class='muted'>via {html.escape(str(book))}</span>"


def _render_splits_block(
    home: str,
    away: str,
    split_board: dict[str, Any],
    odds_row: dict[str, Any] | None,
) -> str:
    from sharp_scout.data.splits_board import build_game_split_board

    # split_board may already be built; if raw AN row passed, build it
    if split_board and "markets" in split_board and "available" in split_board:
        board = split_board
    else:
        board = build_game_split_board(split_board, home_team=home, away_team=away)

    lines: list[str] = ['<div class="splits"><h4>Game lines &amp; Action Network public betting</h4>']
    if board.get("available"):
        lines.append("<table><thead><tr><th>Market</th><th>Line</th>"
                     "<th class='num'>Tickets</th><th class='num'>Money</th>"
                     "<th>Sharp signal</th></tr></thead><tbody>")
        for mkey, label in (("spread", "Spread"), ("total", "Total"), ("moneyline", "Moneyline")):
            m = (board.get("markets") or {}).get(mkey)
            if not m:
                continue
            sides = m.get("sides") or {}
            if mkey == "total":
                left = sides.get("over", {})
                right = sides.get("under", {})
                tickets = f"O {_an_pct(left.get('tickets_pct'))} / U {_an_pct(right.get('tickets_pct'))}"
                money = f"O {_an_pct(left.get('money_pct'))} / U {_an_pct(right.get('money_pct'))}"
            else:
                left = sides.get("home", {})
                right = sides.get("away", {})
                tickets = f"{away} {_an_pct(right.get('tickets_pct'))} · {home} {_an_pct(left.get('tickets_pct'))}"
                money = f"{away} {_an_pct(right.get('money_pct'))} · {home} {_an_pct(left.get('money_pct'))}"
            edge = m.get("sharp_edge") or {}
            sig = edge.get("reason") or "—"
            if edge.get("available"):
                sig = html.escape(str(sig))
            line_val = m.get("line")
            line_show = html.escape(str(line_val)) if line_val is not None else "—"
            lines.append(
                f"<tr><td>{label}</td><td class='num'>{line_show}</td>"
                f"<td class='num'>{tickets}</td><td class='num'>{money}</td>"
                f"<td>{sig}</td></tr>"
            )
        lines.append("</tbody></table>")
    else:
        reason = html.escape(str(board.get("reason") or "No Action Network match"))
        lines.append(f"<p class='muted'>Action Network: {reason}. Showing sharp-book lines from The Odds API.</p>")
        if odds_row:
            lines.append("<table><tbody>")
            lines.append(
                f"<tr><td>Spread</td><td>{_line_from_odds_pick(odds_row.get('spread'), home, away, 'spreads')}</td></tr>"
            )
            lines.append(
                f"<tr><td>Total</td><td>{_line_from_odds_pick(odds_row.get('total'), home, away, 'totals')}</td></tr>"
            )
            lines.append(
                f"<tr><td>Moneyline</td><td>{_line_from_odds_pick(odds_row.get('h2h'), home, away, 'h2h')}</td></tr>"
            )
            lines.append("</tbody></table>")
        else:
            lines.append("<p class='muted'>No odds snapshot for this matchup.</p>")
    lines.append("</div>")
    return "".join(lines)


def _render_player_block(player: str, prows: list[dict[str, Any]]) -> str:
    team = next((r.get("team") for r in prows if r.get("team")), "")
    chunks = [
        f'<div class="player"><h3>{html.escape(player)}'
        f'<small>{html.escape(str(team))} &middot; {len(prows)} bets</small></h3>'
        "<table><thead><tr>"
        "<th>Market</th><th>Side</th><th class='num'>Line</th><th>Book</th>"
        "<th class='num'>Price</th><th class='num'>EV</th>"
        "<th class='num'>Model</th><th class='num'>Raw</th>"
        "<th class='num'>Model %</th><th class='num'>Market %</th>"
        "</tr></thead><tbody>"
    ]
    for r in prows:
        side = str(r.get("side") or "")
        alt = ' <span class="alt">ALT</span>' if r.get("is_alternate") else ""
        price = r.get("price")
        price_cell = f"{price:+.0f}" if price is not None else "&mdash;"
        chunks.append(
            "<tr>"
            f"<td>{html.escape(_market_label(str(r.get('market') or '')))}</td>"
            f'<td><span class="side {side}">{html.escape(side.upper())}</span></td>'
            f"<td class='num'>{r.get('line')}{alt}</td>"
            f"<td>{html.escape(str(r.get('book') or '').replace('_', ' '))}</td>"
            f"<td class='num'>{price_cell}</td>"
            f"<td class='num'>{_pct(r.get('edge'))}</td>"
            f"<td class='num'>{r.get('model_mean')}</td>"
            f"<td class='num'>{_pct(r.get('p_raw'))}</td>"
            f"<td class='num'>{_pct(r.get('p_true'))}</td>"
            f"<td class='num'>{_pct(r.get('p_mkt'))}</td>"
            "</tr>"
        )
    chunks.append("</tbody></table></div>")
    return "".join(chunks)


def render(
    payload: dict[str, Any],
    game: str | None,
    *,
    top_players: int,
    top_per_game: int,
    include_splits: bool,
) -> str:
    settings = get_settings()
    plays = payload.get("plays") or []

    if game:
        away, _, home = game.partition("@")
        away, home = away.strip().upper(), home.strip().upper()
        plays = [p for p in plays if p.get("away_team") == away and p.get("home_team") == home]
        title = f"{away} @ {home}"
        game_list = _group_games(plays)
    else:
        title = f"Full slate ({payload.get('n_events', '?')} games)"
        game_list = _group_games(plays)

    if not game_list:
        raise SystemExit(f"No validated props found for {title}")

    all_rows = collapse_best(plays)
    edges = [r["edge"] for r in all_rows]

    an_rows: list[dict[str, Any]] = []
    odds_lines: dict[tuple[str, str], dict[str, Any]] = {}
    if include_splits:
        try:
            an_rows = _fetch_action_splits(game_list)
        except Exception as exc:  # noqa: BLE001
            an_rows = []
            an_error = str(exc)
        else:
            an_error = None
        try:
            odds_lines = _load_odds_lines()
        except Exception:
            odds_lines = {}
    else:
        an_error = None

    from sharp_scout.data.splits_board import build_game_split_board
    from sharp_scout.phase4.filters import _find_split_game

    parts: list[str] = [
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Sharp Scout props — {html.escape(title)}</title>
<style>{STYLES}</style></head><body>
<div class="hdr">
  <h1>Sharp Scout — NFL player props</h1>
  <div class="sub">{html.escape(title)} &middot; props run {html.escape(str(payload.get('generated_at', ''))[:19])}
   &middot; report {datetime.now().strftime("%b %d, %Y %I:%M %p")}</div>
</div>

<div class="warn">
  <b>Shadow mode / research only.</b> Player props are calibrated on historical play-by-play
  but not posted to the public board. <b>Game lines</b> below are Action Network ticket/money
  splits when matched; otherwise sharp-book quotes from The Odds API. Prop rows are model
  disagreements with sportsbook prices — sanity-check injuries and roles before betting.
</div>
"""
    ]

    if an_error:
        parts.append(f"<p class='muted'>Action Network fetch failed: {html.escape(an_error)}</p>")

    if not game:
        parts.append(
            f"""<div class="stats">
  <div class="stat"><b>{len(game_list)}</b><span>Games</span></div>
  <div class="stat"><b>{len(all_rows)}</b><span>Prop bets (collapsed)</span></div>
  <div class="stat"><b>{_pct(statistics.median(edges))}</b><span>Median EV</span></div>
  <div class="stat"><b>{_pct(max(edges))}</b><span>Best EV</span></div>
</div>
<table class="idx"><thead><tr>
<th>Matchup</th><th>Kickoff (UTC)</th><th>Props</th><th>AN splits</th>
</tr></thead><tbody>"""
        )
        for g in game_list:
            away, home = g["away_team"], g["home_team"]
            sg = _find_split_game(an_rows, home, away, sport="nfl") if an_rows else None
            board = build_game_split_board(sg, home_team=home, away_team=away) if sg else {}
            an_ok = "Yes" if board.get("available") else "No / odds fallback"
            n_props = len(collapse_best(g["plays"]))
            kick = html.escape(str(g.get("kickoff") or "")[:16])
            parts.append(
                f"<tr><td>{html.escape(away)} @ {html.escape(home)}</td>"
                f"<td>{kick}</td><td class='num'>{n_props}</td><td>{an_ok}</td></tr>"
            )
        parts.append("</tbody></table>")

    for g in game_list:
        away, home = g["away_team"], g["home_team"]
        kick = str(g.get("kickoff") or "")[:16]
        rows = collapse_best(g["plays"])
        if not rows:
            continue
        parts.append(
            f'<h2 class="game">{html.escape(away)} @ {html.escape(home)}'
            f'<span class="sub"> &middot; kickoff {html.escape(kick)} &middot; '
            f'{len(rows)} prop bets</span></h2>'
        )
        if include_splits:
            sg = _find_split_game(an_rows, home, away, sport="nfl") if an_rows else None
            odds_row = odds_lines.get((away, home))
            parts.append(_render_splits_block(home, away, sg or {}, odds_row))

        by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_player[row.get("player_name") or "Unknown"].append(row)
        limit = top_players if game else top_per_game
        ordered = sorted(
            by_player.items(), key=lambda kv: max(r.get("edge") or 0 for r in kv[1]), reverse=True
        )[:limit]
        for player, prows in ordered:
            parts.append(_render_player_block(player, prows))

    parts.append(
        f"""<div class="foot">
  Prop engine: nflverse usage, calibrated Monte Carlo, two-way market pricing.
  Public betting: Action Network scoreboard (anonymous when no token/cookie).
  Research only — Sharp Scout does not place bets.
</div></body></html>"""
    )
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render latest props run as HTML/PDF")
    ap.add_argument("--game", help="Filter to one game, e.g. NE@SEA (omit for full slate)")
    ap.add_argument("--top-players", type=int, default=40, help="Max players when --game is set")
    ap.add_argument(
        "--top-per-game",
        type=int,
        default=10,
        help="Max players per game on full-slate reports",
    )
    ap.add_argument("--no-splits", action="store_true", help="Skip Action Network / odds lines")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "Downloads",
        help="Output directory (default: ~/Downloads)",
    )
    ap.add_argument("--pdf", action="store_true", help="Also render a PDF via headless Chrome")
    args = ap.parse_args()

    src = ARTIFACTS_DIR / "latest_props.json"
    if not src.exists():
        raise SystemExit(f"{src} not found — run scripts/run_props.py first")
    payload = json.loads(src.read_text())

    doc = render(
        payload,
        args.game,
        top_players=args.top_players,
        top_per_game=args.top_per_game,
        include_splits=not args.no_splits,
    )
    slug = (args.game or "slate").replace("@", "-").lower()
    args.out.mkdir(parents=True, exist_ok=True)
    html_path = args.out / f"sharp-scout-props-{slug}.html"
    html_path.write_text(doc)
    print(f"HTML: {html_path}")

    if args.pdf:
        pdf_path = args.out / f"sharp-scout-props-{slug}.pdf"
        if not Path(CHROME).exists():
            raise SystemExit(f"Chrome not found at {CHROME} — open the HTML and print to PDF")
        subprocess.run(
            [
                CHROME,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
        print(f"PDF:  {pdf_path}")


if __name__ == "__main__":
    main()
