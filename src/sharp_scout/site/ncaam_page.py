"""College basketball (NCAAM) public board — shell until model pipeline lands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR, ROOT, get_settings
from sharp_scout.ledger.tracker import compute_record, load_ledger
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


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load_signals() -> dict[str, Any]:
    if NCAAM_SIGNALS_PATH.exists():
        try:
            return json.loads(NCAAM_SIGNALS_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _render_record(rec: dict[str, Any]) -> str:
    record = str(rec.get("record") or "0-0")
    pnl = float(rec.get("pnl_units") or 0)
    pnl_s = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
    cls = "pos" if pnl >= 0 else "neg"
    return (
        f'<div class="ncaam-record">'
        f'<div class="pr-card"><div class="pr-val">{_esc(record)}</div>'
        f'<div class="pr-lbl">Season record</div></div>'
        f'<div class="pr-card"><div class="pr-val {cls}">{pnl_s}u</div>'
        f'<div class="pr-lbl">Units P&amp;L</div></div>'
        f"</div>"
    )


def _render_plays(signals: dict[str, Any]) -> str:
    plays = signals.get("plays") or signals.get("official_plays") or []
    if not plays:
        return (
            '<div class="ncaam-empty">'
            "<p><b>Plays post once the model run starts.</b></p>"
            "<p>The NCAAM engine will write picks to "
            "<code>data/ncaam_latest_signals.json</code> and the ledger below.</p>"
            "</div>"
        )
    rows = []
    for p in plays:
        away = _esc(p.get("away_team") or "")
        home = _esc(p.get("home_team") or "")
        market = _esc(p.get("market") or "")
        side = _esc(p.get("side") or "")
        line = p.get("line")
        line_s = f" {_esc(line)}" if line is not None else ""
        rows.append(
            f"<tr><td>{away} @ {home}</td><td>{market}</td>"
            f"<td>{side}{line_s}</td></tr>"
        )
    body = "".join(rows)
    return (
        '<div class="table-wrap"><table class="export-table plays-table">'
        "<thead><tr><th>Game</th><th>Market</th><th>Play</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _ledger_rows(ledger: dict[str, Any]) -> str:
    plays = list(ledger.get("plays") or [])
    if not plays:
        return "<p class=\"ncaam-empty\">No graded NCAAM plays yet.</p>"
    rows = []
    for p in reversed(plays[-40:]):
        res = p.get("result") or "pending"
        rows.append(
            f"<tr><td>{_esc(p.get('kickoff', ''))}</td>"
            f"<td>{_esc(p.get('away_team', ''))} @ {_esc(p.get('home_team', ''))}</td>"
            f"<td>{_esc(p.get('market', ''))} {_esc(p.get('side', ''))}</td>"
            f"<td>{_esc(res)}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table">'
        "<thead><tr><th>Kickoff</th><th>Game</th><th>Play</th><th>Result</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_ncaam_page_html(
    *,
    ledger: dict[str, Any],
    signals: dict[str, Any],
    analytics_head: str,
    site_css: str,
    updated: str,
) -> str:
    rec = compute_record(ledger, path=NCAAM_LEDGER_PATH)
    return NCAAM_PAGE_TEMPLATE.format(
        site_tabs=render_site_tabs(active="ncaam"),
        site_css=site_css,
        nav_test_css=NAV_TEST_BADGE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        updated=_esc(updated),
        record_block=_render_record(rec),
        plays_html=_render_plays(signals),
        ledger_html=_ledger_rows(ledger),
        bottom_bar=render_bottom_bar(active="board"),
        slip_overlay=render_slip_overlay(),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
    )


def build_ncaam_page(*, docs_dir: Path | None = None) -> Path:
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)
    ledger = load_ledger(NCAAM_LEDGER_PATH)
    signals = _load_signals()
    updated = signals.get("generated_at") or ledger.get("updated_at") or datetime.now(timezone.utc).isoformat()
    from sharp_scout.site.build import _SITE_CSS, _render_analytics_head, _ssq_logo_svg

    html = render_ncaam_page_html(
        ledger=ledger,
        signals=signals,
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        site_css=_SITE_CSS,
        updated=updated,
    )
    (out / "ncaam.html").write_text(html)
    (out / "ncaam_ledger.json").write_text(json.dumps(ledger, indent=2, default=str) + "\n")
    rec = compute_record(ledger, path=NCAAM_LEDGER_PATH)
    (out / "ncaam_record.json").write_text(json.dumps(rec, indent=2, default=str) + "\n")
    return out / "ncaam.html"


NCAAM_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>College Basketball · Sharp Scout Quant</title>
<meta name="description" content="Sharp Scout Quant NCAAM board — model plays and season record">
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
  .ncaam-hero p {{ color: var(--color-text-muted); font-size: 15px; max-width: 640px; margin: 0 auto; line-height: 1.5; }}
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
    <p>NCAAM sides and totals board. Model output lands here when the Gem2/Quant blend pipeline is wired.</p>
    <p class="phase-note">Updated {updated}</p>
    {record_block}
  </div>
  <h2 class="ncaam-h2">Today&apos;s plays</h2>
  {plays_html}
  <h2 class="ncaam-h2">Ledger &amp; results</h2>
  {ledger_html}
</div>
{slip_overlay}
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""
