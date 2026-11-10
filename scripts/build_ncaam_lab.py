#!/usr/bin/env python3
"""Build the unlisted NCAAM three-system page (Sharp 3, Sharp 3.5, New System).

Standard library only, so every Pages deploy job can run it right before uploading docs/.
The output path comes from the NCAAM_LAB_SLUG secret and is never committed or linked
from any other page. With no slug configured this script does nothing.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sharp_scout.ncaam.sharp3_sim import (  # noqa: E402
    format_sim_rec,
    lab_sim_display_text,
    monte_carlo_projection,
    run_margin_monte_carlo_core,
)
from sharp_scout.ncaam.ratings import load_ratings  # noqa: E402

DATA = ROOT / "data"
ET = ZoneInfo("America/New_York")
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SYSTEMS = (
    ("sharp3", "Sharp 3", DATA / "ncaam" / "sharp3_ledger.json"),
    ("sharp35", "Sharp 3.5", DATA / "ncaam" / "sharp35_ledger.json"),
    ("new", "New System", DATA / "ncaam_ledger.json"),
)
TIER_LABEL = {
    "DOUBLE_DIAMOND": "Double Diamond",
    "DIAMOND": "Diamond",
    "GOLD": "Gold",
    "BRONZE": "Bronze",
}


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def _dt(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def num(x: Any, *, sign: bool = False) -> str:
    """Whole numbers without a trailing .0 (so -3 not -3.0)."""
    try:
        f = round(float(x), 1)
    except (TypeError, ValueError):
        return ""
    s = str(int(f)) if f == int(f) else f"{f:.1f}"
    if sign and f > 0:
        s = "+" + s
    return s


def price(x: Any) -> str:
    try:
        f = int(round(float(x)))
    except (TypeError, ValueError):
        return ""
    return f"+{f}" if f > 0 else str(f)


BOOK_LABEL = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "caesars": "Caesars",
    "betrivers": "BetRivers",
    "espnbet": "ESPN BET",
    "betonlineag": "BetOnline",
    "bovada": "Bovada",
    "pinnacle": "Pinnacle",
    "fanatics": "Fanatics",
}


def book_label(b: Any) -> str:
    if not b:
        return ""
    k = str(b).lower()
    return BOOK_LABEL.get(k, k.replace("_", " ").title())


def pick_text(p: dict[str, Any]) -> str:
    """Readable bet: "Elon ML +170", "Purdue +5.5 (-115)"."""
    team = p.get("selection") or p.get(f"{p.get('side')}_team") or str(p.get("side") or "").title()
    pr = price(p.get("price"))
    if (p.get("market") or "spreads") == "h2h":
        return f"{team} ML {pr}".strip()
    line = num(p.get("line"), sign=True)
    out = f"{team} {'PK' if line == '0' else line}".strip()
    return f"{out} ({pr})" if pr else out


def bet_type(p: dict[str, Any]) -> str:
    return "Moneyline" if p.get("market") == "h2h" else "Spread"


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _play_cell(p: dict[str, Any], *, locked: bool, extra: str = "") -> str:
    tier = TIER_LABEL.get(str(p.get("tier") or ""), "")
    est = " (est.)" if p.get("price_estimated") else ""
    parts = [f"{_esc(bet_type(p))}{est}"]
    if book_label(p.get("book")):
        parts.append(_esc(book_label(p.get("book"))))
    if tier:
        parts.append(_esc(tier))
    if p.get("units") is not None:
        parts.append(f"{num(p.get('units'))}u")
    sim_line = ""
    if p.get("sim_rec") is not None or p.get("sim_projection") is not None:
        sim_txt = lab_sim_display_text(p)
        if sim_txt:
            sim_line = f"<br><small class='muted'>{_esc(sim_txt)}</small>"
    status = "Locked" if locked else "Preview"
    if locked and p.get("pick_status"):
        status += f" {p['pick_status']}"
    head = f"<b>{_esc(pick_text(p))}</b>" if locked else _esc(pick_text(p))
    cls = "lock" if locked else "muted"
    return f'<div class="{cls}">{head}<br><small>{" | ".join(parts)} | {status}{extra}</small>{sim_line}</div>'


def sharp_cell(rec: dict[str, Any] | None, game: dict[str, Any], *, splits_live: bool) -> str:
    if not splits_live:
        return '<span class="muted">Waiting on splits data</span>'
    rec = rec or {}
    if not game.get("has_splits") and not rec.get("locked"):
        return '<span class="muted">No splits for this game</span>'
    p = {**rec, "home_team": game.get("home_team"), "away_team": game.get("away_team")}
    if rec.get("locked"):
        return _play_cell(p, locked=True)
    if rec.get("volume"):
        return f'<span class="muted">No play (volume, outside top 10)</span><br><small class="muted">{_esc(pick_text(p))}</small>'
    res = rec.get("result")
    if res == "play":
        return _play_cell(p, locked=False, extra=f" | {_esc(rec['reason'])}" if rec.get("reason") else "")
    why = {
        "trap": f"Trap: {rec.get('reason') or ''}",
        "lean": "lean",
        "anomaly": "data anomaly",
        "not_shortlisted": "not enough signals",
    }.get(str(res), rec.get("reason") or "not evaluated")
    return f'<span class="muted">No play ({_esc(why)})</span>'


def new_cell(row: dict[str, Any] | None, game: dict[str, Any], now: datetime) -> str:
    if row and row.get("side"):
        p = {**row, "home_team": game.get("home_team"), "away_team": game.get("away_team")}
        return _play_cell(p, locked=True)
    if row and row.get("status") in ("no_play", "missed"):
        return '<span class="muted">No play</span>'
    tip = _dt(game.get("tip"))
    if tip and tip - now > timedelta(minutes=90):
        return '<span class="muted">Evaluates 90 min before tip</span>'
    if tip and now >= tip:
        return '<span class="muted">No play</span>'
    return '<span class="muted">No play so far</span>'


def record(ledger: dict[str, Any]) -> dict[str, Any]:
    w = l = pu = pend = 0
    pnl = risked = 0.0
    for r in ledger.get("plays") or []:
        if not r.get("side"):
            continue
        st = r.get("status")
        if st == "win":
            w += 1
        elif st == "loss":
            l += 1
        elif st == "push":
            pu += 1
        else:
            pend += st == "pending"
            continue
        pnl += float(r.get("pnl_units") or 0)
        if st != "push":
            risked += float(r.get("units") or 0)
    return {"w": w, "l": l, "p": pu, "pending": pend, "units": pnl, "roi": (pnl / risked * 100) if risked else None}


def _state_for(day: str) -> tuple[str, dict[str, Any]]:
    p = DATA / "ncaam" / f"systems_{day.replace('-', '')}.json"
    st = _load(p, None)
    if st and st.get("games"):
        return day, st
    files = sorted((DATA / "ncaam").glob("systems_*.json"))
    if files:
        f = files[-1]
        d = f.stem.split("_")[1]
        return f"{d[:4]}-{d[4:6]}-{d[6:]}", _load(f, {"games": {}})
    return day, {"games": {}}


CSS = """
body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:20px;}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.sub{color:#9aa0a6;font-size:13px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #262a33;padding:7px 8px;text-align:left;vertical-align:top}
th{color:#9aa0a6;font-weight:600;position:sticky;top:0;background:#0f1115}
.muted{color:#8a9099}.lock b{color:#7ee2a8}small{font-size:11px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{background:#171a21;border:1px solid #262a33;border-radius:8px;padding:12px 16px;min-width:200px}
.card .n{font-size:20px;font-weight:700}.pos{color:#7ee2a8}.neg{color:#ff8a8a}
.wrap{overflow-x:auto}
pre.example{background:#171a21;border:1px solid #262a33;border-radius:6px;padding:12px;font-size:12px;overflow:auto}
"""


def _fixture_sim_example_html() -> str:
    """Labeled Torvik fixture MC — not a live pregame forecast."""
    fixture = ROOT / "tests" / "fixtures" / "ncaam" / "torvik_sample.csv"
    prov_path = ROOT / "tests" / "fixtures" / "ncaam" / "torvik_sample.provenance.json"
    if not fixture.is_file():
        return (
            "<h2>Fixture example (offline only)</h2>"
            "<p class='sub'>Torvik sample fixture missing; no example projection rendered.</p>"
        )
    ratings = load_ratings(fixture)
    provenance = json.loads(prov_path.read_text()) if prov_path.is_file() else None
    game = {
        "espn_id": "fixture-demo-001",
        "home_team": "Duke",
        "away_team": "North Carolina",
        "neutral_site": False,
    }
    gated = monte_carlo_projection(
        game,
        side="home",
        market="spreads",
        line=-4.5,
        ratings=ratings,
        ratings_provenance=provenance,
        n=2000,
    )
    gated_line = lab_sim_display_text(
        {"sim_projection": gated, "sim_rec": format_sim_rec(gated)}
    ) or "MC projection: unavailable"
    math_demo = run_margin_monte_carlo_core(
        game,
        side="home",
        market="spreads",
        line=-4.5,
        ratings=ratings,
        ratings_provenance=provenance,
        n=2000,
    )
    return (
        "<h2>Fixture example (not live pregame)</h2>"
        "<p class='sub'>Production path from <code>tests/fixtures/ncaam/torvik_sample.csv</code>: "
        "no verified upstream retrieval record (fixture). Gated MC requires acquisition meta + "
        "digest match. Publisher ratings snapshot date: unknown.</p>"
        f"<p class='muted'><b>Gated (production rule):</b> {_esc(gated_line)}</p>"
        "<p class='sub'><b>Math demo only</b> (same Torvik rows, no verified source as-of — "
        "not a forecast): "
        f"{_esc(format_sim_rec(math_demo) or '')} · margin_model={math_demo.get('margin_model')}"
        "</p>"
        f"<pre class='example'>{_esc(json.dumps(gated, indent=2))}</pre>"
    )


def build(out: Path, *, now: datetime | None = None, fixture_sim_demo: bool = False) -> Path:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ET).date().isoformat()
    day, state = _state_for(today)
    ledgers = {k: _load(p, {"plays": []}) for k, _, p in SYSTEMS}
    new_by_id = {str(r.get("espn_id")): r for r in ledgers["new"].get("plays") or []}
    games = state.get("games") or {}
    splits_live = bool((state.get("splits") or {}).get("n_with_money"))
    rows = []
    for eid, g in sorted(games.items(), key=lambda kv: (str(kv[1].get("tip")), kv[0])):
        shown = g.get("has_splits") or eid in new_by_id or any((g.get(k) or {}).get("locked") for k in ("sharp3", "sharp35"))
        if not shown:
            continue
        tip = _dt(g.get("tip"))
        from sharp_scout.copy.explain import format_kickoff_time_et

        tip_s = format_kickoff_time_et(tip) if tip else ""
        rows.append(
            "<tr>"
            f"<td>{_esc(tip_s)}</td>"
            f"<td>{_esc(g.get('away_team'))} at {_esc(g.get('home_team'))}</td>"
            f"<td>{sharp_cell(g.get('sharp3'), g, splits_live=splits_live)}</td>"
            f"<td>{sharp_cell(g.get('sharp35'), g, splits_live=splits_live)}</td>"
            f"<td>{new_cell(new_by_id.get(eid), g, now)}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="5" class="muted">No games evaluated yet for this date.</td></tr>')
    cards = []
    for k, name, _ in SYSTEMS:
        r = record(ledgers[k])
        cls = "pos" if r["units"] > 0 else ("neg" if r["units"] < 0 else "")
        roi = f"{r['roi']:.1f}%" if r["roi"] is not None else "n/a"
        cards.append(
            f'<div class="card"><div>{_esc(name)}</div>'
            f'<div class="n">{r["w"]}-{r["l"]}{"-" + str(r["p"]) if r["p"] else ""}</div>'
            f'<div class="{cls}">{"+" if r["units"] > 0 else ""}{r["units"]:.2f}u</div>'
            f'<div class="muted">ROI {roi} | {r["pending"]} pending</div></div>'
        )
    ledger_html = []
    for k, name, _ in SYSTEMS:
        plays = [p for p in ledgers[k].get("plays") or [] if p.get("side")]
        plays.sort(key=lambda p: str(p.get("tip")), reverse=True)
        trs = []
        for p in plays[:60]:
            tip = _dt(p.get("tip"))
            pnl = p.get("pnl_units")
            trs.append(
                "<tr>"
                f"<td>{tip.astimezone(ET).strftime('%b %-d') if tip else ''}</td>"
                f"<td>{_esc(p.get('away_team'))} at {_esc(p.get('home_team'))}</td>"
                f"<td><b>{_esc(pick_text(p))}</b></td><td>{_esc(bet_type(p))}</td>"
                f"<td>{_esc(book_label(p.get('book')))}</td>"
                f"<td>{_esc(TIER_LABEL.get(str(p.get('tier') or ''), ''))}</td>"
                f"<td>{num(p.get('units'))}u</td>"
                f"<td>{_esc(str(p.get('status') or '').title())}</td>"
                f"<td>{'' if pnl is None else num(pnl, sign=True) + 'u'}</td>"
                "</tr>"
            )
        if not trs:
            trs.append('<tr><td colspan="9" class="muted">No graded or pending picks yet.</td></tr>')
        ledger_html.append(
            f"<h2>{_esc(name)} ledger</h2><div class='wrap'><table><tr><th>Date</th><th>Game</th><th>Pick</th>"
            "<th>Type</th><th>Book</th><th>Tier</th><th>Stake</th><th>Result</th><th>Units</th></tr>"
            + "".join(trs)
            + "</table></div>"
        )
    sp = state.get("splits") or {}
    cov = sp.get("coverage") or f"{sp.get('n_with_money', 0)}/{sp.get('n_games', 0)}"
    splits_note = (
        f"Splits coverage: {cov} slate games."
        if splits_live
        else "Sharp 3 and Sharp 3.5 are waiting on splits data."
    )
    updated = _dt(state.get("updated_at"))
    from sharp_scout.copy.explain import format_display_datetime_et

    upd = format_display_datetime_et(updated) if updated else "not yet"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive, nosnippet">
<meta name="googlebot" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>NCAAM systems</title><style>{CSS}</style></head>
<body>
<h1>College Basketball: three systems</h1>
<div class="sub">Sharp 3, Sharp 3.5 and New System run side by side. Picks are never combined; each system is graded in its own ledger. Slate: {_esc(day)}. Updated {_esc(upd)}. {_esc(splits_note)}</div>
<div class="wrap"><table>
<tr><th>Tip (ET)</th><th>Game</th><th>Sharp 3</th><th>Sharp 3.5</th><th>New System</th></tr>
{''.join(rows)}
</table></div>
<h2>Records</h2>
<div class="cards">{''.join(cards)}</div>
{''.join(ledger_html)}
{_fixture_sim_example_html() if fixture_sim_demo else ""}
<p class="sub">Bold = locked pick; gray = preview or no play. "
"Sharp 3 MC lines require validated <code>sim_projection</code> metadata; legacy "
"<code>sim_rec</code> pseudo-data is never shown.</p>
</body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="Explicit output file (local preview)")
    ap.add_argument(
        "--fixture-sim-demo",
        action="store_true",
        help="Append labeled Torvik fixture MC example (not live pregame)",
    )
    ap.add_argument("--slug-env", default="NCAAM_LAB_SLUG")
    args = ap.parse_args()
    if args.out:
        build(Path(args.out), fixture_sim_demo=args.fixture_sim_demo)
        print("Built unlisted page (local preview)")
        return 0
    slug = (os.environ.get(args.slug_env) or "").strip()
    if not slug:
        print("No unlisted page slug configured; skipping")
        return 0
    if not SLUG_RE.match(slug):
        print("Unlisted page slug is not valid; skipping")
        return 0
    build(ROOT / "docs" / slug / "index.html")
    print("Built unlisted page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
