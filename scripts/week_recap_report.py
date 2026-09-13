#!/usr/bin/env python3
"""Generate an HTML + PDF week recap for Sharp Scout CFB ledger performance."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.config import DATA_DIR  # noqa: E402
from sharp_scout.copy.explain import collapse_best_signals, format_play_rationale  # noqa: E402
from sharp_scout.ledger.tracker import compute_record, load_ledger  # noqa: E402
from sharp_scout.site.build import _side_label  # noqa: E402
from sharp_scout.sports import get_sport  # noqa: E402

ET = ZoneInfo("America/New_York")
STAGE_LABELS = {
    "model": "Quant model (EPA + Monte Carlo)",
    "sharp": "Sharp book price (Pinnacle-style)",
    "public": "Public tickets %",
    "money": "Handle (dollars) %",
    "sharp_edge": "Sharp money (handle − tickets)",
    "hybrid": "Quant pick (hybrid / validated lean)",
    "rlm": "Reverse line movement",
}


def _week_stage_records(cards: list[dict], season: int, week: int) -> dict[str, dict]:
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"w": 0, "l": 0, "p": 0})
    for card in cards:
        if card.get("season") != season or card.get("week") != week:
            continue
        if card.get("status") != "settled":
            continue
        for stage, res in (card.get("results") or {}).items():
            if res == "win":
                buckets[stage]["w"] += 1
            elif res == "loss":
                buckets[stage]["l"] += 1
            elif res == "push":
                buckets[stage]["p"] += 1
    out: dict[str, dict] = {}
    for stage, b in buckets.items():
        d = b["w"] + b["l"]
        out[stage] = {
            "wins": b["w"],
            "losses": b["l"],
            "pushes": b["p"],
            "record": f"{b['w']}-{b['l']}" + (f"-{b['p']}" if b["p"] else ""),
            "win_pct": (b["w"] / d) if d else None,
            "n_games": d + b["p"],
        }
    return out


def _play_row(p: dict) -> str:
    pick = html.escape(_side_label(p))
    game = html.escape(f"{p.get('away_team')} @ {p.get('home_team')}")
    book = html.escape(str(p.get("book") or "—"))
    pnl = float(p.get("pnl_units") or 0)
    pnl_s = f"{pnl:+.2f}u"
    score = ""
    if p.get("away_score") is not None and p.get("home_score") is not None:
        score = html.escape(f"Final {p['away_team']} {p['away_score']} – {p['home_team']} {p['home_score']}")
    why = html.escape(format_play_rationale(p).replace("\n", " · ")[:280])
    return (
        f"<tr><td>{game}</td><td>{pick}</td><td>{book}</td>"
        f"<td class='{'pos' if pnl > 0 else 'neg'}'>{pnl_s}</td><td>{score}</td><td class='why'>{why}</td></tr>"
    )


def build_html(
    *,
    season: int,
    week: int,
    ncaaf_ledger: dict,
    nfl_record: dict | None,
) -> str:
    plays = ncaaf_ledger.get("plays") or []
    cards = ncaaf_ledger.get("stage_cards") or []

    graded = [
        p
        for p in plays
        if p.get("season") == season
        and p.get("week") == week
        and (p.get("status") or "") in ("win", "loss", "push")
    ]
    sharp_plays = collapse_best_signals(graded)
    wins = [p for p in sharp_plays if p.get("status") == "win"]
    losses = [p for p in sharp_plays if p.get("status") == "loss"]
    wk_pnl = sum(float(p.get("pnl_units") or 0) for p in sharp_plays)
    decided = len(wins) + len(losses)
    win_pct = (len(wins) / decided) if decided else 0.0

    quarantined = [
        p
        for p in plays
        if p.get("season") == season and p.get("week") == week and p.get("status") == "quarantined"
    ]
    quarantine_games = len({(p.get("event_id"), p.get("market"), p.get("side")) for p in quarantined})

    stage = _week_stage_records(cards, season, week)
    stage_rows = []
    for key in ("hybrid", "model", "sharp", "public", "money", "sharp_edge", "rlm"):
        b = stage.get(key)
        if not b:
            continue
        pct = f"{b['win_pct'] * 100:.1f}%" if b["win_pct"] is not None else "—"
        stage_rows.append(
            f"<tr><td>{html.escape(STAGE_LABELS.get(key, key))}</td>"
            f"<td>{b['record']}</td><td>{pct}</td><td>{b['n_games']}</td></tr>"
        )

    full_rec = compute_record(ncaaf_ledger)
    now = datetime.now(ET).strftime("%B %-d, %Y %-I:%M %p ET")

    lessons = [
        f"<b>Posted Sharp Plays (week {week}):</b> {len(wins)}-{len(losses)} ({win_pct:.1%}) "
        f"on {decided} deduplicated recommendations, <b>{wk_pnl:+.2f} units</b> P&amp;L.",
        "<b>What filtered through:</b> Phase 4 + ledger posting produced multiple book/line "
        f"variants; QA quarantined <b>{len(quarantined)}</b> row(s) across "
        f"<b>{quarantine_games}</b> game/market/side groups (suspicious model clusters, "
        "single-book lines, model–market spread gaps, etc.). Only pending plays appeared in "
        "<i>PLAY THESE QUANTS NOW</i>.",
        "<b>Lens leaderboard (graded stage picks, same week):</b> Sharp book price led ATS "
        f"({stage.get('sharp', {}).get('record', '—')}); hybrid/quant model "
        f"({stage.get('hybrid', {}).get('record', '—')}) beat public tickets "
        f"({stage.get('public', {}).get('record', '—')}). Sharp-money (handle vs tickets) "
        f"underperformed ({stage.get('sharp_edge', {}).get('record', '—')}) — confirmation "
        "filters matter.",
        "<b>Totals vs sides:</b> Week 2 posted plays leaned heavily on totals; unders and "
        "mid-total overs that cleared the bar mostly cashed, while a few high-EV totals "
        "(e.g. OU–Michigan over) missed in shootout variance.",
        "<b>Moneylines:</b> Straight ML posts (Wake, Montana State, UNLV ML) went 0–3 — "
        "large model–market gaps on ML remain a QA focus.",
        "<b>Operational:</b> Settlement now pulls ESPN finals via HTTP client (fixes SSL "
        "failures that left Saturday games pending). Sunday CI cron + manual workflow "
        "refresh keeps the board in sync.",
    ]
    if nfl_record and (nfl_record.get("pending") or 0) > 0:
        lessons.append(
            f"<b>NFL:</b> {nfl_record.get('pending')} play(s) still pending NFL grading "
            f"(overall {nfl_record.get('record')})."
        )

    win_rows = "".join(_play_row(p) for p in sorted(wins, key=lambda x: -(x.get("pnl_units") or 0)))
    loss_rows = "".join(_play_row(p) for p in sorted(losses, key=lambda x: (x.get("pnl_units") or 0)))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Sharp Scout CFB Week {week} Recap</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111; margin: 32px; line-height: 1.45; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .meta {{ color: #555; font-size: 13px; margin-bottom: 20px; }}
  h2 {{ font-size: 16px; margin-top: 24px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0 16px; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #f3f4f6; }}
  .pos {{ color: #047857; font-weight: 600; }}
  .neg {{ color: #b91c1c; font-weight: 600; }}
  .summary {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px 14px; border-radius: 8px; }}
  ul {{ margin: 8px 0; padding-left: 20px; }}
  li {{ margin-bottom: 8px; }}
  td.why {{ font-size: 11px; color: #444; max-width: 280px; }}
</style>
</head>
<body>
<h1>Sharp Scout — College Football Week {week} Recap ({season})</h1>
<p class="meta">Generated {html.escape(now)} · Ledger: {html.escape(full_rec.get('record', '—'))} all-time · 
Bankroll {full_rec.get('bankroll_units', '—')}u (start {full_rec.get('starting_units', 100)}u)</p>

<div class="summary">
  <strong>Week {week} Sharp Plays (deduplicated):</strong> {len(wins)}-{len(losses)} ({win_pct:.1%}) · 
  <strong>{wk_pnl:+.2f} units</strong> · {decided} recommendations graded<br/>
  <strong>QA held (not recommended):</strong> {len(quarantined)} ledger rows · {quarantine_games} logical play groups
</div>

<h2>Quant model vs other lenses (ATS / ML / total picks per game)</h2>
<p>Each row is how that <em>lens</em> would have done if you took its pick on every graded game card this week (not the same as posted unit sizing).</p>
<table>
<thead><tr><th>Lens</th><th>Record</th><th>Win %</th><th>Graded picks</th></tr></thead>
<tbody>{''.join(stage_rows) or '<tr><td colspan="4">No settled stage cards for this week.</td></tr>'}</tbody>
</table>

<h2>Where the ledger won</h2>
<table>
<thead><tr><th>Game</th><th>Play</th><th>Book</th><th>P&amp;L</th><th>Score</th><th>Rationale (short)</th></tr></thead>
<tbody>{win_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
</table>

<h2>Where the ledger lost</h2>
<table>
<thead><tr><th>Game</th><th>Play</th><th>Book</th><th>P&amp;L</th><th>Score</th><th>Rationale (short)</th></tr></thead>
<tbody>{loss_rows or '<tr><td colspan="6">None</td></tr>'}</tbody>
</table>

<h2>Lessons learned</h2>
<ul>
{''.join(f'<li>{x}</li>' for x in lessons)}
</ul>

<p class="meta">Sharp Scout · sharp-scout docs board reflects settled ledgers after <code>settle_now.py</code>.</p>
</body>
</html>
"""


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not chrome.is_file():
        raise SystemExit("Google Chrome not found — cannot render PDF.")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    url = html_path.resolve().as_uri()
    cmd = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        url,
    ]
    subprocess.run(cmd, check=True, timeout=120)


def main() -> None:
    p = argparse.ArgumentParser(description="Week recap HTML + PDF")
    p.add_argument("--season", type=int, default=2026)
    p.add_argument("--week", type=int, default=2)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / "Downloads",
    )
    args = p.parse_args()

    ncaaf_path = DATA_DIR / get_sport("ncaaf").ledger_name
    ncaaf_ledger = load_ledger(path=ncaaf_path)
    nfl_rec = compute_record(path=DATA_DIR / get_sport("nfl").ledger_name)

    body = build_html(
        season=args.season,
        week=args.week,
        ncaaf_ledger=ncaaf_ledger,
        nfl_record=nfl_rec,
    )

    stamp = datetime.now(ET).strftime("%Y-%m-%d")
    base = args.out_dir / f"sharp-scout-cfb-week{args.week}-recap-{stamp}"
    html_path = base.with_suffix(".html")
    pdf_path = base.with_suffix(".pdf")
    html_path.write_text(body, encoding="utf-8")
    html_to_pdf(html_path, pdf_path)
    print(json.dumps({"html": str(html_path), "pdf": str(pdf_path)}, indent=2))


if __name__ == "__main__":
    main()
