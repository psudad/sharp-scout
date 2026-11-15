"""NBA paper plays embed for index.html and board.html (testing only, not the NFL card)."""

from __future__ import annotations

from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.nba.slate_et import format_kickoff_day_time_et
from sharp_scout.site.nba_page import (
    NBA_NEXT_SCAN_SCRIPT,
    NO_LIVE_SCAN_MESSAGE,
    _game_pick,
    _merge_signals_with_todays_open_ledger,
    _next_scan_context,
    has_live_nba_scan,
    load_nba_site_sources,
    public_nba_ledger,
    public_nba_signals,
    upcoming_slate_items,
    _book_label,
    _price,
)
from sharp_scout.utils.slate import parse_commence

SECTION_TITLE = "NBA paper plays — testing only"


def _esc(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def nba_home_upcoming_game_lines() -> dict[str, Any]:
    """Today's qualifying NBA game-line paper plays (same pool as nba.html upcoming block)."""
    sources = load_nba_site_sources()
    signals_payload = sources["signals_payload"]
    live_scan = sources["live_scan"]
    pub_signals = public_nba_signals(signals_payload)
    pub_ledger = public_nba_ledger(sources["ledger"])
    picks = _merge_signals_with_todays_open_ledger(
        list(pub_signals.get("signals") or []),
        pub_ledger,
    )
    picks_slate = upcoming_slate_items(picks)
    side_picks = [p for p in picks_slate if (p.get("play_type") or "side") != "prop"]
    generated = parse_commence(pub_signals.get("generated_at"))
    from sharp_scout.site.build import _format_timestamp_et

    updated = _format_timestamp_et(generated) if generated else "—"
    next_scan, next_scans_json = _next_scan_context(sources.get("paper_store"))
    return {
        "plays": side_picks,
        "live_scan": live_scan,
        "updated": updated,
        "next_scan": next_scan,
        "next_scans_json": next_scans_json,
    }


def _render_home_play_card(play: dict[str, Any]) -> str:
    settings = get_settings()
    unit_d = float(settings.nba_unit_dollars)
    tip = format_kickoff_day_time_et(play.get("kickoff"))
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    pick = _game_pick(play)
    market = str(play.get("market") or "")
    line = play.get("line")
    book = _book_label(play.get("book"))
    price = _price(play.get("price"))
    line_s = f"{float(line):g}" if isinstance(line, (int, float)) else "—"
    if market == "h2h":
        line_disp = "ML"
    elif market == "totals":
        line_disp = f"Total {line_s}"
    else:
        line_disp = f"Line {line_s}"
    units = play.get("units")
    units_f = float(units) if isinstance(units, (int, float)) else None
    units_s = f"{units_f:.2f}u" if units_f is not None else "—"
    stake_s = f"${units_f * unit_d:.0f}" if units_f is not None else ""

    return (
        f'<article class="lp-nba-card" data-nba-paper="1">'
        f'<div class="lp-nba-card-row">'
        f'<span class="lp-nba-tip">{_esc(tip)}</span>'
        f'<span class="lp-nba-stake">{_esc(units_s)}'
        f'{f"<span class=\"lp-nba-stake-usd\">{_esc(stake_s)}</span>" if stake_s else ""}'
        f"</span></div>"
        f'<div class="lp-nba-game">{_esc(away)} @ {_esc(home)}</div>'
        f'<div class="lp-nba-pick">{_esc(pick)}</div>'
        f'<div class="lp-nba-odds">'
        f'<span class="lp-nba-odds-k">Line</span> <span class="lp-nba-odds-v">{_esc(line_disp)}</span>'
        f'<span class="lp-nba-odds-sep">·</span>'
        f'<span class="lp-nba-odds-k">Book</span> <span class="lp-nba-odds-v">{_esc(book)}</span>'
        f'<span class="lp-nba-odds-sep">·</span>'
        f'<span class="lp-nba-odds-k">Price</span> <span class="lp-nba-odds-v">{_esc(price)}</span>'
        f"</div>"
        f'<span class="lp-nba-paper-tag">Paper only</span>'
        f"</article>"
    )


def _render_empty(*, live_scan: bool, next_scan: str, next_scans_json: str) -> str:
    if not live_scan:
        body = (
            f"<p>{_esc(NO_LIVE_SCAN_MESSAGE)}</p>"
            f'<p class="lp-nba-empty-sub">Next scan '
            f'<span class="nba-next-scan-time" data-nba-next-scans=\'{_esc(next_scans_json)}\'>'
            f"{_esc(next_scan)}</span>.</p>"
        )
    else:
        body = (
            "<p><strong>No NBA paper plays yet today.</strong></p>"
            f'<p class="lp-nba-empty-sub">Next scan '
            f'<span class="nba-next-scan-time" data-nba-next-scans=\'{_esc(next_scans_json)}\'>'
            f"{_esc(next_scan)}</span>.</p>"
        )
    return f'<div class="lp-nba-empty" role="status">{body}</div>'


def render_nba_home_section(*, variant: str = "landing") -> str:
    """HTML block for NBA paper plays on index.html and board.html."""
    ctx = nba_home_upcoming_game_lines()
    plays = ctx["plays"]
    live_scan = ctx["live_scan"]
    next_scan = ctx["next_scan"]
    next_scans_json = ctx["next_scans_json"]
    updated = ctx["updated"]

    cards = "".join(_render_home_play_card(p) for p in plays)
    plays_html = (
        f'<div class="lp-nba-grid">{cards}</div>'
        if cards
        else _render_empty(
            live_scan=live_scan,
            next_scan=next_scan,
            next_scans_json=next_scans_json,
        )
    )
    wrap_cls = "lp-nba-section" if variant == "landing" else "board-nba-section"
    updated_line = (
        f'<p class="lp-nba-updated">NBA scan {_esc(updated)}</p>' if live_scan and updated != "—" else ""
    )
    section = (
        f'<section class="{wrap_cls}" aria-labelledby="nba-home-heading" data-nba-paper-section="1">'
        f'<div class="lp-nba-head">'
        f'<h2 class="lp-nba-title" id="nba-home-heading">{_esc(SECTION_TITLE)}</h2>'
        f'<p class="lp-nba-note">Paper only — never live bets. '
        f'<a href="nba.html">Full NBA board →</a></p>'
        f"{updated_line}"
        f"</div>"
        f"{plays_html}"
        f"</section>"
    )
    return section + NBA_NEXT_SCAN_SCRIPT


NBA_HOME_SECTION_CSS = """
  .lp-nba-section, .board-nba-section {
    margin: 28px 0 8px;
    padding: 18px 16px 20px;
    background: #fff;
    border: 2px dashed #cbd5e1;
    border-radius: 16px;
    box-shadow: 0 1px 2px rgba(16,24,40,.04);
  }
  .board-nba-section {
    max-width: 1240px;
    margin-left: auto;
    margin-right: auto;
    padding: 20px 16px 24px;
  }
  .lp-nba-title {
    font-family: var(--font-serif);
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 6px;
    color: var(--color-navy, #1e3a5f);
  }
  .lp-nba-note {
    margin: 0 0 12px;
    font-size: 14px;
    color: var(--color-text-muted);
    line-height: 1.45;
  }
  .lp-nba-note a { color: var(--color-navy, #1e3a5f); font-weight: 700; }
  .lp-nba-updated { margin: 0 0 10px; font-size: 12px; color: var(--color-text-muted); }
  .lp-nba-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 12px;
  }
  @media (min-width: 640px) { .lp-nba-grid { grid-template-columns: 1fr 1fr; } }
  @media (min-width: 1024px) { .lp-nba-grid { grid-template-columns: repeat(3, 1fr); } }
  .lp-nba-card {
    border: 1px solid var(--color-border);
    border-left: 3px solid #64748b;
    border-radius: 12px;
    padding: 14px 14px 12px;
    background: #fafbfc;
    position: relative;
  }
  .lp-nba-card-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
    color: var(--color-text-muted);
    margin-bottom: 6px;
  }
  .lp-nba-stake {
    font-family: var(--font-mono);
    font-weight: 700;
    color: var(--color-text);
    font-size: 13px;
    text-align: right;
  }
  .lp-nba-stake-usd {
    display: block;
    font-size: 11px;
    font-weight: 600;
    color: var(--color-text-muted);
  }
  .lp-nba-game {
    font-size: 13px;
    color: var(--color-text-muted);
    margin-bottom: 4px;
  }
  .lp-nba-pick {
    font-size: 20px;
    font-weight: 800;
    line-height: 1.2;
    margin-bottom: 8px;
    color: var(--color-text);
  }
  .lp-nba-odds {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 6px;
    font-size: 13px;
    margin-bottom: 6px;
  }
  .lp-nba-odds-k {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--color-text-muted);
    font-weight: 700;
  }
  .lp-nba-odds-v { font-weight: 700; color: var(--color-text); }
  .lp-nba-odds-sep { color: #cbd5e1; }
  .lp-nba-paper-tag {
    display: inline-block;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: #64748b;
    background: #f1f5f9;
    padding: 3px 8px;
    border-radius: 6px;
  }
  .lp-nba-empty {
    text-align: center;
    padding: 16px 12px;
    border: 1px dashed var(--color-border);
    border-radius: 12px;
    color: var(--color-text-muted);
    font-size: 15px;
  }
  .lp-nba-empty-sub { font-size: 13px; margin-top: 8px; }
"""