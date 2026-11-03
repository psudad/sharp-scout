"""College Basketball (NCAAM) public board."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR, ROOT, get_settings
from sharp_scout.ledger.tracker import compute_record, load_ledger
from sharp_scout.ncaam.rules import RULES
from sharp_scout.site.bottom_bar import (
    BOTTOM_BAR_SCRIPT,
    bottom_bar_css,
    render_bottom_bar,
    render_slip_overlay,
)
from sharp_scout.site.site_nav import NAV_TEST_BADGE_CSS, render_site_tabs

DOCS_DIR = ROOT / "docs"
NCAAM_LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"
NCAAM_SIGNALS_PATH = DATA_DIR / "ncaam_latest_signals.json"
ET = ZoneInfo("America/New_York")


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load_signals(path: Path | None = None) -> dict[str, Any]:
    p = path or NCAAM_SIGNALS_PATH
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _pct(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{min(v, RULES.p_true_display_cap) * 100:.1f}%"


def _fmt_et(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ET).strftime("%b %-d %I:%M %p ET")
    except ValueError:
        return _esc(iso)


_NOT_A_PLAY = ("no_play", "missed")

NCAAM_BOOK_LABELS = {
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
    "hardrockbet": "Hard Rock Bet",
    "ballybet": "Bally Bet",
    "betus": "BetUS",
    "lowvig": "LowVig",
    "mybookieag": "MyBookie",
}
_RESULT_LABELS = {"win": "Win", "loss": "Loss", "push": "Push", "void": "Void", "pending": "Pending"}


def ncaam_price(x: Any) -> str:
    """American odds with an explicit + for underdogs (e.g. +170, -110)."""
    try:
        n = int(round(float(x)))
    except (TypeError, ValueError):
        return ""
    return f"+{n}" if n > 0 else str(n)


def ncaam_book_label(book: Any) -> str:
    if not book:
        return "—"
    key = str(book).lower()
    return NCAAM_BOOK_LABELS.get(key, key.replace("_", " ").title())


def _play_team(p: dict[str, Any]) -> str:
    side = str(p.get("side") or "").lower()
    team = p.get("selection") or p.get(f"{side}_team")
    return str(team or side.title())


def ncaam_play_label(p: dict[str, Any]) -> str:
    """Readable bet: team + line + price, e.g. "Elon ML +170" or "Iona +1 (-110)"."""
    team = _play_team(p)
    price = ncaam_price(p.get("price"))
    if str(p.get("market") or "spreads") == "h2h":
        return f"{team} ML {price}".strip()
    line = p.get("line")
    try:
        fv = float(line)
        line_s = "PK" if fv == 0 else f"{fv:+g}"
    except (TypeError, ValueError):
        line_s = ""
    out = f"{team} {line_s}".strip()
    return f"{out} ({price})" if price else out


def ncaam_bet_type(p: dict[str, Any]) -> str:
    return "Moneyline" if str(p.get("market") or "") == "h2h" else "Spread"


def _stake(p: dict[str, Any]) -> str:
    u = p.get("units")
    try:
        return f"{float(u if u is not None else 1):g}u"
    except (TypeError, ValueError):
        return "—"


def _result_label(p: dict[str, Any]) -> str:
    st = str(p.get("status") or "pending").lower()
    label = _RESULT_LABELS.get(st, st.title())
    pnl = p.get("pnl_units")
    if pnl is None:
        return label
    v = float(pnl)
    return f"{label} ({v:+.2f}u)" if v else f"{label} (0.00u)"


def ncaam_record(ledger: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Season record for the NCAAM board.

    Only real picks count: no-edge / missed markers (no side) are left out, so they are not
    reported as "pending". Voids are counted as void with 0u and never enter W-L, units or CLV.
    """
    from sharp_scout.ledger.clv import summarize_clv

    plays = ledger.get("plays") or []
    picks = [p for p in plays if p.get("side") and p.get("status") not in _NOT_A_PLAY]
    rec = compute_record({**ledger, "plays": picks}, path=path or NCAAM_LEDGER_PATH)
    rec["clv"] = summarize_clv({**ledger, "plays": [p for p in picks if p.get("status") != "void"]})
    rec["n_no_play"] = len(plays) - len(picks)
    return rec


def _render_record(rec: dict[str, Any], ledger: dict[str, Any]) -> str:
    record = str(rec.get("record") or "0-0")
    pnl = float(rec.get("pnl_units") or 0)
    pnl_s = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
    cls = "pos" if pnl >= 0 else "neg"
    clv_beat = 0
    clv_total = 0
    for p in ledger.get("plays") or []:
        if p.get("status") == "void":
            continue
        if p.get("clv_points") is not None:
            clv_total += 1
            if float(p.get("clv_points") or 0) > 0:
                clv_beat += 1
    clv_pct = f"{100.0 * clv_beat / clv_total:.0f}%" if clv_total else "—"
    roi = rec.get("roi_pct")
    roi_s = f"{float(roi):+.1f}%" if roi is not None else "—"
    return (
        f'<div class="ncaam-record">'
        f'<div class="pr-card"><div class="pr-val">{_esc(record)}</div>'
        f'<div class="pr-lbl">Season record</div></div>'
        f'<div class="pr-card"><div class="pr-val {cls}">{pnl_s}u</div>'
        f'<div class="pr-lbl">Units P&amp;L</div></div>'
        f'<div class="pr-card"><div class="pr-val">{_esc(roi_s)}</div>'
        f'<div class="pr-lbl">ROI</div></div>'
        f'<div class="pr-card"><div class="pr-val">{_esc(clv_pct)}</div>'
        f'<div class="pr-lbl">CLV beat close</div></div>'
        f"</div>"
    )


def _render_locks(signals: dict[str, Any]) -> str:
    locks = signals.get("locks") or []
    if not locks:
        pending = [
            p
            for p in (load_ledger(NCAAM_LEDGER_PATH).get("plays") or [])
            if p.get("status") == "pending" and p.get("side")
        ]
        locks = pending
    if not locks:
        return (
            '<div class="ncaam-empty">'
            "<p><b>No locked plays yet today.</b></p>"
            "<p>Picks lock once per game between T-90 and T-25 minutes before tip "
            "(late window through T-5).</p></div>"
        )
    rows = []
    for p in locks:
        away = _esc(p.get("away_team") or "")
        home = _esc(p.get("home_team") or "")
        ev = p.get("ev")
        note = p.get("note")
        note_cell = f'<br><small class="phase-note">{_esc(note)}</small>' if note else ""
        ev_s = f"{float(ev)*100:.1f}%" if ev is not None else "—"
        rows.append(
            f'<tr><td data-label="Game">{away} @ {home}</td>'
            f'<td data-label="Play"><b>{_esc(ncaam_play_label(p))}</b>{note_cell}</td>'
            f'<td data-label="Type">{_esc(ncaam_bet_type(p))}</td>'
            f'<td data-label="Book">{_esc(ncaam_book_label(p.get("book")))}</td>'
            f'<td data-label="Stake">{_esc(_stake(p))}</td>'
            f'<td data-label="EV">{ev_s}</td>'
            f'<td data-label="Model / Fair / Anchor">{_pct(p.get("p_model"))} / {_pct(p.get("p_fair"))} / {_pct(p.get("p_true"))}</td>'
            f'<td data-label="Locked (ET)">{_fmt_et(p.get("locked_at"))}</td>'
            f'<td data-label="Tip (ET)">{_fmt_et(p.get("tip"))}</td></tr>'
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table">'
        "<thead><tr><th>Game</th><th>Play</th><th>Type</th><th>Book</th><th>Stake</th><th>EV</th>"
        "<th>Model / Fair / Anchor</th>"
        "<th>Locked (ET)</th><th>Tip (ET)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _ledger_rows(ledger: dict[str, Any]) -> str:
    plays = [p for p in (ledger.get("plays") or []) if p.get("side")]
    if not plays:
        return '<p class="ncaam-empty">No graded NCAAM plays yet.</p>'
    rows = []
    for p in reversed(plays[-50:]):
        st = str(p.get("status") or "pending").lower()
        rows.append(
            f'<tr><td data-label="Tip (ET)">{_fmt_et(p.get("tip"))}</td>'
            f'<td data-label="Game">{_esc(p.get("away_team", ""))} @ {_esc(p.get("home_team", ""))}</td>'
            f'<td data-label="Play"><b>{_esc(ncaam_play_label(p))}</b></td>'
            f'<td data-label="Book">{_esc(ncaam_book_label(p.get("book")))}</td>'
            f'<td data-label="Stake">{_esc(_stake(p))}</td>'
            f'<td data-label="Result" class="{_esc(st)}">{_esc(_result_label(p))}</td></tr>'
        )
    return (
        '<div class="table-wrap"><table class="export-table">'
        "<thead><tr><th>Tip (ET)</th><th>Game</th><th>Play</th><th>Book</th><th>Stake</th>"
        "<th>Result</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _how_it_works() -> str:
    """Public disclaimer only — no method or model detail on the page."""
    return """
  <p class="phase-note" style="text-align:center">Informational model picks only — <b>no automated betting</b>.</p>
"""


def render_ncaam_page_html(
    *,
    ledger: dict[str, Any],
    signals: dict[str, Any],
    analytics_head: str,
    site_css: str,
    updated: str,
) -> str:
    rec = ncaam_record(ledger, path=NCAAM_LEDGER_PATH)
    return NCAAM_PAGE_TEMPLATE.format(
        site_tabs=render_site_tabs(active="ncaam"),
        site_css=site_css,
        nav_test_css=NAV_TEST_BADGE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        updated=_esc(updated),
        record_block=_render_record(rec, ledger),
        plays_html=_render_locks(signals),
        ledger_html=_ledger_rows(ledger),
        how_it_works=_how_it_works(),
        bottom_bar=render_bottom_bar(active="board"),
        slip_overlay=render_slip_overlay(),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
    )


def build_ncaam_page(
    *,
    docs_dir: Path | None = None,
    signals_path: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_path or NCAAM_LEDGER_PATH
    ledger = load_ledger(ledger_path)
    signals = _load_signals(signals_path)
    updated = signals.get("generated_at") or ledger.get("updated_at") or datetime.now(timezone.utc).isoformat()
    from sharp_scout.site.build import _SITE_CSS, _render_analytics_head

    html = render_ncaam_page_html(
        ledger=ledger,
        signals=signals,
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        site_css=_SITE_CSS,
        updated=updated,
    )
    (out / "ncaam.html").write_text(html)
    (out / "ncaam_ledger.json").write_text(json.dumps(ledger, indent=2, default=str) + "\n")
    rec = ncaam_record(ledger, path=ledger_path)
    (out / "ncaam_record.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    return out / "ncaam.html"


NCAAM_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>College Basketball · Sharp Scout Quant</title>
<meta name="description" content="Sharp Scout Quant NCAAM board — automated spread picks and season record">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{site_css}
{nav_test_css}
{bottom_bar_css}
  .ncaam-wrap {{ max-width: 1200px; margin: 0 auto; padding: 0 20px 48px; }}
  .ncaam-hero {{ text-align: center; padding: 28px 16px 12px; }}
  .ncaam-hero h1 {{ font-family: var(--font-serif); font-size: clamp(28px, 6vw, 38px); font-weight: 500; margin: 8px 0; }}
  .ncaam-hero p {{ color: var(--color-text-muted); font-size: 15px; max-width: 720px; margin: 0 auto; line-height: 1.5; }}
  .ncaam-record {{ display: flex; gap: 14px; flex-wrap: wrap; justify-content: center; margin: 18px 0; }}
  .ncaam-record .pr-card {{ border: 1px solid var(--color-border); border-radius: 8px; padding: 10px 18px; text-align: center; min-width: 110px; }}
  .ncaam-record .pr-val {{ font-size: 24px; font-weight: 800; }}
  .ncaam-record .pr-val.pos {{ color: #15803d; }}
  .ncaam-record .pr-val.neg {{ color: #b91c1c; }}
  .ncaam-record .pr-lbl {{ font-size: 11px; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: .05em; }}
  .ncaam-h2 {{ font-family: var(--font-serif); font-size: 24px; font-weight: 500; margin: 28px 0 10px; }}
  .ncaam-empty {{ background: var(--color-bg-soft); border: 1px dashed var(--color-border); border-radius: 12px; padding: 20px; color: var(--color-text-muted); text-align: center; }}
  .ncaam-empty code {{ font-family: var(--font-mono); font-size: 12px; }}
</style>
</head>
<body class="ss-bottom-bar">
{site_tabs}
<div class="ncaam-wrap">
  <div class="ncaam-hero">
    <h1>College Basketball</h1>
    <p>Automated NCAAM picks. Locks are timestamped before tip; results settle from ESPN finals.</p>
    <p class="phase-note">Updated {updated}</p>
    {record_block}
  </div>
  <h2 class="ncaam-h2">Today&apos;s locked picks</h2>
  {plays_html}
  <h2 class="ncaam-h2">Ledger &amp; results</h2>
  {ledger_html}
  {how_it_works}
</div>
{slip_overlay}
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""
