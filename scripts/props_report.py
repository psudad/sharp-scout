#!/usr/bin/env python3
"""Render the latest player-props run as a shareable HTML/PDF card.

Reads artifacts/latest_props.json (written by scripts/run_props.py) and collapses the
raw rows — one per book, line, and side — down to the best available price per logical
bet, so a single game reads as ~50 lines instead of ~250.

    python scripts/run_props.py --no-ledger
    python scripts/props_report.py --game NE@SEA --pdf
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


def _market_label(market: str) -> str:
    return market.replace("player_", "").replace("_", " ").title()


def render(payload: dict[str, Any], game: str | None, top_players: int) -> str:
    settings = get_settings()
    plays = payload.get("plays") or []

    if game:
        away, _, home = game.partition("@")
        plays = [
            p
            for p in plays
            if p.get("away_team") == away.strip().upper()
            and p.get("home_team") == home.strip().upper()
        ]
        title = f"{away.strip().upper()} @ {home.strip().upper()}"
    else:
        title = "Full slate"

    rows = collapse_best(plays)
    if not rows:
        raise SystemExit(f"No validated props found for {title}")

    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_player[row.get("player_name") or "Unknown"].append(row)
    ordered = sorted(
        by_player.items(), key=lambda kv: max(r.get("edge") or 0 for r in kv[1]), reverse=True
    )[:top_players]

    kickoff = next((r.get("kickoff") for r in rows if r.get("kickoff")), "") or ""
    edges = [r["edge"] for r in rows]

    parts: list[str] = [
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Sharp Scout props — {html.escape(title)}</title>
<style>
  @page {{ margin: 14mm; }}
  body {{ font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
          color: #111827; margin: 32px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #6b7280; font-size: 13px; }}
  .hdr {{ border-bottom: 3px solid #1d4ed8; padding-bottom: 14px; margin-bottom: 18px; }}
  .warn {{ background: #fffbeb; border-left: 4px solid #d97706; padding: 12px 16px;
           border-radius: 4px; margin: 18px 0; font-size: 13px; }}
  .stats {{ display: flex; gap: 28px; margin: 16px 0 26px; flex-wrap: wrap; }}
  .stat b {{ display: block; font-size: 21px; }}
  .stat span {{ color: #6b7280; font-size: 12px; text-transform: uppercase;
                letter-spacing: .04em; }}
  .player {{ margin: 22px 0; page-break-inside: avoid; }}
  .player h2 {{ font-size: 16px; margin: 0 0 6px; }}
  .player h2 small {{ color: #6b7280; font-weight: 400; margin-left: 8px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #111827; color: #fff; font-size: 11px; text-transform: uppercase;
        letter-spacing: .05em; padding: 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .side {{ font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 3px; }}
  .over {{ background: #fee2e2; color: #991b1b; }}
  .under {{ background: #dbeafe; color: #1e40af; }}
  .alt {{ color: #b45309; font-size: 11px; font-weight: 600; }}
  .foot {{ margin-top: 30px; padding-top: 14px; border-top: 2px solid #e5e7eb;
           color: #6b7280; font-size: 12px; }}
</style></head><body>
<div class="hdr">
  <h1>Sharp Scout — NFL player props</h1>
  <div class="sub">{html.escape(title)}{f" &middot; kickoff {html.escape(str(kickoff)[:16])}" if kickoff else ""}
   &middot; generated {datetime.now().strftime("%b %d, %Y %I:%M %p")}</div>
</div>

<div class="warn">
  <b>Calibrated, but not yet proven.</b> Probabilities pass through a per-market calibrator
  fit on historical play-by-play and validated out of sample; the <b>Raw</b> column is the
  uncalibrated simulation, so a large Raw&nbsp;&rarr;&nbsp;Model move means the correction is
  doing heavy lifting there. Residual mean bias remains &mdash;
  the projection still does not know this week's role, injury, or snap-share news, and no
  prop has settled for real money yet. Treat as a research shortlist.
</div>

<div class="stats">
  <div class="stat"><b>{len(rows)}</b><span>Bets shown</span></div>
  <div class="stat"><b>{len(by_player)}</b><span>Players</span></div>
  <div class="stat"><b>{_pct(statistics.median(edges))}</b><span>Median EV</span></div>
  <div class="stat"><b>{_pct(max(edges))}</b><span>Best EV</span></div>
  <div class="stat"><b>{_pct(settings.max_prop_edge)}</b><span>EV cap</span></div>
</div>
"""
    ]

    for player, prows in ordered:
        team = next((r.get("team") for r in prows if r.get("team")), "")
        parts.append(
            f'<div class="player"><h2>{html.escape(player)}'
            f'<small>{html.escape(str(team))} &middot; {len(prows)} bets</small></h2>'
            "<table><thead><tr>"
            "<th>Market</th><th>Side</th><th class='num'>Line</th><th>Book</th>"
            "<th class='num'>Price</th><th class='num'>EV</th>"
            "<th class='num'>Model</th><th class='num'>Raw</th>"
            "<th class='num'>Model %</th><th class='num'>Market %</th>"
            "</tr></thead><tbody>"
        )
        for r in prows:
            side = str(r.get("side") or "")
            alt = ' <span class="alt">ALT</span>' if r.get("is_alternate") else ""
            price = r.get("price")
            price_cell = f"{price:+.0f}" if price is not None else "&mdash;"
            parts.append(
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
        parts.append("</tbody></table></div>")

    parts.append(
        f"""<div class="foot">
  Usage baselines from nflverse play-by-play (season decay {settings.prop_season_decay}),
  non-normal Monte Carlo (negative binomial for counts, gamma for yardage), calibrated per
  market, then priced against each book's no-vig two-way market. Rejected automatically: EV
  above {_pct(settings.max_prop_edge)}, model certainty above {_pct(settings.max_prop_p_true)},
  a model-vs-market gap above {_pct(settings.prop_model_market_gap)}, or no two-way market to
  price against.<br>
  Research only — Sharp Scout does not place bets.
</div></body></html>"""
    )
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render latest props run as HTML/PDF")
    ap.add_argument("--game", help="Filter to one game, e.g. NE@SEA")
    ap.add_argument("--top-players", type=int, default=40)
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

    doc = render(payload, args.game, args.top_players)
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
