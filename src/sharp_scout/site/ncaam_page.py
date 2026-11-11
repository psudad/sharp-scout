"""College Basketball (NCAAM) public board."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sharp_scout.config import DATA_DIR, ROOT, get_settings
from sharp_scout.copy.explain import format_display_datetime_et
from sharp_scout.ledger.day_record import format_yesterday_stat_value, summarize_yesterday
from sharp_scout.ledger.tracker import compute_record, load_ledger
from sharp_scout.site.bottom_bar import (
    BOTTOM_BAR_SCRIPT,
    bottom_bar_css,
    render_bottom_bar,
    render_slip_overlay,
)
from sharp_scout.site.build import _remove_unpublished_docs, public_ledger, publish_site_icons
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


def _fmt_et(iso: str | None) -> str:
    return format_display_datetime_et(iso)


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
    yest = summarize_yesterday(
        ledger.get("plays") or [],
        include=lambda p: bool(p.get("side")) and str(p.get("status") or "").lower() not in _NOT_A_PLAY,
    )
    yest_val = format_yesterday_stat_value(yest)
    yest_cls = "pos" if float(yest.get("pnl_units") or 0) >= 0 else "neg" if yest.get("n") else ""
    return (
        f'<div class="summary-grid summary-grid-5 ncaam-record">'
        f'<div class="stat-card"><div class="stat-val {yest_cls}">{_esc(yest_val)}</div>'
        f'<div class="stat-label">Yesterday · {_esc(yest["day_label"])}</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_esc(record)}</div>'
        f'<div class="stat-label">Season record</div></div>'
        f'<div class="stat-card"><div class="stat-val {cls}">{pnl_s}u</div>'
        f'<div class="stat-label">Units P&amp;L</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_esc(roi_s)}</div>'
        f'<div class="stat-label">ROI</div></div>'
        f'<div class="stat-card"><div class="stat-val">{_esc(clv_pct)}</div>'
        f'<div class="stat-label">CLV beat close</div></div>'
        f"</div>"
    )


PLAY_BADGE_LABEL = "Play"
TRACKING_ONLY_LABEL = "Tracking only, not a bet"


def _tip_et_date(p: dict[str, Any]):
    iso = p.get("tip") or p.get("kickoff") or p.get("commence_time")
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ET).date()
    except ValueError:
        return None


def _is_official_play(p: dict[str, Any]) -> bool:
    return bool(p.get("side")) and str(p.get("status") or "").lower() not in _NOT_A_PLAY


def _is_tracking_play(p: dict[str, Any]) -> bool:
    st = str(p.get("status") or "").lower()
    if st in _NOT_A_PLAY or st in {"lean", "shadow", "near_miss"}:
        return True
    return False


def _dedupe_key(p: dict[str, Any]) -> tuple:
    return (
        str(p.get("id") or p.get("event_id") or p.get("espn_id") or ""),
        str(p.get("away_team") or ""),
        str(p.get("home_team") or ""),
        str(p.get("market") or ""),
        str(p.get("side") or p.get("selection") or ""),
        str(p.get("line") or ""),
        str(p.get("tip") or ""),
    )


def _merge_plays(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for p in group:
            key = _dedupe_key(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    out.sort(key=lambda item: str(item.get("tip") or ""))
    return out


def _official_board_plays(ledger: dict[str, Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Today's official ET-day card, plus any still-pending official picks."""
    today = (now or datetime.now(ET)).astimezone(ET).date()
    official = [p for p in (ledger.get("plays") or []) if _is_official_play(p)]
    todays = [p for p in official if _tip_et_date(p) == today]
    pending = [p for p in official if str(p.get("status") or "pending").lower() == "pending"]
    return _merge_plays(todays, pending)


def _status_chip(p: dict[str, Any]) -> str:
    st = str(p.get("status") or "pending").lower()
    if st in ("", "pending"):
        return '<span class="card-result pending">LOCKED</span>'
    cls = st if st in ("win", "loss", "push", "void") else "pending"
    return f'<span class="card-result {_esc(cls)}">{_esc(_result_label(p))}</span>'


def _render_play_card(
    p: dict[str, Any],
    *,
    badge: str = PLAY_BADGE_LABEL,
    badge_cls: str = "badge-play",
    card_cls: str = "sharp-play",
) -> str:
    away = p.get("away_team") or ""
    home = p.get("home_team") or ""
    sub = f"{_fmt_et(p.get('tip'))} · {away} @ {home} · {ncaam_book_label(p.get('book'))}"
    return f"""
      <div class="play-card {card_cls}">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge {badge_cls}">{_esc(badge)}</span>
            <div class="play-title"><b>{_esc(ncaam_play_label(p))}</b></div>
            <div class="play-subtitle">{_esc(sub)}</div>
          </div>
          <div class="units-badge">{_esc(_stake(p))}</div>
        </div>
        {_status_chip(p)}
      </div>"""


def _render_locks(signals: dict[str, Any]) -> str:
    locks = [p for p in (signals.get("locks") or []) if _is_official_play(p)]
    if not locks:
        locks = _official_board_plays(load_ledger(NCAAM_LEDGER_PATH))
    if not locks:
        return (
            '<div class="ncaam-empty">'
            "<p><b>No locked plays yet today.</b></p>"
            "<p>Official plays appear here once they are posted for today&apos;s slate.</p></div>"
        )
    cards = "".join(_render_play_card(p) for p in locks)
    return f'<div class="ncaam-plays">{cards}</div>'


def _tracking_items(ledger: dict[str, Any], signals: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in ledger.get("plays") or []:
        if _is_tracking_play(p):
            items.append(p)
    for key in ("leans", "near_misses", "shadow", "no_play"):
        extra = signals.get(key)
        if isinstance(extra, list):
            items.extend(x for x in extra if isinstance(x, dict))
    return _merge_plays(items)


def _render_tracking(ledger: dict[str, Any], signals: dict[str, Any] | None = None) -> str:
    items = _tracking_items(ledger, signals or {})
    if not items:
        return ""
    labeled: list[dict[str, Any]] = []
    anonymous = 0
    for p in items:
        if p.get("away_team") or p.get("home_team") or p.get("side") or p.get("selection"):
            labeled.append(p)
        else:
            anonymous += 1
    if not labeled and not anonymous:
        return ""
    rows = []
    for p in labeled:
        label = ncaam_play_label(p) if (p.get("side") or p.get("selection")) else "—"
        away = _esc(p.get("away_team") or "")
        home = _esc(p.get("home_team") or "")
        note = p.get("reason") or p.get("status") or "tracking"
        rows.append(
            f'<tr><td data-label="Game">{away} @ {home}</td>'
            f'<td data-label="Note">{_esc(label)}</td>'
            f'<td data-label="Status">{_esc(note)}</td></tr>'
        )
    table = ""
    if rows:
        table = (
            '<div class="table-wrap"><table class="export-table">'
            "<thead><tr><th>Game</th><th>Note</th><th>Status</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    extra = ""
    if anonymous:
        noun = "game" if anonymous == 1 else "games"
        prefix = f"{anonymous} other {noun}" if labeled else f"{anonymous} {noun}"
        extra = (
            f'<p class="ncaam-tracking-note">{prefix} were reviewed '
            "and did not produce an official pick.</p>"
        )
    return (
        '<details class="ncaam-tracking">'
        f"<summary>{_esc(TRACKING_ONLY_LABEL)}</summary>"
        '<p class="ncaam-tracking-note">These are not official picks. Do not play them.</p>'
        f"{table}{extra}"
        "</details>"
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
        tracking_html=_render_tracking(ledger, signals),
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
    updated = format_display_datetime_et(
        signals.get("generated_at") or ledger.get("updated_at") or datetime.now(timezone.utc)
    )
    from sharp_scout.site.build import _SITE_CSS, _render_analytics_head

    html = render_ncaam_page_html(
        ledger=ledger,
        signals=signals,
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        site_css=_SITE_CSS,
        updated=updated,
    )
    (out / "ncaam.html").write_text(html)
    publish_site_icons(out)
    _remove_unpublished_docs(out)
    (out / "ncaam_ledger.json").write_text(
        json.dumps(public_ledger(ledger), indent=2, default=str) + "\n"
    )
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
<link rel="icon" type="image/png" sizes="32x32" href="assets/favicon-32.png">
<link rel="icon" href="favicon.ico" sizes="48x48">
<link rel="apple-touch-icon" href="assets/apple-touch-icon.png">
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
  .ncaam-record {{ margin: 18px 0 8px; }}
  .ncaam-plays {{ margin: 0 0 8px; }}
  .badge-play {{ font-weight: 700; letter-spacing: .12em; }}
  .ncaam-tracking {{
    margin: 28px 0 8px;
    border: 1px dashed var(--color-border);
    border-radius: 8px;
    padding: 10px 14px;
    background: var(--color-bg-soft);
    color: var(--color-text-muted);
  }}
  .ncaam-tracking > summary {{
    cursor: pointer;
    font-weight: 600;
    color: var(--color-text-muted);
    list-style: none;
  }}
  .ncaam-tracking > summary::-webkit-details-marker {{ display: none; }}
  .ncaam-tracking-note {{ font-size: 13px; margin: 8px 0 12px; }}
  .ncaam-tracking table {{ opacity: 0.72; }}
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
  <div class="plays-heading">
    <div class="plays-heading-main">TODAY&apos;S PLAYS — BET THESE</div>
    <div class="plays-heading-sub">Official locked picks. If we posted a play, it appears here and stays here after the game with the result.</div>
  </div>
  {plays_html}
  <h2 class="ncaam-h2">Ledger &amp; results</h2>
  {ledger_html}
  {tracking_html}
  {how_it_works}
</div>
{slip_overlay}
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""
