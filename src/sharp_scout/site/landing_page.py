"""Landing page (docs/index.html) — card layout, filters, and My card."""

from __future__ import annotations

import json
from datetime import timezone
from typing import Any

from sharp_scout.copy.explain import (
    format_kickoff_compact,
    format_play_rationale_short,
    kickoff_sort_key,
    _signal_rank,
)
from sharp_scout.utils.teams import normalize_ncaaf
from sharp_scout.utils.odds import normalize_team
from sharp_scout.site.bottom_bar import (
    BOTTOM_BAR_SCRIPT,
    bottom_bar_css,
    render_bottom_bar,
    render_slip_overlay,
)


def _site_build():
    """Lazy import to avoid circular import with build.py."""
    from sharp_scout.site import build as site_build

    return site_build


def _stage_market_to_signal_market(market: str | None) -> str:
    m = (market or "spread").lower()
    return {
        "spread": "spreads",
        "total": "totals",
        "moneyline": "h2h",
        "h2h": "h2h",
    }.get(m, m)


def _book_label(book: str | None) -> str:
    if not book:
        return "—"
    key = str(book).lower()
    labels = {
        "lowvig": "LowVig",
        "hardrockbet": "Hard Rock Bet",
        "marathonbet": "Marathonbet",
        "pinnacle": "Pinnacle",
        "courtside": "Courtside",
    }
    return labels.get(key, str(book).replace("_", " ").title())


def _landing_team_display(name: str, *, sport: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if sport == "ncaaf":
        from sharp_scout.utils.teams import _simplify_punct, _strip_mascot

        canon = normalize_ncaaf(raw) or raw
        label = _simplify_punct(_strip_mascot(canon))
        return label.title()
    return (normalize_team(raw, "nfl") or raw).title()


def _play_card_id(play: dict[str, Any]) -> str:
    parts = (
        play.get("event_id") or "",
        play.get("market") or "",
        play.get("side") or "",
        play.get("line") or "",
        play.get("sport") or "",
    )
    return "|".join(str(p) for p in parts)


def _conf_tier_index(p_true: Any, edge: Any = None) -> int:
    b = _site_build()
    tier = b._conf_tier(p_true, edge)
    if not tier:
        return 0
    cls = tier[0]
    for i, row in enumerate(b.CONF_TIERS):
        if row[0] == cls:
            return i
    return 0


def _best_price_index(signals: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Best American price per event/market/side/line across all books."""
    best: dict[tuple[Any, ...], dict[str, Any]] = {}

    def line_key(line: Any) -> Any:
        try:
            return round(float(line), 1)
        except (TypeError, ValueError):
            return line

    for s in signals:
        try:
            price = float(s.get("price"))
        except (TypeError, ValueError):
            continue
        key = (
            s.get("event_id"),
            s.get("market"),
            str(s.get("side") or "").lower(),
            line_key(s.get("line")),
        )
        prev = best.get(key)
        if prev is None or price > float(prev.get("price") or -9999):
            best[key] = {"price": price, "book": s.get("book")}
    return best


def _lookup_best_now(play: dict[str, Any], index: dict[tuple[Any, ...], dict[str, Any]]) -> dict[str, Any] | None:
    try:
        line = round(float(play.get("line")), 1)
    except (TypeError, ValueError):
        line = play.get("line")
    key = (
        play.get("event_id"),
        play.get("market"),
        str(play.get("side") or "").lower(),
        line,
    )
    hit = index.get(key)
    if not hit:
        return None
    try:
        posted = float(play.get("price"))
        best = float(hit["price"])
    except (TypeError, ValueError):
        return None
    if best <= posted:
        return None
    return hit


def _match_signal_for_lean(
    row: dict[str, Any],
    hybrid: dict[str, Any],
    signals: list[dict[str, Any]],
) -> dict[str, Any] | None:
    market = _stage_market_to_signal_market(str(row.get("market") or hybrid.get("market")))
    side = str(hybrid.get("side") or "").lower()
    eid = str(row.get("event_id") or "")
    best: dict[str, Any] | None = None
    for s in signals:
        if str(s.get("event_id") or "") != eid:
            continue
        if str(s.get("market") or "") != market:
            continue
        if str(s.get("side") or "").lower() != side:
            continue
        if best is None or _signal_rank(s) > _signal_rank(best):
            best = s
    return best


def landing_lean_plays(
    stage_cards: list[dict[str, Any]],
    *,
    sport: str,
    ledger_plays: list[dict[str, Any]],
    signal_plays: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    b = _site_build()
    rows = b._extract_hybrid_leans(stage_cards, ledger_plays=ledger_plays)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("is_sharp_play"):
            continue
        hybrid = row.get("pick") or {}
        sig = _match_signal_for_lean(row, hybrid, signal_plays)
        if sig:
            play = dict(sig)
        else:
            market = _stage_market_to_signal_market(str(row.get("market")))
            play = {
                "event_id": row.get("event_id"),
                "away_team": row.get("away_team"),
                "home_team": row.get("home_team"),
                "market": market,
                "side": hybrid.get("side"),
                "line": hybrid.get("line"),
                "kickoff": row.get("kickoff"),
                "p_true": hybrid.get("confidence"),
                "edge": None,
                "price": None,
                "book": None,
                "rationale": hybrid.get("reason"),
            }
        play["sport"] = sport
        play["official"] = False
        play["units"] = None
        play["tier"] = "lean"
        out.append(play)
    return sorted(
        out,
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )


def _pick_headline_html(play: dict[str, Any], *, sport: str) -> str:
    b = _site_build()
    market = str(play.get("market") or "")
    side = str(play.get("side") or "").lower()
    line = play.get("line")
    if market == "totals" and line is not None:
        try:
            mag = abs(float(line))
            mag_s = f"{int(mag)}" if mag == int(mag) else f"{mag:g}"
        except (TypeError, ValueError):
            mag_s = str(line)
        label = "Over" if side == "over" else "Under"
        return f"{label} {mag_s} <small>total points</small>"
    team = play.get("home_team") if side == "home" else play.get("away_team")
    if side in ("over", "under"):
        team = side.upper()
    team_s = b._esc(_landing_team_display(str(team or ""), sport=sport))
    if market == "spreads" and line is not None:
        try:
            lv = float(line)
        except (TypeError, ValueError):
            lv = 0.0
        line_s = f"{lv:+g}"
        if lv > 0:
            hint = f"can lose by {lv - 0.5:g} or less"
        elif lv < 0:
            hint = f"must win by {abs(lv) + 0.5:g}+"
        else:
            hint = "pick em"
        return f"{team_s} {line_s} <small>{hint}</small>"
    if market == "h2h":
        return f"{team_s} <small>to win</small>"
    return team_s


def _render_landing_play_card(
    play: dict[str, Any],
    *,
    sport: str,
    official: bool,
    best_index: dict[tuple[Any, ...], dict[str, Any]],
) -> str:
    b = _site_build()
    sport_key = str(play.get("sport") or sport).lower()
    conf_idx = _conf_tier_index(play.get("p_true"), play.get("edge"))
    tier = b.CONF_TIERS[conf_idx]
    cls, label, icons = tier
    conf_html = f'<span class="lp-conf {cls}">{b._esc((f"{icons} {label}".strip()))}</span>'

    p_true = play.get("p_true")
    try:
        win_pct = f"{float(p_true) * 100:.0f}%"
    except (TypeError, ValueError):
        win_pct = "—"

    tier_name = play.get("tier") or "lean"
    units = play.get("units")
    if units is None and official:
        units = {"play": 1.5, "lean": 1.0}.get(tier_name, 0.5)
    if official and units is not None:
        size = f"{units} units"
    elif official:
        size = "1 unit"
    else:
        size = "Not a bet"

    kick = format_kickoff_compact(play.get("kickoff") or play.get("commence_time"))
    away = _landing_team_display(str(play.get("away_team") or ""), sport=sport_key)
    home = _landing_team_display(str(play.get("home_team") or ""), sport=sport_key)
    sport_label = "NFL" if sport_key == "nfl" else "COLLEGE"

    timing_html = b._play_timing_status_html(play, sport=sport_key).replace(
        "play-timing", "lp-when play-timing"
    )

    best_now = _lookup_best_now(play, best_index)
    book = _book_label(play.get("book"))
    posted_price = b._price(play.get("price"))
    if best_now:
        price_html = (
            f"Posted at <b>{posted_price}</b> ({b._esc(book)}). "
            f"Best price now: <b>{b._price(best_now.get('price'))}</b> "
            f"at {b._esc(_book_label(best_now.get('book')))}."
        )
    elif play.get("price") is not None:
        price_html = f"Price: <b>{posted_price}</b> at {b._esc(book)}."
    else:
        price_html = ""

    card_id = b._esc(_play_card_id(play))
    ribbon = "Official play" if official else "Lean only"
    ribbon_cls = "" if official else " lean"
    card_cls = "lp-card official" if official else "lp-card lean-only"
    why = b._esc(format_play_rationale_short(play))

    return (
        f'<article class="{card_cls}" data-sport="{b._esc(sport_key)}" '
        f'data-conf="{conf_idx}" data-play-id="{card_id}">'
        f'<span class="lp-ribbon{ribbon_cls}">{ribbon}</span>'
        f'<div class="lp-matchup"><span class="lp-sport">{sport_label}</span>'
        f"<span>{b._esc(kick)}</span></div>"
        f'<div class="lp-pick">{_pick_headline_html(play, sport=sport_key)}</div>'
        f'<div class="lp-game">{b._esc(away)} at {b._esc(home)}</div>'
        f'<div class="lp-facts">'
        f'<div class="lp-fact"><div class="lp-fact-k">Confidence</div>'
        f'<div class="lp-fact-v">{conf_html}</div></div>'
        f'<div class="lp-fact"><div class="lp-fact-k">Chance to win</div>'
        f'<div class="lp-fact-v">{win_pct}</div></div>'
        f'<div class="lp-fact"><div class="lp-fact-k">Bet size</div>'
        f'<div class="lp-fact-v">{size}</div></div>'
        f"</div>"
        f'<div class="lp-when-wrap">{timing_html}</div>'
        f'<div class="lp-price">{price_html}</div>'
        f'<button type="button" class="lp-add" data-play-id="{card_id}">+ Add to my card</button>'
        f'<details class="lp-why"><summary>Why we like it ›</summary><p>{why}</p></details>'
        f"</article>"
    )


def _season_record_chip(label: str, record: dict[str, Any]) -> str:
    b = _site_build()
    rec = str(record.get("record") or "0-0")
    pnl = float(record.get("pnl_units") or 0)
    pnl_s = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
    cls = "pos" if pnl >= 0 else "neg"
    return f"<b>{b._esc(label)} {rec}</b> <span class=\"{cls}\">{pnl_s}u</span>"


LANDING_PAGE_CSS = """
  body.lp-body { background: #f5f7fa; }
  .lp-header { background: var(--color-navy, #1e3a5f); color: #fff; position: sticky; top: 0; z-index: 5; }
  .lp-hwrap { max-width: 1180px; margin: 0 auto; display: flex; align-items: center; gap: 12px; padding: 10px 16px; }
  .lp-hwrap .ssq-logo { width: 36px; height: 36px; flex-shrink: 0; }
  .lp-brand { font-weight: 700; font-size: 17px; }
  .lp-record { margin-left: auto; font-size: 13px; text-align: right; line-height: 1.35; }
  .lp-record .pos { color: #86efac; font-weight: 700; }
  .lp-record .neg { color: #fca5a5; font-weight: 700; }
  .lp-topnav { display: none; gap: 4px; margin-left: 20px; }
  .lp-topnav a { color: #dbe6f3; text-decoration: none; padding: 8px 12px; border-radius: 8px; font-size: 14px; }
  .lp-topnav a.on { background: rgba(255,255,255,.14); color: #fff; font-weight: 600; }
  .lp-main { max-width: 1180px; margin: 0 auto; padding: 12px 16px 24px; }
  .lp-hero h1 { font-family: var(--font-serif); font-size: 28px; font-weight: 600; margin: 4px 0 2px; }
  .lp-hero p { margin: 0; color: var(--color-text-muted); font-size: 15px; font-weight: 400; }
  .lp-updated { font-size: 13px; color: var(--color-text-muted); margin-top: 6px; }
  .lp-filters { display: flex; gap: 8px; overflow-x: auto; padding: 12px 0 6px; scrollbar-width: none; }
  .lp-chip { flex: 0 0 auto; border: 1px solid var(--color-border); background: #fff; border-radius: 999px;
    padding: 8px 14px; font-size: 15px; cursor: pointer; color: var(--color-text); font-family: var(--font-sans); }
  .lp-chip.on { background: var(--color-navy); border-color: var(--color-navy); color: #fff; }
  .lp-filter-sep { flex: 0 0 1px; background: var(--color-border); margin: 4px 2px; }
  .lp-layout { display: block; margin-top: 8px; }
  .lp-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
  .lp-grid.leans-grid { margin-top: 12px; }
  .lp-card { background: #fff; border: 1px solid var(--color-border); border-radius: 16px; padding: 16px;
    box-shadow: 0 1px 2px rgba(16,24,40,.04); }
  .lp-card.official { border: 2px solid #15803d; }
  .lp-ribbon { display: inline-block; background: #15803d; color: #fff; font-size: 11px; font-weight: 800;
    letter-spacing: .04em; padding: 3px 9px; border-radius: 6px; text-transform: uppercase; }
  .lp-ribbon.lean { background: #64748b; }
  .lp-matchup { display: flex; justify-content: space-between; margin-top: 10px; color: var(--color-text-muted); font-size: 13px; }
  .lp-sport { font-weight: 700; color: var(--color-navy); letter-spacing: .04em; font-size: 11px; }
  .lp-pick { font-size: 22px; font-weight: 800; margin: 6px 0 2px; line-height: 1.25; }
  .lp-pick small { font-size: 15px; font-weight: 600; color: var(--color-text-muted); }
  .lp-game { font-size: 15px; }
  .lp-facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }
  .lp-fact { background: #f5f7fa; border-radius: 10px; padding: 8px 10px; }
  .lp-fact-k { font-size: 11px; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: .04em; }
  .lp-fact-v { font-size: 15px; font-weight: 700; margin-top: 2px; }
  .lp-conf { display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; }
  .lp-when-wrap .lp-when, .lp-when-wrap .play-timing { display: flex; gap: 8px; align-items: center;
    border-radius: 10px; padding: 10px 12px; font-size: 14px; font-weight: 600; width: 100%; box-sizing: border-box; }
  .lp-when.hold, .play-timing.hold { background: #fff7e6; color: #b45309; }
  .lp-when.watch, .play-timing.watch { background: #e8f0ff; color: #1e40af; }
  .lp-when.soon, .play-timing.soon { background: #e8f0ff; color: #1e40af; }
  .lp-when.lock, .play-timing.lock { background: #ecfdf3; color: #15803d; }
  .lp-when.started, .play-timing.started { background: #f1f5f9; color: #64748b; }
  .lp-when::before, .play-timing.hold::before, .play-timing.watch::before, .play-timing.soon::before,
  .play-timing.lock::before, .play-timing.started::before {
    content: ''; width: 9px; height: 9px; border-radius: 50%; background: currentColor; flex-shrink: 0;
  }
  .lp-price { font-size: 14px; color: var(--color-text-muted); margin-top: 10px; }
  .lp-price b { color: var(--color-text); }
  .lp-add { width: 100%; margin-top: 12px; border: 0; border-radius: 12px; padding: 14px; font-size: 16px;
    font-weight: 700; background: var(--color-navy); color: #fff; cursor: pointer; font-family: var(--font-sans); }
  .lp-add.added { background: #15803d; }
  .lp-why { margin-top: 10px; font-size: 14px; color: var(--color-text-muted); }
  .lp-why summary { cursor: pointer; color: var(--color-navy); font-weight: 600; list-style: none; }
  .lp-why summary::-webkit-details-marker { display: none; }
  .lp-empty { background: #fff; border: 1px dashed var(--color-border); border-radius: 16px; padding: 18px;
    color: var(--color-text-muted); text-align: center; grid-column: 1 / -1; }
  .lp-leans { margin-top: 20px; }
  .lp-leans > summary { cursor: pointer; font-weight: 700; font-size: 17px; padding: 10px 0; list-style: none; }
  .lp-leans > summary::-webkit-details-marker { display: none; }
  .lp-leans-note { font-weight: 400; color: var(--color-text-muted); font-size: 14px; }
  .lp-help { margin-top: 22px; background: #fff; border: 1px solid var(--color-border); border-radius: 16px;
    padding: 14px 16px; font-size: 14px; color: var(--color-text-muted); line-height: 1.55; }
  .lp-more { display: block; text-align: center; margin: 18px 0 8px; color: var(--color-navy); font-weight: 600; }
  .lp-slip { display: none; }
  .lp-slip-sidebar { display: none; }
  .lp-slip h2 { font-size: 18px; margin: 0 0 4px; font-family: var(--font-serif); }
  .lp-slip-sub { font-size: 13px; color: var(--color-text-muted); margin-bottom: 10px; }
  .lp-slip ul { list-style: none; margin: 0; padding: 0; }
  .lp-slip li { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0;
    border-top: 1px solid var(--color-border); font-size: 15px; }
  .lp-slip li small { display: block; color: var(--color-text-muted); font-size: 13px; }
  .lp-slip li button { border: 0; background: none; color: #b91c1c; cursor: pointer; font-size: 13px; }
  .lp-slip .lp-copy { width: 100%; margin-top: 10px; border: 1px solid var(--color-navy); background: #fff;
    color: var(--color-navy); border-radius: 12px; padding: 12px; font-weight: 700; cursor: pointer; font-family: var(--font-sans); }
  @media (min-width: 900px) {
    .lp-topnav { display: flex; }
    .lp-hero h1 { font-size: 32px; }
    .lp-layout { display: grid; grid-template-columns: 1fr 320px; gap: 24px; align-items: start; }
    .lp-grid.official-grid { grid-template-columns: 1fr; }
    .lp-grid.leans-grid { grid-template-columns: 1fr 1fr; }
    .lp-slip.lp-slip-sidebar { display: block; position: sticky; top: 76px; background: #fff; border: 1px solid var(--color-border);
      border-radius: 16px; padding: 16px; }
  }
"""

LANDING_FILTER_SCRIPT = """
<script>
(function () {
  var filters = { sport: 'all', conf: 0 };

  function allCards() {
    return Array.prototype.slice.call(document.querySelectorAll('.lp-card'));
  }

  function applyFilters() {
    allCards().forEach(function (card) {
      var sport = card.getAttribute('data-sport');
      var conf = parseInt(card.getAttribute('data-conf') || '0', 10);
      var ok = (filters.sport === 'all' || sport === filters.sport) && conf >= filters.conf;
      card.style.display = ok ? '' : 'none';
    });
    var vis = allCards().filter(function (c) { return c.style.display !== 'none'; });
    var empty = document.getElementById('lp-official-empty');
    if (empty) empty.style.display = vis.some(function (c) { return c.classList.contains('official'); }) ? 'none' : '';
  }

  document.addEventListener('click', function (e) {
    var chip = e.target.closest('.lp-chip');
    if (!chip) return;
    var f = chip.getAttribute('data-f');
    var v = chip.getAttribute('data-v');
    if (f === 'conf') filters.conf = parseInt(v, 10);
    else filters[f] = v;
    document.querySelectorAll('.lp-chip[data-f="' + f + '"]').forEach(function (c) {
      c.classList.toggle('on', c === chip);
    });
    applyFilters();
  });

  applyFilters();
})();
</script>
"""


def render_landing_page(
    *,
    site_css: str,
    ncaaf_plays: list[dict[str, Any]],
    nfl_plays: list[dict[str, Any]],
    ncaaf_leans: list[dict[str, Any]],
    nfl_leans: list[dict[str, Any]],
    ncaaf_record: dict[str, Any],
    nfl_record: dict[str, Any],
    board_updated: str,
    analytics_head: str,
    nfl_season_week: int | None = None,
    ncaaf_season_week: int | None = None,
    nfl_signal_plays: list[dict[str, Any]],
    ncaaf_signal_plays: list[dict[str, Any]],
) -> str:
    best_index = _best_price_index(list(nfl_signal_plays) + list(ncaaf_signal_plays))
    official_ncaaf = [dict(p, sport="ncaaf") for p in ncaaf_plays]
    official_nfl = [dict(p, sport="nfl") for p in nfl_plays]
    official = sorted(
        official_ncaaf + official_nfl,
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    leans = list(ncaaf_leans) + list(nfl_leans)

    b = _site_build()
    banners = b.early_season_banner_html(nfl_season_week) + b.early_season_banner_html(ncaaf_season_week)

    official_html = "".join(
        _render_landing_play_card(p, sport=str(p.get("sport")), official=True, best_index=best_index)
        for p in official
    )
    if not official_html:
        official_html = (
            '<div class="lp-empty" id="lp-official-empty">'
            "No official plays posted this week yet. New plays appear after each model run."
            "</div>"
        )

    leans_html = "".join(
        _render_landing_play_card(p, sport=str(p.get("sport")), official=False, best_index=best_index)
        for p in leans
    )
    if not leans_html:
        leans_html = '<div class="lp-empty">No model leans on the current slate.</div>'

    record_html = (
        _season_record_chip("CFB", ncaaf_record)
        + '<br class="lp-rec-br"> '
        + _season_record_chip("NFL", nfl_record)
    )

    return LANDING_TEMPLATE.format(
        site_css=site_css,
        landing_css=LANDING_PAGE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        ssq_logo=b._ssq_logo_svg(embedded=True),
        board_updated=b._esc(board_updated),
        record_html=record_html,
        early_banners=banners,
        official_cards=official_html,
        lean_count=len(leans),
        leans_cards=leans_html,
        bottom_bar=render_bottom_bar(active="plays"),
        slip_overlay=render_slip_overlay(),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
        landing_filter_script=LANDING_FILTER_SCRIPT,
        timing_script=b._TIMING_SCRIPT,
    )


LANDING_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>Today's best plays · Sharp Scout Quant</title>
<meta name="description" content="Sharp Scout Quant — today's recommended NFL and college football plays">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="apple-touch-icon" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<script>
  (function () {{
    var h = window.location.hash || '';
    if (h.indexOf('#tab-') === 0) window.location.replace('board.html' + h);
  }})();
</script>
<style>
{site_css}
{bottom_bar_css}
{landing_css}
</style>
</head>
<body class="lp-body ss-bottom-bar">
<header class="lp-header"><div class="lp-hwrap">
  {ssq_logo}
  <div class="lp-brand">Sharp Scout</div>
  <nav class="lp-topnav" aria-label="Primary">
    <a class="on" href="index.html">Today's plays</a>
    <a href="board.html#tab-plays">Results</a>
    <a href="board.html#tab-guide">How it works</a>
    <a href="board.html">Full board</a>
  </nav>
  <div class="lp-record"><span class="lp-rec-label">Season record</span><br>{record_html}</div>
</div></header>

<main class="lp-main">
  <div class="lp-hero">
    <h1>Today's best plays</h1>
    <p>Only the bets we actually post. Tap <b>Add to my card</b> to save the ones you like.</p>
    <div class="lp-updated">Updated {board_updated}</div>
    <div id="gameday-scores-bar" class="gameday-scores-bar" aria-live="polite" style="margin-top:10px"></div>
  </div>

  <div class="lp-filters" role="toolbar" aria-label="Filters">
    <button type="button" class="lp-chip on" data-f="sport" data-v="all">All</button>
    <button type="button" class="lp-chip" data-f="sport" data-v="ncaaf">College</button>
    <button type="button" class="lp-chip" data-f="sport" data-v="nfl">NFL</button>
    <span class="lp-filter-sep"></span>
    <button type="button" class="lp-chip on" data-f="conf" data-v="0">Any confidence</button>
    <button type="button" class="lp-chip" data-f="conf" data-v="2">💎 Strong or better</button>
  </div>

  {early_banners}

  <div class="lp-layout">
    <section>
      <div class="lp-grid official-grid" id="lp-official">{official_cards}</div>
      <details class="lp-leans">
        <summary>Model leans ({lean_count})<br>
          <span class="lp-leans-note">Not official bets. Smaller edges the model noticed. Tap to show.</span>
        </summary>
        <div class="lp-grid leans-grid">{leans_cards}</div>
      </details>
      <div class="lp-help">
        <b>How to read a play.</b> <b>Confidence</b> is how likely the bet is to win, plus how good the price is.
        💎💎 Top pick (wins about 7 in 10) · 💎 Strong (about 6 in 10) · Good (55%+) · Lean (under 55%).
        Even top picks lose sometimes. <b>Bet size</b> is in units: 1 unit is your normal bet.
      </div>
      <a class="lp-more" href="board.html">See the full research board →</a>
    </section>
    <aside class="lp-slip lp-slip-sidebar" id="lp-slip">
      <h2>My card <span class="lp-badge" id="lp-slip-count">0</span></h2>
      <div class="lp-slip-sub">Saved on this phone or computer only.</div>
      <ul id="lp-slip-list"></ul>
      <button type="button" class="lp-copy" id="lp-copy-btn">Copy my card</button>
    </aside>
  </div>
</main>

{slip_overlay}
{bottom_bar}
<div class="footer">
  Sharp Scout Quant · research and entertainment only · not betting advice.<br>
  Updated {board_updated}
</div>
{timing_script}
{bottom_bar_script}
{landing_filter_script}
</body>
</html>
"""
