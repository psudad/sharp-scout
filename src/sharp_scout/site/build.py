"""Build static GitHub Pages site from ledger + latest signals."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR, ROOT, get_settings
from sharp_scout.copy.explain import (
    BOARD_STAT_TIPS,
    collapse_best_signals,
    describe_splits_board,
    describe_stage_pick,
    format_kickoff_et,
    format_kickoff_compact,
    format_play_rationale,
    kickoff_sort_key,
    STAGE_COLUMN_TIPS,
    STAGE_LABELS,
    HYBRID_LEANS_SECTION_NOTE,
    STAGE_RECORD_SECTION_NOTE,
    STAGE_RECORD_TIPS,
)
from sharp_scout.ledger.tracker import compute_record, load_ledger
from sharp_scout.sports import NCAAF
from sharp_scout.utils.slate import (
    ET,
    college_week_bounds,
    college_week_label,
    filter_plays_college_week,
    filter_plays_nfl_display_slate,
    filter_events_nfl_display_slate,
    group_stage_cards_by_college_week,
    group_stage_cards_by_nfl_week,
    nfl_week_bounds,
    nfl_week_label,
    parse_commence,
    partition_stage_cards_current_historical,
    partition_stage_cards_nfl_current_historical,
)
from sharp_scout.stage_picks import normalize_stage_cards_team_lines
from sharp_scout.utils.teams import ncaaf_display_code

DOCS_DIR = ROOT / "docs"


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


def _team_for_side(p: dict[str, Any]) -> str:
    side = str(p.get("side") or "").lower()
    if side == "home":
        return str(p.get("home_team") or "HOME")
    if side == "away":
        return str(p.get("away_team") or "AWAY")
    return str(p.get("side", "")).upper()


def _side_label(p: dict[str, Any]) -> str:
    if p.get("player_name") or str(p.get("market") or "").startswith("player_"):
        line = p.get("line")
        line_s = f" {line}" if line is not None else ""
        mkt = str(p.get("market") or "").replace("player_", "").replace("_", " ")
        return f"{p.get('player_name')} {str(p.get('side', '')).upper()}{line_s} ({mkt}) {_price(p.get('price'))}"
    line = p.get("line")
    line_s = ""
    if line is not None:
        line_s = f" {float(line):+g}" if float(line) != 0 else " 0"
    m = {"spreads": "spread", "totals": "total", "h2h": "ML"}.get(p.get("market"), p.get("market"))
    team = _team_for_side(p)
    return f"{team}{line_s} ({m}) {_price(p.get('price'))}"


def _status_badge(status: str) -> str:
    st = status or "pending"
    cls = {"win": "win", "loss": "loss", "push": "pending", "pending": "pending", "void": "pending"}.get(st, "pending")
    label = {"win": "WIN", "loss": "LOSS", "push": "PUSH", "pending": "PENDING", "void": "VOID"}.get(st, st.upper())
    return f'<span class="card-result {cls}">{label}</span>'


def _pick_signals(path_names: tuple[str, ...]) -> dict[str, Any]:
    """Prefer the signals file with the fullest current slate (avoids stale empty artifacts)."""
    best: dict[str, Any] = {}
    best_n = -1
    for name in path_names:
        for path in (ARTIFACTS_DIR / name, DOCS_DIR / name):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            n = int(data.get("n_games") or len(data.get("games") or []))
            if n > best_n:
                best, best_n = data, n
    return best


def _pick_nfl_signals() -> dict[str, Any]:
    return _pick_signals(("latest_signals.json",))


def _pick_ncaaf_signals() -> dict[str, Any]:
    return _pick_signals((NCAAF.artifact_name, "latest_ncaaf_signals.json"))


def _format_timestamp_et(dt: datetime) -> str:
    return dt.astimezone(ET).strftime("%a %b %-d, %-I:%M %p ET")


def _resolve_board_updated_at(
    *,
    nfl_signals: dict[str, Any],
    ncaaf_signals: dict[str, Any],
    nfl_ledger: dict[str, Any],
    ncaaf_ledger: dict[str, Any],
) -> str:
    """Latest pipeline / ledger / play timestamp for the board header."""
    candidates: list[datetime] = []
    for src in (nfl_signals, ncaaf_signals, nfl_ledger, ncaaf_ledger):
        ts = parse_commence(src.get("generated_at") or src.get("updated_at"))
        if ts is not None:
            candidates.append(ts)
    for ledger in (nfl_ledger, ncaaf_ledger):
        for play in ledger.get("plays") or []:
            for key in ("created_at", "settled_at", "clv_at"):
                ts = parse_commence(play.get(key))
                if ts is not None:
                    candidates.append(ts)
    latest = max(candidates) if candidates else datetime.now(timezone.utc)
    return _format_timestamp_et(latest)


def _render_analytics_head(measurement_id: str) -> str:
    mid = (measurement_id or "").strip()
    if not mid:
        return ""
    safe = _esc(mid)
    return f"""<script async src="https://www.googletagmanager.com/gtag/js?id={safe}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{safe}', {{ anonymize_ip: true }});
</script>"""


def _ssq_logo_svg(*, embedded: bool = True) -> str:
    """SSQ monogram: stacked S's with Q centered over the overlap, on abstract bills."""
    cls = ' class="ssq-logo"' if embedded else ""
    return f"""<svg{cls} viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Sharp Scout Quant">
  <rect x="1" y="1" width="78" height="78" rx="14" fill="#1e3a5f" stroke="#111111" stroke-width="2"/>
  <g opacity="0.5">
    <rect x="10" y="21" width="52" height="27" rx="3" fill="#2a5278" stroke="#9eb4cc" stroke-width="1.1" transform="rotate(-12 36 34)"/>
    <ellipse cx="23" cy="34" rx="5.5" ry="7.5" fill="none" stroke="#9eb4cc" stroke-width="0.9" transform="rotate(-12 23 34)"/>
    <path d="M13 25.5h5v4.5" fill="none" stroke="#9eb4cc" stroke-width="0.9" stroke-linecap="round" transform="rotate(-12 36 34)"/>
    <path d="M57 42.5h-5v-4.5" fill="none" stroke="#9eb4cc" stroke-width="0.9" stroke-linecap="round" transform="rotate(-12 36 34)"/>
    <rect x="18" y="35" width="52" height="27" rx="3" fill="#234868" stroke="#c5d4e3" stroke-width="1.1" transform="rotate(10 44 48)"/>
    <ellipse cx="57" cy="48" rx="5.5" ry="7.5" fill="none" stroke="#c5d4e3" stroke-width="0.9" transform="rotate(10 57 48)"/>
    <path d="M21 39h5v4.5" fill="none" stroke="#c5d4e3" stroke-width="0.9" stroke-linecap="round" transform="rotate(10 44 48)"/>
    <path d="M65 56h-5v-4.5" fill="none" stroke="#c5d4e3" stroke-width="0.9" stroke-linecap="round" transform="rotate(10 44 48)"/>
  </g>
  <g opacity="0.24" stroke="#dbe4ed" fill="none" stroke-width="1.7" stroke-linecap="round">
    <path d="M40 17 C32.5 17 28 21 28 25.5 C28 30 32.5 32 40 32 C47.5 32 52 34 52 38.5 C52 43 47.5 47 40 47"/>
    <line x1="40" y1="13" x2="40" y2="51"/>
  </g>
  <text x="40" y="29" text-anchor="middle" font-family="Inconsolata, monospace" font-size="28" font-weight="700" fill="#ffffff" opacity="0.92">S</text>
  <text x="40" y="51" text-anchor="middle" font-family="Inconsolata, monospace" font-size="28" font-weight="700" fill="#ffffff" opacity="0.92">S</text>
  <text x="40" y="40" text-anchor="middle" font-family="Inconsolata, monospace" font-size="30" font-weight="700" fill="#ffffff">Q</text>
</svg>"""


def build_site(
    *,
    docs_dir: Path | None = None,
    signals_path: Path | None = None,
) -> Path:
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    ledger = load_ledger()
    record = compute_record(ledger)
    if signals_path is not None:
        signals: dict[str, Any] = (
            json.loads(signals_path.read_text()) if signals_path.exists() else {}
        )
    else:
        signals = _pick_nfl_signals()

    # Copy data for client-side refresh / debugging
    (out / "ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    (out / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    if signals:
        existing_n = 0
        out_signals = out / "latest_signals.json"
        if out_signals.exists():
            try:
                existing = json.loads(out_signals.read_text())
                existing_n = int(existing.get("n_games") or len(existing.get("games") or []))
            except json.JSONDecodeError:
                existing_n = 0
        new_n = int(signals.get("n_games") or len(signals.get("games") or []))
        if new_n >= existing_n:
            out_signals.write_text(json.dumps(signals, indent=2, default=str) + "\n")

    ncaaf_signals: dict[str, Any] = _pick_ncaaf_signals()
    ncaaf_ledger = load_ledger(path=DATA_DIR / NCAAF.ledger_name)
    ncaaf_record = compute_record(ncaaf_ledger)
    (out / "ncaaf_ledger.json").write_text(json.dumps(ncaaf_ledger, indent=2) + "\n")
    (out / "ncaaf_record.json").write_text(json.dumps(ncaaf_record, indent=2) + "\n")
    if ncaaf_signals:
        (out / "latest_ncaaf_signals.json").write_text(
            json.dumps(ncaaf_signals, indent=2, default=str) + "\n"
        )
        (out / "ncaaf_plays.json").write_text(
            json.dumps(ncaaf_signals.get("plays") or [], indent=2, default=str) + "\n"
        )
        (out / "ncaaf_stages.json").write_text(
            json.dumps(ncaaf_signals.get("stage_picks") or [], indent=2, default=str) + "\n"
        )
        (out / "ncaaf_ratings.json").write_text(
            json.dumps(ncaaf_signals.get("ratings") or [], indent=2, default=str) + "\n"
        )

    pending = [p for p in ledger["plays"] if (p.get("status") or "pending") == "pending"]
    settled = [p for p in ledger["plays"] if (p.get("status") or "pending") != "pending"]
    settled_sorted = sorted(settled, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    pending_deduped = collapse_best_signals(pending)
    pending_sorted = sorted(
        pending_deduped,
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    nfl_games_all = signals.get("games") or []
    nfl_week_plays = filter_plays_nfl_display_slate(
        pending, events=nfl_games_all or [{"commence_time": p.get("kickoff")} for p in pending]
    )
    nfl_week_plays_sorted = sorted(
        collapse_best_signals(nfl_week_plays),
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    plays_html = _render_play_cards(nfl_week_plays_sorted, live_fallback=[])
    nfl_clv_banner_html = _render_clv_banner(record.get("clv"))
    nfl_ledger_rows = _render_ledger_rows(settled_sorted + pending_sorted)
    nfl_win_pct = f"{record['win_pct'] * 100:.1f}%" if record["win_pct"] is not None else "—"
    nfl_pnl = record["pnl_units"]
    nfl_pnl_cls = "pos" if nfl_pnl >= 0 else "neg"
    nfl_pnl_s = f"+{nfl_pnl}" if nfl_pnl >= 0 else str(nfl_pnl)

    nfl_signal_count = len(nfl_week_plays_sorted)
    demo_note = "DEMO data" if signals.get("demo") else "Live pipeline"
    ratings_rows = _render_ratings(signals.get("ratings") or [])
    nfl_stage_cards = normalize_stage_cards_team_lines(
        _merge_stage_cards(
            ledger.get("stage_cards") or [],
            signals.get("stage_picks") or [],
            games=nfl_games_all,
            plays=ledger.get("plays") or [],
        )
    )
    nfl_current_stage_cards, nfl_historical_weeks = partition_stage_cards_nfl_current_historical(
        nfl_stage_cards,
        events=nfl_games_all,
    )
    nfl_stage_weeks_html = _render_stage_weeks_html(nfl_current_stage_cards, sport="nfl")
    nfl_historical_html = _render_historical_weeks(
        nfl_historical_weeks,
        sport="nfl",
        ledger_plays=ledger.get("plays") or [],
    )
    nfl_leans_html = _render_hybrid_leans_section(
        nfl_current_stage_cards,
        sport="nfl",
        ledger_plays=filter_plays_nfl_display_slate(
            ledger.get("plays") or [],
            events=nfl_games_all,
        ),
    )
    nfl_games_display = filter_events_nfl_display_slate(nfl_games_all)
    nfl_event_ids = {str(g.get("event_id")) for g in nfl_games_display}
    stage_cards = [
        c for c in nfl_current_stage_cards if str(c.get("event_id")) in nfl_event_ids
    ] or nfl_current_stage_cards
    nfl_signals_list = [
        s for s in (signals.get("signals") or []) if str(s.get("event_id")) in nfl_event_ids
    ]
    nfl_split_boards = [
        b for b in (signals.get("split_boards") or []) if str(b.get("event_id")) in nfl_event_ids
    ]
    disagreement_rows = _render_disagreement_rows(record.get("disagreements"))
    stage_rows = _render_stage_rows(stage_cards, sport="nfl")
    stage_record_rows = _render_stage_record_rows(record.get("stage_records") or {})
    stage_summary = signals.get("stage_summary") or {}
    fade_n = stage_summary.get("fade_public_games", "—")
    rlm_n = stage_summary.get("rlm_games", "—")
    stage_highlights_html = _render_stage_highlight_lists(stage_summary)

    games_html = _render_games_pipeline(
        nfl_games_display,
        nfl_split_boards,
        stage_cards,
        nfl_signals_list,
        signals.get("ratings") or [],
    )

    ncaaf_pending = [p for p in ncaaf_ledger["plays"] if (p.get("status") or "pending") == "pending"]
    ncaaf_week_plays = filter_plays_college_week(ncaaf_pending)
    ncaaf_week_plays_sorted = sorted(
        collapse_best_signals(ncaaf_week_plays),
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    ncaaf_plays_html = _render_play_cards(ncaaf_week_plays_sorted, live_fallback=[])
    ncaaf_stage_cards = normalize_stage_cards_team_lines(
        _merge_stage_cards(
            ncaaf_ledger.get("stage_cards") or [],
            ncaaf_signals.get("stage_picks") or [],
            games=ncaaf_signals.get("games") or [],
            plays=ncaaf_ledger.get("plays") or [],
        )
    )
    ncaaf_current_stage_cards, ncaaf_historical_weeks = partition_stage_cards_current_historical(
        ncaaf_stage_cards
    )
    ncaaf_stage_weeks_html = _render_stage_weeks_html(ncaaf_current_stage_cards)
    ncaaf_historical_html = _render_historical_weeks(
        ncaaf_historical_weeks,
        sport="ncaaf",
        ledger_plays=ncaaf_ledger.get("plays") or [],
    )
    ncaaf_stage_record_rows = _render_stage_record_rows(ncaaf_record.get("stage_records") or {})
    ncaaf_stage_summary = ncaaf_signals.get("stage_summary") or {}
    ncaaf_fade_n = ncaaf_stage_summary.get("fade_public_games", "—")
    ncaaf_rlm_n = ncaaf_stage_summary.get("rlm_games", "—")
    ncaaf_leans_html = _render_hybrid_leans_section(
        ncaaf_current_stage_cards,
        sport="ncaaf",
        ledger_plays=filter_plays_college_week(ncaaf_ledger.get("plays") or []),
    )
    ncaaf_win_pct = (
        f"{ncaaf_record['win_pct'] * 100:.1f}%" if ncaaf_record["win_pct"] is not None else "—"
    )
    ncaaf_pnl = ncaaf_record["pnl_units"]
    ncaaf_pnl_cls = "pos" if ncaaf_pnl >= 0 else "neg"
    ncaaf_pnl_s = f"+{ncaaf_pnl}" if ncaaf_pnl >= 0 else str(ncaaf_pnl)
    ncaaf_settled = [p for p in ncaaf_ledger["plays"] if (p.get("status") or "pending") != "pending"]
    ncaaf_settled_sorted = sorted(
        ncaaf_settled, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True
    )
    ncaaf_pending_sorted = sorted(
        collapse_best_signals(ncaaf_pending),
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    ncaaf_clv_banner_html = _render_clv_banner(ncaaf_record.get("clv"))
    ncaaf_ledger_rows = _render_ledger_rows(ncaaf_settled_sorted + ncaaf_pending_sorted)

    nfl_top_stats_html = "".join(
        [
            _stat_card(str(record["record"]), "NFL Record", "Validated Sharp Plays on the NFL ledger."),
            _stat_card(nfl_win_pct, "Win %", "Win rate on validated NFL Sharp Plays."),
            _stat_card(f"{nfl_pnl_s}u", "Profit", "Net units on NFL Sharp Plays.", val_cls=nfl_pnl_cls),
            _stat_card(demo_note, "Mode", "Live pipeline or demo mock data."),
        ]
    )
    ncaaf_top_stats_html = "".join(
        [
            _stat_card(ncaaf_record["record"], "CFB Record", BOARD_STAT_TIPS["cfb_record"]),
            _stat_card(ncaaf_win_pct, "Win %", "Win rate on validated CFB Sharp Plays."),
            _stat_card(f"{ncaaf_pnl_s}u", "Profit", BOARD_STAT_TIPS["cfb_profit"], val_cls=ncaaf_pnl_cls),
            _stat_card("DEMO data" if ncaaf_signals.get("demo") else "Live pipeline", "Mode", "Live odds/splits or demo mock."),
        ]
    )
    stage_alarm_stats_html = "".join(
        [
            _stat_card(str(fade_n), "Sharp ≠ Public games", BOARD_STAT_TIPS["sharp_vs_public"]),
            _stat_card(str(rlm_n), "RLM games", BOARD_STAT_TIPS["rlm_games"]),
        ]
    )
    ncaaf_alarm_stats_html = "".join(
        [
            _stat_card(str(ncaaf_fade_n), "Sharp vs Public", BOARD_STAT_TIPS["sharp_vs_public"]),
            _stat_card(str(ncaaf_rlm_n), "RLM Games", BOARD_STAT_TIPS["rlm_games"]),
        ]
    )
    stage_records_thead = (
        "<thead><tr><th>Stage</th><th>Record</th><th>Win %</th>"
        + _stage_th("Ungraded", BOARD_STAT_TIPS["stage_ungraded"])
        + "</tr></thead>"
    )

    board_updated = _resolve_board_updated_at(
        nfl_signals=signals,
        ncaaf_signals=ncaaf_signals,
        nfl_ledger=ledger,
        ncaaf_ledger=ncaaf_ledger,
    )

    html = SITE_TEMPLATE.format(
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        ssq_logo=_ssq_logo_svg(embedded=True),
        board_updated=board_updated,
        nfl_record=record["record"],
        nfl_win_pct=nfl_win_pct,
        nfl_pnl=nfl_pnl_s,
        nfl_pnl_cls=nfl_pnl_cls,
        nfl_pending=record["pending"],
        nfl_n_plays=record["n_plays"],
        nfl_signal_count=nfl_signal_count,
        demo_note=demo_note,
        plays_html=plays_html,
        nfl_clv_banner_html=nfl_clv_banner_html,
        nfl_ledger_rows=nfl_ledger_rows,
        nfl_stage_weeks_html=nfl_stage_weeks_html,
        nfl_leans_html=nfl_leans_html,
        nfl_historical_html=nfl_historical_html,
        ratings_rows=ratings_rows,
        stage_rows=stage_rows,
        stage_table_head=_render_stage_table_head(),
        stage_record_rows=stage_record_rows,
        disagreement_rows=disagreement_rows,
        games_html=games_html,
        fade_n=fade_n,
        rlm_n=rlm_n,
        stage_highlights_html=stage_highlights_html,
        ncaaf_record=ncaaf_record["record"],
        ncaaf_win_pct=ncaaf_win_pct,
        ncaaf_pnl=ncaaf_pnl_s,
        ncaaf_pnl_cls=ncaaf_pnl_cls,
        ncaaf_pending=ncaaf_record["pending"],
        ncaaf_n_plays=ncaaf_record["n_plays"],
        ncaaf_plays_html=ncaaf_plays_html,
        ncaaf_week_play_count=len(ncaaf_week_plays_sorted),
        ncaaf_stage_weeks_html=ncaaf_stage_weeks_html,
        ncaaf_stage_record_rows=ncaaf_stage_record_rows,
        ncaaf_fade_n=ncaaf_stage_summary.get("fade_public_games", "—"),
        ncaaf_rlm_n=ncaaf_stage_summary.get("rlm_games", "—"),
        ncaaf_historical_html=ncaaf_historical_html,
        ncaaf_leans_html=ncaaf_leans_html,
        ncaaf_demo_note="DEMO data" if ncaaf_signals.get("demo") else "Live pipeline",
        ncaaf_clv_banner_html=ncaaf_clv_banner_html,
        ncaaf_ledger_rows=ncaaf_ledger_rows,
        nfl_top_stats_html=nfl_top_stats_html,
        ncaaf_top_stats_html=ncaaf_top_stats_html,
        stage_alarm_stats_html=stage_alarm_stats_html,
        ncaaf_alarm_stats_html=ncaaf_alarm_stats_html,
        stage_records_thead=stage_records_thead,
        stage_record_section_note=_esc(STAGE_RECORD_SECTION_NOTE),
        guide_html=_render_guide_html(),
    )
    (out / "index.html").write_text(html)

    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "ssq-logo.svg").write_text(_ssq_logo_svg(embedded=False) + "\n")

    # CNAME placeholder not needed; add .nojekyll for GH Pages
    (out / ".nojekyll").write_text("")
    return out


def _render_guide_html() -> str:
    """Plain-language site guide — process overview, not model IP."""
    return """
<div class="guide-block">
  <h2>How to use this site</h2>
  <p>Sharp Scout Quant is a research board for NFL and college football. It compares our model view of each game to the market, then surfaces where the number looks soft — and where ticket/money splits agree or disagree.</p>
  <div class="guide-callout"><p><b>Signals only.</b> Nothing here places a bet for you. Use it as a checklist before you decide.</p></div>
</div>

<div class="guide-block">
  <h2>What the system is doing</h2>
  <p>At a high level, each run:</p>
  <ul>
    <li><b>Rates teams</b> from recent play-by-play (efficiency / EPA-style power), so matchups have a model spread and total.</li>
    <li><b>Simulates games</b> (Monte Carlo) to turn those ratings into cover and win probabilities at the posted lines.</li>
    <li><b>Compares to the market</b> — sharp books and the wider board — to see where the price offers value vs our fair number.</li>
    <li><b>Checks betting splits</b> (tickets vs money, line movement) as a second opinion: is the public piled on one side while dollars lean the other?</li>
    <li><b>Filters</b> candidates so only plays that clear our bar show up as validated <b>Sharp Plays</b>.</li>
  </ul>
  <p>We do not publish the exact edges, weights, or filter thresholds. Treat the board as the output of that process, not a black-box tip sheet.</p>
</div>

<div class="guide-block">
  <h2>How to read the tabs</h2>
  <h3>NFL / CFB (main boards)</h3>
  <ul>
    <li><b>This Week's Plays</b> — validated Sharp Plays only. These are the bets we would actually track on the ledger.</li>
    <li><b>Pregame Stage Winners</b> — every game, three markets (spread, moneyline, total). Each column is a different lens (model, sharp books, public tickets, money, etc.). The green <b>Quant Pick</b> is the system side for that market.</li>
    <li><b>Quant Pick Leans</b> — all Quant Pick rows for the week. Yellow rows are posted Sharp Plays; the rest are leans / research, not auto-ledger bets.</li>
    <li><b>Ledger</b> — full history of posted plays, results, CLV, and units.</li>
  </ul>
  <h3>Games</h3>
  <p>Deep dive per matchup: model numbers, splits boards, and stage picks in one place. Use it when you want context on a single game.</p>
  <h3>Stages</h3>
  <p>Season-long scorecards for each lens, plus disagreement notes when the model and market diverge. Helpful for process review — not the first place to look for today's bet.</p>
  <h3>Ratings</h3>
  <p>Current power ratings (offense / defense EPA). Good for “who is actually strong right now?” before you dig into a line.</p>
  <h3>NFL Historical / CFB Historical</h3>
  <p>Prior weeks archived after the week rolls (NFL Wed–Tue ET; CFB Mon–Sun ET). Download CSV from any table if you want your own spreadsheet.</p>
</div>

<div class="guide-block">
  <h2>How the board updates through the week</h2>
  <ul>
    <li><b>Opening / early week</b> — first lines and early sims. Expect more movement and fewer locked Sharp Plays.</li>
    <li><b>Midweek</b> — ratings and odds refresh on the scheduled pipeline. Splits get richer as handle builds. Stage columns can flip as the number moves.</li>
    <li><b>Late week / gameday</b> — sharper closes, better money/ticket reads, more stable Quant Picks. CLV is measured vs the closing line after the fact.</li>
    <li><b>After games</b> — settle grades the ledger and stage records. Historical tabs pick up completed weeks.</li>
  </ul>
  <p>The navy bar under the header shows when picks, prices, and lines were last refreshed (Eastern Time). It updates whenever the pipeline rebuilds the board. Hard-refresh the page if something looks stale.</p>
</div>

<div class="guide-block">
  <h2>When to place a bet</h2>
  <ul>
    <li>Prefer sides that appear as <b>Sharp Plays</b> (or yellow Quant Pick rows), not every stage column agreement.</li>
    <li>If Model, Sharp, Money, and Quant Pick align — and Public is on the other side — that is usually a stronger process story than a lone model lean.</li>
    <li>Re-check closer to kickoff: a play that looked good Tuesday can disappear (or flip) after steam or a number move.</li>
    <li>Shop the price. The board names a market side; your edge depends on getting a number at least as good as what we evaluated.</li>
    <li>Skip or downsize when the line has already moved through your number, or when you only see a lean with no validated Sharp Play.</li>
  </ul>
  <div class="guide-callout"><p>Best habit: note the play early, confirm on the last refresh before kickoff, then bet only if the number and story still hold.</p></div>
</div>

<div class="guide-block">
  <h2>Quick glossary</h2>
  <ul>
    <li><b>Sharp Play</b> — cleared filters and posted to the ledger.</li>
    <li><b>Quant Pick / Hybrid</b> — system side for that game/market after combining lenses.</li>
    <li><b>CLV (Closing Line Value)</b> — did we beat the closing number? Positive CLV is a process win even before the game grades.</li>
    <li><b>RLM</b> — reverse line movement: the line moves against the ticket majority (often a sharp-money tell).</li>
    <li><b>Units</b> — stake size on the ledger; profit is tracked in units, not dollars.</li>
  </ul>
</div>
"""


def _render_play_cards(pending: list[dict], live_fallback: list[dict]) -> str:
    source = pending if pending else live_fallback
    if not source:
        return '<div class="empty">No open plays. Run the pipeline to generate signals.</div>'

    cards = []
    for p in source:
        kick_et = format_kickoff_et(p.get("kickoff") or p.get("commence_time"))
        if "filter_passed" in p and not p.get("status"):
            tier = p.get("tier") or "lean"
            status_html = '<span class="card-result pending">OPEN</span>'
            title = _side_label(p)
            sub = f"{kick_et} · {p.get('away_team')} @ {p.get('home_team')} · {p.get('book')}"
            edge = p.get("edge")
            units = {"play": 1.5, "lean": 1.0}.get(tier, 0.5)
            rationale = format_play_rationale(p)
            meta_edge = f"{(edge or 0) * 100:.1f}%" if edge is not None else "—"
        else:
            tier = p.get("tier") or "lean"
            status_html = _status_badge(p.get("status") or "pending")
            title = _side_label(p)
            sub = f"{kick_et} · {p.get('away_team')} @ {p.get('home_team')} · {p.get('book')}"
            if p.get("window"):
                w = p.get("window")
                sub += f" · {'force-all' if w == -1 else f'T-{w}h'}"
            if p.get("play_type") == "prop" or p.get("player_name"):
                sub = f"PROP · {sub}"
            if p.get("home_score") is not None and not p.get("player_name"):
                sub += f" · Final {p.get('away_team')} {p.get('away_score')}, {p.get('home_team')} {p.get('home_score')}"
            edge = p.get("edge")
            units = p.get("units") or 1
            rationale = format_play_rationale(p)
            meta_edge = f"{(edge or 0) * 100:.1f}%" if edge is not None else "—"

        card_cls = "sharp-play" if tier == "play" else "sharp-lean" if tier == "lean" else "candidate"
        badge_cls = "badge-play" if tier == "play" else "badge-lean" if tier == "lean" else "badge-cand"
        tier_name = "Sharp Play" if tier == "play" else "Sharp Lean" if tier == "lean" else "Candidate"
        conf = min(99, round(50 + float(edge or 0) * 500))
        color = "#15803d" if tier == "play" else "#ca8a04" if tier == "lean" else "#2563eb"
        pnl = p.get("pnl_units")
        pnl_html = ""
        if pnl is not None:
            cls = "pos" if pnl >= 0 else "neg"
            pnl_html = f'<div class="meta-item"><span class="meta-label">PnL </span><span class="meta-val {cls}">{"+" if pnl >= 0 else ""}{pnl}u</span></div>'

        cards.append(
            f"""
      <div class="play-card {card_cls}">
        <div class="card-top">
          <div class="card-left">
            <span class="tier-badge {badge_cls}">{tier_name}</span>
            <div class="play-title">{_esc(title)}</div>
            <div class="play-subtitle">{_esc(sub)}</div>
          </div>
          <div class="units-badge">{units}u</div>
        </div>
        {status_html}
        <div class="play-meta">
          <div class="meta-item"><span class="meta-label">EV </span><span class="meta-val pos">{meta_edge}</span></div>
          <div class="meta-item"><span class="meta-label">P_true </span><span class="meta-val">{(float(p.get('p_true') or 0) * 100):.1f}%</span></div>
          {pnl_html}
        </div>
        <div class="conf-bar">
          <div class="conf-track"><div class="conf-fill" style="width:{conf}%;background:{color};"></div></div>
        </div>
        <div class="rationale-toggle" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
          <span class="arrow">▶</span><span>Rationale</span>
        </div>
        <div class="rationale-body">{_esc(rationale).replace(chr(10), '<br>')}</div>
      </div>"""
        )
    return "\n".join(cards)


def _clv_cell(p: dict) -> str:
    """Points of closing-line value with a color cue (positive = beat the close)."""
    pts = p.get("clv_points")
    prob = p.get("clv_prob")
    if pts is None and prob is None:
        return "<td class='pending'>—</td>"
    if pts is not None:
        cls = "pos" if pts > 0 else "neg" if pts < 0 else "pending"
        main = f"{pts:+g}"
    else:
        cls = "pos" if (prob or 0) > 0 else "neg" if (prob or 0) < 0 else "pending"
        main = f"{prob * 100:+.1f}%"
    sub = f" ({prob * 100:+.1f}%)" if pts is not None and prob is not None else ""
    return f"<td class='{cls}'>{main}{sub}</td>"


def _render_ledger_rows(plays: list[dict]) -> str:
    if not plays:
        return "<tr><td colspan='8'>No plays in ledger yet.</td></tr>"
    rows = []
    for p in sorted(
        plays,
        key=lambda x: kickoff_sort_key(x.get("kickoff") or x.get("commence_time") or x.get("created_at")),
        reverse=True,
    ):
        st = p.get("status") or "pending"
        pnl = p.get("pnl_units")
        if pnl is None:
            pnl_s = "—"
            pnl_cls = ""
        else:
            pnl_cls = "pos" if pnl >= 0 else "neg"
            pnl_s = f"+{pnl}" if pnl >= 0 else str(pnl)
        score = "—"
        if p.get("home_score") is not None:
            score = f"{p.get('away_team')} {p.get('away_score')} – {p.get('home_team')} {p.get('home_score')}"
        kick = format_kickoff_et(p.get("kickoff") or p.get("commence_time") or p.get("created_at"))
        rows.append(
            f"<tr>"
            f"<td>{_esc(kick)}</td>"
            f"<td>{_esc(p.get('away_team'))} @ {_esc(p.get('home_team'))}</td>"
            f"<td>{_esc(_side_label(p))}</td>"
            f"<td>{p.get('units')}u</td>"
            f"<td class='{st if st in ('win','loss') else 'pending'}'>{st.upper()}</td>"
            f"<td>{_esc(score)}</td>"
            f"{_clv_cell(p)}"
            f"<td class='{pnl_cls}'>{pnl_s}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _render_clv_banner(clv: dict[str, Any] | None) -> str:
    """Summary of Closing Line Value — the earliest proof the process beats the market."""
    clv = clv or {}
    n = clv.get("n_plays_with_clv") or 0
    if not n:
        return (
            '<p class="phase-note" style="padding:6px 0">Closing Line Value appears here once '
            "plays are graded against their closing line (captured at the T-1h pregame run).</p>"
        )
    avg_pts = clv.get("avg_clv_points")
    beat_pct = clv.get("beat_close_pct")
    rec = clv.get("beat_close_record") or "—"
    pts_s = f"{avg_pts:+g}" if avg_pts is not None else "—"
    beat_s = f"{beat_pct * 100:.0f}%" if beat_pct is not None else "—"
    cls = "pos" if (avg_pts or 0) > 0 else "neg" if (avg_pts or 0) < 0 else ""
    return (
        '<div class="summary-grid" style="margin-top:6px">'
        + _stat_card(pts_s, "Avg CLV (pts)", BOARD_STAT_TIPS["clv_avg_pts"], val_cls=cls)
        + _stat_card(beat_s, "Beat Close %", BOARD_STAT_TIPS["clv_beat_pct"])
        + _stat_card(str(rec), "Beat-Close W-L", BOARD_STAT_TIPS["clv_beat_record"])
        + _stat_card(str(n), "Plays w/ CLV", BOARD_STAT_TIPS["clv_n_plays"])
        + "</div>"
    )


def _render_week_rows(by_week: dict) -> str:
    if not by_week:
        return "<tr><td colspan='4'>No weekly history yet.</td></tr>"
    rows = []
    for week, b in sorted(by_week.items(), reverse=True):
        pnl = b.get("pnl") or 0
        cls = "pos" if pnl >= 0 else "neg"
        rows.append(
            f"<tr><td>{_esc(week)}</td>"
            f"<td>{b.get('wins', 0)}-{b.get('losses', 0)}</td>"
            f"<td>{b.get('pending', 0)}</td>"
            f"<td class='{cls}'>{'+' if pnl >= 0 else ''}{pnl:.2f}u</td></tr>"
        )
    return "\n".join(rows)


def _render_ratings(ratings: list[dict]) -> str:
    if not ratings:
        return "<tr><td colspan='4'>Run pipeline to populate ratings.</td></tr>"
    return "\n".join(
        f"<tr><td><b>{_esc(r['team'])}</b></td>"
        f"<td class='{'pos' if r['power'] >= 0 else 'neg'}'>{r['power']:.3f}</td>"
        f"<td>{r['off_epa']:.3f}</td>"
        f"<td>{r['def_epa']:.3f}</td></tr>"
        for r in ratings
    )


def _rating_row(team: str, ratings: list[dict]) -> str:
    r = next((x for x in ratings if x.get("team") == team), None)
    if not r:
        return "—"
    return f"power {r['power']:.3f} · off {r['off_epa']:.3f} · def {r['def_epa']:.3f}"


def _render_splits_table(board: dict[str, Any]) -> str:
    markets = board.get("markets") or {}
    if not markets:
        reason = board.get("reason") or "No split data"
        return f'<p class="phase-note">{_esc(reason)}</p>'

    narrative = describe_splits_board(board)
    parts = [f'<p class="phase-note splits-summary"><b>Sharp money read:</b> {_esc(narrative)}</p>']
    parts.append(
        '<p class="phase-note" style="font-size:11px">'
        "Tickets = % of bets on each side. Money = % of dollars (handle). "
        "Diff = money minus tickets — positive means sharps lean that side.</p>"
    )
    for mkey, mdata in markets.items():
        rows = []
        for side_key, side in (mdata.get("sides") or {}).items():
            t = side.get("tickets_pct")
            m = side.get("money_pct")
            d = side.get("diff_pct")
            t_s = f"{t * 100:.0f}%" if t is not None else "—"
            m_s = f"{m * 100:.0f}%" if m is not None else "—"
            d_s = f"{d * 100:+.0f}%" if d is not None else "—"
            rows.append(
                f"<tr><td>{_esc(side.get('label') or side_key)}</td>"
                f"<td>{t_s}</td><td>{m_s}</td><td class='pos'>{d_s}</td></tr>"
            )
        line = mdata.get("line")
        line_s = f" line {line}" if line is not None else ""
        parts.append(
            f"<div class='phase-sub'>{_esc(mkey)}{line_s}</div>"
            f"<div class='table-wrap'><table><thead><tr>"
            f"<th>Side</th><th>Tickets</th><th>Money</th><th>Diff</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return "".join(parts)


def _render_edge_rows(signals: list[dict]) -> str:
    if not signals:
        return "<tr><td colspan='6'>No EV candidates (phase 3).</td></tr>"
    collapsed = collapse_best_signals(signals)
    rows = []
    for s in collapsed[:12]:
        passed = s.get("filter_passed")
        cls = "pos" if passed else "pending"
        flag = "✓" if passed else "—"
        edge = s.get("edge")
        edge_s = f"{edge * 100:.1f}%" if edge is not None else "—"
        line = s.get("line")
        side_label = _side_label({**s, "price": s.get("price")})
        rationale = format_play_rationale(s).replace("\n", " · ")
        rows.append(
            f"<tr><td>{_esc(_market_label(s.get('market')))}</td>"
            f"<td>{_esc(side_label)}</td>"
            f"<td>{_esc(s.get('book'))}</td>"
            f"<td class='{cls}'>{edge_s}</td>"
            f"<td>{flag}</td>"
            f"<td class='rationale-cell'>{_esc(rationale)}</td></tr>"
        )
    return "\n".join(rows)


def _market_label(market: str | None) -> str:
    return {"spreads": "spread", "totals": "total", "h2h": "ML"}.get(market or "", market or "")


def _render_stage_mini(card: dict | None, home: str, away: str) -> str:
    if not card:
        return "<p class='phase-note'>No stage card.</p>"
    picks = card.get("picks") or {}
    rows = []
    for key in ("model", "sharp", "public", "money", "sharp_edge", "rlm", "hybrid"):
        p = picks.get(key) or {}
        label = STAGE_LABELS.get(key, key)
        if not p.get("available"):
            cell = "—"
            why = p.get("reason") or "Not available"
        else:
            team = p.get("team") or p.get("side") or "—"
            conf = p.get("confidence")
            conf_s = f" ({conf * 100:.0f}%)" if conf is not None else ""
            cell = f"{_esc(team)}{conf_s}"
            why = describe_stage_pick(key, p, home, away)
        rows.append(
            f"<tr><td><b>{_esc(label)}</b></td><td>{cell}</td>"
            f"<td class='stage-why'>{_esc(why)}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Lens</th><th>Pick</th><th>Why</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_games_pipeline(
    games: list[dict],
    split_boards: list[dict],
    stage_cards: list[dict],
    signals: list[dict],
    ratings: list[dict],
) -> str:
    if not games:
        return '<div class="empty">No games in latest pipeline run. Run scripts/run_today_slate.py or the NFL Pipeline workflow.</div>'

    boards = {str(b.get("event_id")): b for b in split_boards}
    stages_by_event: dict[str, list[dict]] = {}
    for c in stage_cards:
        stages_by_event.setdefault(str(c.get("event_id")), []).append(c)
    sig_by_event: dict[str, list[dict]] = {}
    for s in signals:
        sig_by_event.setdefault(str(s.get("event_id")), []).append(s)

    cards = []
    games_sorted = sorted(
        games,
        key=lambda g: kickoff_sort_key(g.get("commence_time")),
    )
    for g in games_sorted:
        eid = str(g.get("event_id"))
        away, home = g.get("away_team"), g.get("home_team")
        board = boards.get(eid) or {}
        event_stages = stages_by_event.get(eid) or []
        stage_sections = []
        for mkt in ("spread", "h2h", "total"):
            stage = next((c for c in event_stages if c.get("market") == mkt), None)
            stage_sections.append(
                f"<div class='phase-sub'>{_esc(_stage_market_label(mkt))}</div>"
                f"{_render_stage_mini(stage, home, away)}"
            )
        stage_html = "".join(stage_sections)
        game_sigs = sig_by_event.get(eid) or []
        kick = format_kickoff_et(g.get("commence_time"))
        p_hw = g.get("p_home_win")
        p_hw_s = f"{p_hw * 100:.1f}%" if p_hw is not None else "—"
        m_spread = g.get("model_spread")
        m_total = g.get("model_total")
        spread_s = f"{float(m_spread):+.2f}" if m_spread is not None else "—"
        total_s = f"{float(m_total):.2f}" if m_total is not None else "—"

        cards.append(
            f"""
      <div class="game-card">
        <div class="game-head">
          <div class="game-title">{_esc(away)} @ {_esc(home)}</div>
          <div class="game-kick">{_esc(kick)}</div>
        </div>
        <div class="phase-block">
          <div class="phase-label">Phase 1 · EPA ratings → model</div>
          <p class="phase-note"><b>{_esc(away)}</b>: {_esc(_rating_row(away, ratings))}</p>
          <p class="phase-note"><b>{_esc(home)}</b>: {_esc(_rating_row(home, ratings))}</p>
          <p class="phase-note">Model spread (home): <b>{spread_s}</b> ·
            total <b>{total_s}</b> · P(home win) <b>{p_hw_s}</b></p>
          <p class="phase-note" style="font-size:11px">Negative model spread = home favored. Power ratings use 3 decimals.</p>
        </div>
        <div class="phase-block">
          <div class="phase-label">Phase 3 · Market EV (best book per side)</div>
          <div class="table-wrap"><table>
            <thead><tr><th>Mkt</th><th>Pick</th><th>Book</th><th>EV</th><th>Pass</th><th>Rationale</th></tr></thead>
            <tbody>{_render_edge_rows(game_sigs)}</tbody>
          </table></div>
        </div>
        <div class="phase-block">
          <div class="phase-label">Phase 4 · Money vs tickets (Action Network)</div>
          {_render_splits_table(board)}
        </div>
        <div class="phase-block">
          <div class="phase-label">Stage picks (each lens)</div>
          {stage_html}
        </div>
      </div>"""
        )
    return "\n".join(cards)


def _render_stage_highlight_lists(stage_summary: dict[str, Any]) -> str:
    fade = stage_summary.get("fade_public_matchups") or []
    rlm = stage_summary.get("rlm_matchups") or []
    parts: list[str] = []
    if fade:
        lines = [
            f"{x.get('away_team')} @ {x.get('home_team')}: "
            f"sharp books like {x.get('sharp_team')} · public tickets on {x.get('public_team')}"
            for x in fade
        ]
        parts.append(
            "<div class='phase-note'><b>Sharp vs public games:</b><br>"
            + "<br>".join(_esc(line) for line in lines)
            + "</div>"
        )
    else:
        parts.append(
            "<div class='phase-note'>No games on this slate where sharp books disagree with public ticket %.</div>"
        )
    if rlm:
        lines = [
            f"{x.get('away_team')} @ {x.get('home_team')}: "
            f"RLM toward {x.get('rlm_team')} — {_esc(x.get('reason') or '')}"
            for x in rlm
        ]
        parts.append(
            "<div class='phase-note' style='margin-top:10px'><b>Reverse line movement games:</b><br>"
            + "<br>".join(lines)
            + "</div>"
        )
    else:
        parts.append(
            "<div class='phase-note' style='margin-top:10px'>"
            "No RLM signals on this slate (needs an opening line vs current — stored on first pipeline run).</div>"
        )
    return "".join(parts)


def _stage_market_label(market: str | None) -> str:
    return {"spread": "Spread", "h2h": "ML", "total": "Total"}.get(market or "", market or "—")


_STAGE_MARKET_ORDER = {"spread": 0, "h2h": 1, "total": 2}

_TH_TIP_EYE = (
    '<svg class="th-tip-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" aria-hidden="true">'
    '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
    '<circle cx="12" cy="12" r="3"/></svg>'
)


def _stage_th(label: str, tip: str | None = None) -> str:
    if not tip:
        return f"<th>{_esc(label)}</th>"
    return (
        f'<th class="stage-th">'
        f"{_esc(label)}"
        f'<span class="th-tip" data-tip="{_esc(tip)}" tabindex="0" role="button" '
        f'aria-label="{_esc(label)}: {_esc(tip)}">{_TH_TIP_EYE}</span>'
        f"</th>"
    )


def _stat_tip_icon(tip: str) -> str:
    return (
        f'<span class="th-tip stat-tip" data-tip="{_esc(tip)}" tabindex="0" role="button" '
        f'aria-label="{_esc(tip)}">{_TH_TIP_EYE}</span>'
    )


def _stat_card(val: str, label: str, tip: str | None = None, *, val_cls: str = "") -> str:
    cls = f" stat-val {val_cls}".strip()
    tip_html = _stat_tip_icon(tip) if tip else ""
    return (
        f'<div class="stat-card">'
        f'<div class="stat-val{(" " + val_cls) if val_cls else ""}">{val}</div>'
        f'<div class="stat-label">{_esc(label)}{tip_html}</div>'
        f"</div>"
    )


def _render_stage_table_head() -> str:
    # Hybrid immediately after Mkt so the system pick is visible without horizontal scroll.
    cols: list[tuple[str, str | None]] = [
        ("Kickoff", None),
        ("Game", None),
        ("Mkt", STAGE_COLUMN_TIPS.get("Mkt")),
        ("Quant Pick", STAGE_COLUMN_TIPS.get("Quant Pick")),
        ("Model", STAGE_COLUMN_TIPS.get("Model")),
        ("Sharp", STAGE_COLUMN_TIPS.get("Sharp")),
        ("Public", STAGE_COLUMN_TIPS.get("Public")),
        ("Money", STAGE_COLUMN_TIPS.get("Money")),
        ("Diff", STAGE_COLUMN_TIPS.get("Diff")),
        ("RLM", STAGE_COLUMN_TIPS.get("RLM")),
        ("Notes", None),
    ]
    parts: list[str] = []
    for label, tip in cols:
        if label == "Quant Pick":
            parts.append(
                f'<th class="stage-th hybrid-col">'
                f"{_esc(label)}"
                f'<span class="th-tip" data-tip="{_esc(tip or "")}" tabindex="0" role="button" '
                f'aria-label="{_esc(label)}: {_esc(tip or "")}">{_TH_TIP_EYE}</span>'
                f"</th>"
            )
        else:
            parts.append(_stage_th(label, tip))
    return "<thead><tr>" + "".join(parts) + "</tr></thead>"


def _pick_cell(pick: dict | None, *, sport: str = "nfl") -> str:
    if not pick or not pick.get("available"):
        return "<span class='pending'>—</span>"
    label = pick.get("team") or pick.get("side") or ""
    if not label:
        return "<span class='pending'>—</span>"
    label_s = str(label)
    side = str(pick.get("side") or "").lower()
    if sport == "ncaaf" and side not in ("over", "under") and label_s.upper() not in ("OVER", "UNDER"):
        label_s = ncaaf_display_code(label_s)
    line = pick.get("line")
    market = pick.get("market")
    if line is not None and market == "spread":
        label_s = f"{label_s} {float(line):+,.1f}"
    elif line is not None and market == "total":
        label_s = f"{label_s} {float(line):,.1f}"
    return f"<b>{_esc(label_s)}</b>"


def _stage_card_key(card: dict[str, Any]) -> str:
    return f"{card.get('event_id')}|{card.get('market') or 'spread'}"


def _enrich_stage_kickoffs(
    cards: list[dict[str, Any]],
    *,
    games: list[dict[str, Any]] | None = None,
    plays: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    kick_by_event: dict[str, str] = {}
    for src in games or []:
        eid = str(src.get("event_id") or "")
        if eid and src.get("commence_time"):
            kick_by_event[eid] = str(src["commence_time"])
    for src in plays or []:
        eid = str(src.get("event_id") or "")
        kick = src.get("kickoff") or src.get("commence_time")
        if eid and kick:
            kick_by_event[eid] = str(kick)
    out: list[dict[str, Any]] = []
    for card in cards:
        row = dict(card)
        if not row.get("kickoff"):
            row["kickoff"] = kick_by_event.get(str(row.get("event_id") or ""))
        out.append(row)
    return out


def _is_validated_hybrid(pick: dict[str, Any] | None) -> bool:
    if not pick:
        return False
    reason = (pick.get("reason") or "").lower()
    if "no validated" in reason:
        return False
    return reason.startswith("validated ") or "validated play" in reason


def _normalize_market_key(market: str | None) -> str:
    m = (market or "spread").lower()
    if m in ("totals", "total"):
        return "total"
    if m in ("h2h", "moneyline", "ml"):
        return "h2h"
    if m in ("spreads", "spread"):
        return "spread"
    return m


def _ledger_play_keys(plays: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for play in plays:
        eid = str(play.get("event_id") or "")
        market = _normalize_market_key(play.get("market"))
        side = str(play.get("side") or "").lower()
        if eid and side:
            keys.add((eid, market, side))
    return keys


def _quant_pick_row_key(card: dict[str, Any], hybrid: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(card.get("event_id") or ""),
        _normalize_market_key(str(card.get("market") or hybrid.get("market") or "")),
        str(hybrid.get("side") or "").lower(),
    )


def _hybrid_pick_rank(pick: dict[str, Any] | None) -> int:
    if not pick or not pick.get("available"):
        return 0
    if _is_validated_hybrid(pick):
        return 3
    reason = (pick.get("reason") or "").lower()
    if "model aligned" in reason:
        return 2
    return 1


def _merge_stage_picks(
    old_picks: dict[str, Any],
    new_picks: dict[str, Any],
) -> dict[str, Any]:
    """Merge per-stage picks; keep validated hybrid over soft model+money lean."""
    out = dict(old_picks)
    for stage, new_pick in new_picks.items():
        old_pick = out.get(stage) or {}
        if stage == "hybrid":
            old_rank = _hybrid_pick_rank(old_pick)
            new_rank = _hybrid_pick_rank(new_pick)
            if old_rank > new_rank:
                out[stage] = old_pick
            elif new_rank > old_rank:
                out[stage] = new_pick
            elif old_rank == new_rank == 3 and _is_validated_hybrid(old_pick):
                out[stage] = old_pick
            elif new_pick.get("available"):
                out[stage] = new_pick
            else:
                out[stage] = old_pick or new_pick
        elif new_pick.get("available") or not old_pick.get("available"):
            out[stage] = new_pick
    return out


def _merge_stage_cards(
    ledger_cards: list[dict[str, Any]],
    signal_cards: list[dict[str, Any]],
    *,
    games: list[dict[str, Any]] | None = None,
    plays: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Ledger holds the full slate history; latest signals refresh in-place."""
    merged: dict[str, dict[str, Any]] = {}
    for card in ledger_cards:
        merged[_stage_card_key(card)] = dict(card)
    for card in signal_cards:
        key = _stage_card_key(card)
        if key in merged:
            old = merged[key]
            row = {**old, **card, "created_at": old.get("created_at") or card.get("created_at")}
            row["picks"] = _merge_stage_picks(old.get("picks") or {}, card.get("picks") or {})
            hybrid = (row["picks"].get("hybrid") or {})
            old_hybrid = (old.get("picks") or {}).get("hybrid") or {}
            if _is_validated_hybrid(old_hybrid) and hybrid.get("team") == old_hybrid.get("team"):
                for fld in (
                    "hybrid_agrees_with",
                    "conflict_stages",
                    "consensus_side",
                    "consensus_team",
                    "agreement",
                ):
                    if fld in old:
                        row[fld] = old[fld]
            merged[key] = row
        else:
            merged[key] = dict(card)
    return _enrich_stage_kickoffs(list(merged.values()), games=games, plays=plays)


def _week_file_slug(week_start: datetime) -> str:
    return week_start.astimezone(ET).strftime("%Y-%m-%d")


def _csv_download_btn(table_id: str, filename: str) -> str:
    safe_id = _esc(table_id)
    safe_name = _esc(filename).replace("'", "&#39;")
    return (
        f'<button type="button" class="csv-btn" '
        f"onclick=\"downloadTableCsv('{safe_id}', '{safe_name}')\">Download CSV</button>"
    )


def _section_toolbar(title: str, table_id: str, filename: str) -> str:
    return (
        f'<div class="section-toolbar">'
        f'<div class="section-label section-toolbar-title">{_esc(title)}</div>'
        f"{_csv_download_btn(table_id, filename)}"
        f"</div>"
    )


def _render_stage_week_table(
    cards: list[dict],
    *,
    sport: str = "ncaaf",
    table_id: str | None = None,
) -> str:
    sorted_cards = sorted(
        cards,
        key=lambda c: (
            kickoff_sort_key(c.get("kickoff") or c.get("commence_time") or c.get("created_at")),
            str(c.get("event_id") or ""),
            _STAGE_MARKET_ORDER.get(str(c.get("market") or "spread"), 9),
        ),
    )
    n_games = len({c.get("event_id") for c in sorted_cards})
    rows = _render_stage_rows(sorted_cards, sport=sport)
    id_attr = f' id="{_esc(table_id)}"' if table_id else ""
    return (
        f'<div class="phase-sub" style="font-size:13px;margin-top:6px">{n_games} games · {len(sorted_cards)} market rows</div>'
        f'<div class="table-wrap stage-table-wrap"><table class="stage-table export-table"{id_attr}>'
        f"{_render_stage_table_head()}<tbody>{rows}</tbody></table></div>"
        f'<p class="phase-note stage-scroll-hint">Three rows per game (spread, ML, total). '
        f"<b>Quant Pick</b> is the system pick for that market — it can disagree with Model/Sharp/Public "
        f"when <b>Diff</b> (money vs tickets) confirms sharp action.</p>"
    )


def _render_stage_weeks_html(cards: list[dict], *, sport: str = "ncaaf") -> str:
    if not cards:
        empty = (
            "No stage picks for this NFL week yet. Run the NFL Pipeline when the slate is posted."
            if sport == "nfl"
            else "No stage picks for this college week yet. Run the NCAAF pipeline when the slate is posted."
        )
        return f'<div class="empty">{empty}</div>'
    groups = (
        group_stage_cards_by_nfl_week(cards)
        if sport == "nfl"
        else group_stage_cards_by_college_week(cards)
    )
    label_fn = nfl_week_label if sport == "nfl" else college_week_label
    parts: list[str] = []
    for week_start, week_cards in groups:
        label = label_fn(week_start)
        parts.append(
            f'<div class="week-block">'
            f'<div class="phase-sub" style="font-size:13px;margin-top:14px">{_esc(label)}</div>'
            f"{_render_stage_week_table(week_cards, sport=sport)}"
            f"</div>"
        )
    return "".join(parts)


def _render_historical_weeks(
    weeks: list[tuple[Any, list[dict[str, Any]]]],
    *,
    sport: str = "ncaaf",
    ledger_plays: list[dict[str, Any]] | None = None,
) -> str:
    if not weeks:
        empty = (
            "No prior NFL weeks archived yet. When the NFL week rolls over (Wednesday ET), "
            "that week's stage winners and quant pick leans move here automatically."
            if sport == "nfl"
            else "No prior weeks archived yet. When the college week rolls over "
            "(Monday ET), that week's stage winners and quant pick leans move here automatically."
        )
        return f'<div class="empty">{empty}</div>'
    label_fn = nfl_week_label if sport == "nfl" else college_week_label
    parts: list[str] = []
    all_ledger = ledger_plays or []
    for week_start, week_cards in weeks:
        label = label_fn(week_start)
        slug = _week_file_slug(week_start)
        prefix = "nfl" if sport == "nfl" else "cfb"
        stages_id = f"hist-{prefix}-stages-{slug}"
        leans_id = f"hist-{prefix}-leans-{slug}"
        week_ledger = _filter_plays_for_week_start(all_ledger, week_start, sport=sport)
        parts.append(
            f'<div class="week-block historical-week">'
            f'<div class="section-label" style="margin-top:18px">{_esc(label)}</div>'
            f"{_render_weekly_lens_scorecard(week_cards, ledger_plays=week_ledger)}"
            f"{_section_toolbar('Quant Pick Leans', leans_id, f'sharp-scout-{prefix}-leans-{slug}.csv')}"
            f"{_render_hybrid_leans_section(week_cards, sport=sport, show_intro=False, table_id=leans_id, ledger_plays=week_ledger)}"
            f"{_section_toolbar('Pregame Stage Winners', stages_id, f'sharp-scout-{prefix}-stages-{slug}.csv')}"
            f"{_render_stage_week_table(week_cards, sport=sport, table_id=stages_id)}"
            f"</div>"
        )
    return "".join(parts)


def _render_cfb_historical_weeks(
    weeks: list[tuple[Any, list[dict[str, Any]]]],
    *,
    sport: str = "ncaaf",
    ledger_plays: list[dict[str, Any]] | None = None,
) -> str:
    """Backward-compatible alias."""
    return _render_historical_weeks(weeks, sport=sport, ledger_plays=ledger_plays)


def _filter_plays_for_college_week_start(
    plays: list[dict[str, Any]],
    week_start: datetime,
) -> list[dict[str, Any]]:
    start, end = college_week_bounds(week_start)
    out: list[dict[str, Any]] = []
    for play in plays:
        kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(play)
    return out


def _filter_plays_for_nfl_week_start(
    plays: list[dict[str, Any]],
    week_start: datetime,
) -> list[dict[str, Any]]:
    start, end = nfl_week_bounds(week_start)
    out: list[dict[str, Any]] = []
    for play in plays:
        kickoff = parse_commence(play.get("kickoff") or play.get("commence_time"))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            out.append(play)
    return out


def _filter_plays_for_week_start(
    plays: list[dict[str, Any]],
    week_start: datetime,
    *,
    sport: str = "ncaaf",
) -> list[dict[str, Any]]:
    if sport == "nfl":
        return _filter_plays_for_nfl_week_start(plays, week_start)
    return _filter_plays_for_college_week_start(plays, week_start)


def _compute_play_record(plays: list[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = pushes = pending = 0
    for play in plays:
        st = play.get("status") or "pending"
        if st == "win":
            wins += 1
        elif st == "loss":
            losses += 1
        elif st == "push":
            pushes += 1
        else:
            pending += 1
    decided = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_pct": (wins / decided) if decided else None,
    }


def _compute_stage_records_from_cards(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stage_records: dict[str, dict[str, Any]] = {}
    for card in cards:
        if str(card.get("event_id") or "").startswith("demo-"):
            continue
        for stage, result in (card.get("results") or {}).items():
            bucket = stage_records.setdefault(
                stage, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0}
            )
            if result == "win":
                bucket["wins"] += 1
            elif result == "loss":
                bucket["losses"] += 1
            elif result == "push":
                bucket["pushes"] += 1
            elif result is not None:
                bucket["pending"] += 1
        if card.get("status") in (None, "pending"):
            for stage, pick in (card.get("picks") or {}).items():
                if not pick.get("available") or not pick.get("side"):
                    continue
                bucket = stage_records.setdefault(
                    stage, {"wins": 0, "losses": 0, "pushes": 0, "pending": 0}
                )
                existing = (card.get("results") or {}).get(stage)
                if existing is None and stage not in (card.get("results") or {}):
                    bucket["pending"] += 1
    for stage, b in stage_records.items():
        decided = b["wins"] + b["losses"]
        b["record"] = f"{b['wins']}-{b['losses']}" + (f"-{b['pushes']}" if b["pushes"] else "")
        b["win_pct"] = (b["wins"] / decided) if decided else None
    return stage_records


def _render_weekly_lens_scorecard(
    cards: list[dict[str, Any]],
    *,
    ledger_plays: list[dict[str, Any]] | None = None,
) -> str:
    stage_records = _compute_stage_records_from_cards(cards)
    ledger_rec = _compute_play_record(ledger_plays or [])
    rows: list[str] = []
    if ledger_plays is not None:
        wp = f"{ledger_rec['win_pct'] * 100:.0f}%" if ledger_rec.get("win_pct") is not None else "—"
        rows.append(
            "<tr class='weekly-score-sharp-play'>"
            "<td><b>Sharp Plays (ledger)</b></td>"
            f"<td><b>{_esc(ledger_rec.get('record') or '0-0')}</b></td>"
            f"<td>{wp}</td>"
            f"<td>{ledger_rec.get('pending', 0)}</td>"
            "</tr>"
        )
    stage_rows = _render_stage_record_rows(stage_records)
    if stage_rows.startswith("<tr"):
        rows.append(stage_rows)
    body = "\n".join(rows) if rows else "<tr><td colspan='4'>No graded picks this week yet.</td></tr>"
    return (
        '<div class="section-label" style="margin-top:8px">Weekly Lens Scorecard</div>'
        '<p class="phase-note" style="padding:4px 0 8px">'
        "How each lens performed this week if you bet every pick (spread, ML, total). "
        "<b>Sharp Plays</b> = actual posted bets only.</p>"
        '<div class="table-wrap"><table class="weekly-scorecard-table">'
        "<thead><tr><th>Lens</th><th>Record</th><th>Win %</th><th>Ungraded</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _render_stage_rows(cards: list[dict], *, sport: str = "nfl") -> str:
    if not cards:
        return "<tr><td colspan='11'>No stage picks yet. Run the pipeline.</td></tr>"
    rows = []
    for c in cards:
        picks = c.get("picks") or {}
        hybrid = picks.get("hybrid") or {}
        agrees = ", ".join(c.get("hybrid_agrees_with") or []) or "—"
        flag = ""
        svp = (c.get("agreement") or {}).get("sharp_vs_public") or {}
        if svp.get("fade_public"):
            flag = "fade pub"
        if (c.get("agreement") or {}).get("rlm_active"):
            flag = (flag + " · RLM").strip(" ·")
        kick_raw = c.get("kickoff") or c.get("commence_time")
        kick_s = format_kickoff_compact(kick_raw)
        away = str(c.get("away_team") or "")
        home = str(c.get("home_team") or "")
        if sport == "ncaaf":
            matchup = f"{_esc(ncaaf_display_code(away))} @ {_esc(ncaaf_display_code(home))}"
        else:
            matchup = f"{_esc(away)} @ {_esc(home)}"
        rows.append(
            "<tr>"
            f"<td>{_esc(kick_s)}</td>"
            f"<td>{matchup}</td>"
            f"<td>{_esc(_stage_market_label(c.get('market')))}</td>"
            f"<td class='hybrid-cell pos'>{_pick_cell(hybrid, sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('model'), sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('sharp'), sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('public'), sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('money'), sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('sharp_edge'), sport=sport)}</td>"
            f"<td>{_pick_cell(picks.get('rlm'), sport=sport)}</td>"
            f"<td>{_esc(flag or agrees)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _render_disagreement_rows(disagreements: dict[str, Any] | None) -> str:
    """Per-category count + hit rate for model-vs-market disagreements."""
    disagreements = disagreements or {}
    by_cat = disagreements.get("by_category") or {}
    if not by_cat:
        return "<tr><td colspan='3'>No logged disagreements yet. They appear when the model differs from the market beyond the threshold.</td></tr>"
    rows = []
    for cat, b in by_cat.items():
        wp = f"{b['win_pct'] * 100:.0f}%" if b.get("win_pct") is not None else "—"
        rec = b.get("record") or "—"
        rows.append(
            f"<tr><td><b>{_esc(cat)}</b></td>"
            f"<td>{b.get('count', 0)}</td>"
            f"<td>{_esc(rec)} · {wp}</td></tr>"
        )
    return "\n".join(rows)


def _stage_record_label(stage: str) -> str:
    """Stage name with hover tooltip for the records table."""
    label = STAGE_LABELS.get(stage, stage.replace("_", " ").title())
    tip = STAGE_RECORD_TIPS.get(stage)
    if not tip:
        return f"<b>{_esc(label)}</b>"
    return (
        f'<span class="stage-record-label"><b>{_esc(label)}</b>'
        f'{_stat_tip_icon(tip)}</span>'
    )


def _hybrid_lean_kind(pick: dict[str, Any]) -> str:
    reason = (pick.get("reason") or "").lower()
    if "model aligned" in reason:
        return "aligned"
    return "model"


def _extract_hybrid_leans(
    stage_cards: list[dict[str, Any]],
    *,
    ledger_plays: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """All quant pick rows for the slate — flagged when posted as a Sharp Play."""
    ledger_keys = _ledger_play_keys(ledger_plays or [])
    leans: list[dict[str, Any]] = []
    for card in stage_cards:
        hybrid = (card.get("picks") or {}).get("hybrid") or {}
        if not hybrid.get("available") or not hybrid.get("side"):
            continue
        row_key = _quant_pick_row_key(card, hybrid)
        is_sharp_play = _is_validated_hybrid(hybrid) or row_key in ledger_keys
        if is_sharp_play:
            kind = "sharp_play"
        elif _hybrid_lean_kind(hybrid) == "aligned":
            kind = "aligned"
        else:
            kind = "model"
        leans.append(
            {
                "event_id": card.get("event_id"),
                "home_team": card.get("home_team"),
                "away_team": card.get("away_team"),
                "market": card.get("market") or "spread",
                "kickoff": card.get("kickoff") or card.get("commence_time"),
                "pick": hybrid,
                "kind": kind,
                "is_sharp_play": is_sharp_play,
                "result": (card.get("results") or {}).get("hybrid"),
                "home_score": card.get("home_score"),
                "away_score": card.get("away_score"),
            }
        )
    return sorted(
        leans,
        key=lambda row: (
            kickoff_sort_key(row.get("kickoff")),
            str(row.get("event_id") or ""),
            _STAGE_MARKET_ORDER.get(str(row.get("market") or "spread"), 9),
        ),
    )


def _render_hybrid_leans_section(
    stage_cards: list[dict[str, Any]],
    *,
    sport: str = "ncaaf",
    show_intro: bool = True,
    table_id: str | None = None,
    ledger_plays: list[dict[str, Any]] | None = None,
) -> str:
    leans = _extract_hybrid_leans(stage_cards, ledger_plays=ledger_plays)
    if not leans:
        empty = (
            "No quant picks on the current slate. "
            if show_intro
            else "No quant picks for this week."
        )
        return (
            f'<div class="empty">{empty} '
            "Rows appear when the quant model has a side for spread, ML, or total.</div>"
        )

    sharp_rows = [row for row in leans if row.get("is_sharp_play")]
    lean_only_rows = [row for row in leans if not row.get("is_sharp_play")]

    wins = losses = pushes = pending = 0
    for row in lean_only_rows:
        result = row.get("result")
        if result == "win":
            wins += 1
        elif result == "loss":
            losses += 1
        elif result == "push":
            pushes += 1
        else:
            pending += 1

    decided = wins + losses
    win_pct = f"{wins / decided * 100:.0f}%" if decided else "—"
    record = f"{wins}-{losses}" + (f"-{pushes}" if pushes else "")
    if pending:
        record += f" · {pending} pending"

    kind_labels = {
        "sharp_play": "Sharp Play",
        "aligned": "Market aligned",
        "model": "Model lean",
    }

    rows = []
    for row in leans:
        hybrid = row["pick"]
        away = str(row.get("away_team") or "")
        home = str(row.get("home_team") or "")
        if sport == "ncaaf":
            matchup = f"{_esc(ncaaf_display_code(away))} @ {_esc(ncaaf_display_code(home))}"
        else:
            matchup = f"{_esc(away)} @ {_esc(home)}"
        kick_s = format_kickoff_compact(row.get("kickoff"))
        kind = kind_labels.get(str(row.get("kind") or ""), "Model lean")
        result = row.get("result")
        if result in ("win", "loss", "push"):
            result_html = _status_badge(result)
        else:
            result_html = _status_badge("pending")
        score = ""
        if row.get("home_score") is not None:
            score = (
                f" · Final {row.get('away_team')} {row.get('away_score')}, "
                f"{row.get('home_team')} {row.get('home_score')}"
            )
        row_cls = ' class="lean-row-sharp-play"' if row.get("is_sharp_play") else ""
        rows.append(
            f"<tr{row_cls}>"
            f"<td>{_esc(kick_s)}</td>"
            f"<td>{matchup}</td>"
            f"<td>{_esc(_stage_market_label(row.get('market')))}</td>"
            f"<td class='pos'>{_pick_cell(hybrid, sport=sport)}</td>"
            f"<td>{_esc(kind)}</td>"
            f"<td>{result_html}</td>"
            f"<td class='rationale-cell'>{_esc(hybrid.get('reason') or '')}{_esc(score)}</td>"
            "</tr>"
        )

    intro = (
        f'<p class="phase-note" style="padding:4px 0 10px">{_esc(HYBRID_LEANS_SECTION_NOTE)}</p>'
        if show_intro
        else ""
    )
    lean_label = "Leans only" if show_intro else "Leans"
    id_attr = f' id="{_esc(table_id)}"' if table_id else ""
    return (
        intro
        + f'<div class="summary-grid" style="margin-bottom:10px">'
        + _stat_card(str(len(sharp_rows)), "Sharp Plays", "Posted quant picks — highlighted yellow in the table.")
        + _stat_card(str(len(lean_only_rows)), lean_label, "Quant pick ideas not posted as Sharp Plays.")
        + _stat_card(record, "Lean record", "Win-loss on lean-only rows (not ledger Sharp Plays).")
        + _stat_card(win_pct, "Lean win %", "Settled lean-only rows.")
        + "</div>"
        f'<div class="table-wrap"><table class="export-table"{id_attr}>'
        "<thead><tr><th>Kickoff</th><th>Game</th><th>Mkt</th><th>Quant Pick</th>"
        "<th>Type</th><th>Result</th><th>Why</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_stage_record_rows(stage_records: dict) -> str:
    if not stage_records:
        return "<tr><td colspan='4'>Stage records appear after games settle.</td></tr>"
    order = ["hybrid", "model", "sharp", "money", "sharp_edge", "rlm", "public"]
    rows = []
    for stage in order:
        b = stage_records.get(stage)
        if not b:
            continue
        wp = f"{b['win_pct']*100:.0f}%" if b.get("win_pct") is not None else "—"
        rows.append(
            f"<tr><td>{_stage_record_label(stage)}</td>"
            f"<td>{_esc(b.get('record'))}</td>"
            f"<td>{wp}</td>"
            f"<td>{b.get('pending', 0)}</td></tr>"
        )
    # any extra stages
    for stage, b in stage_records.items():
        if stage in order:
            continue
        wp = f"{b['win_pct']*100:.0f}%" if b.get("win_pct") is not None else "—"
        rows.append(
            f"<tr><td>{_stage_record_label(stage)}</td>"
            f"<td>{_esc(b.get('record'))}</td>"
            f"<td>{wp}</td>"
            f"<td>{b.get('pending', 0)}</td></tr>"
        )
    return "\n".join(rows) if rows else "<tr><td colspan='4'>No stage records.</td></tr>"


SITE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Sharp Scout Quant</title>
<meta name="description" content="Sharp Scout Quant — NFL and CFB quant model plays and record">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --font-serif: 'Cormorant Garamond', Georgia, 'Times New Roman', serif;
    --font-sans: 'Karla', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono: 'Inconsolata', 'SF Mono', Menlo, monospace;
    --color-text: #222222;
    --color-text-muted: #555555;
    --color-bg: #ffffff;
    --color-bg-soft: #fafafa;
    --color-slate: #dbe4ed;
    --color-navy: #1e3a5f;
    --color-border: #000000;
    --color-win: #15803d;
    --color-loss: #dc2626;
    --color-hybrid: #166534;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--font-sans);
    background: var(--color-bg-soft);
    color: var(--color-text);
    min-height: 100vh;
    font-size: 14px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}
  .header {{
    background: var(--color-slate);
    padding: 28px 16px 22px;
    border-bottom: 1px solid #c5d0dc;
  }}
  .header-inner {{
    max-width: 1240px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: 14px;
  }}
  .header-text {{
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
  }}
  .header-logo {{
    flex-shrink: 0;
  }}
  .ssq-logo {{
    display: block;
    width: 76px;
    height: 76px;
  }}
  .header h1 {{
    font-family: var(--font-serif);
    font-size: 34px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--color-text);
    text-transform: none;
    text-align: center;
  }}
  .header p {{
    color: var(--color-text-muted);
    font-size: 13px;
    font-weight: 300;
    margin-top: 8px;
    max-width: 520px;
    text-align: center;
  }}
  .header-updated {{
    display: none;
  }}
  .board-nav {{
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .board-updated-bar {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    flex-wrap: wrap;
    background: var(--color-navy);
    color: #fff;
    padding: 9px 12px;
    border-bottom: 1px solid #152a45;
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .board-updated-label {{
    opacity: 0.85;
    font-weight: 500;
  }}
  .board-updated-time {{
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: none;
  }}
  .pill {{
    display: inline-block;
    margin-top: 12px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-weight: 500;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 5px 12px;
    border-radius: 0;
  }}
  .tabs {{
    display: flex;
    background: var(--color-bg);
    border-bottom: 1px solid #e5e5e5;
  }}
  .tab {{
    flex: 1;
    padding: 14px 8px;
    text-align: center;
    cursor: pointer;
    color: var(--color-text-muted);
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    border-bottom: 2px solid transparent;
  }}
  .tab.active {{
    color: #ffffff;
    font-weight: 600;
    border-bottom-color: var(--color-navy);
    background: var(--color-navy);
  }}
  .content {{ display: none; padding: 20px 16px 32px; max-width: 900px; margin: 0 auto; }}
  .content.active {{ display: block; }}
  #tab-plays.content {{ max-width: 1240px; }}
  #tab-nfl-historical.content {{ max-width: 1240px; }}
  #tab-cfb.content {{ max-width: 1240px; }}
  #tab-cfb-historical.content {{ max-width: 1240px; }}
  #tab-guide.content {{ max-width: 820px; }}
  .guide-block {{ margin: 0 0 28px; }}
  .guide-block h2 {{
    font-family: var(--font-serif);
    font-size: 22px;
    font-weight: 500;
    margin: 0 0 10px;
    color: var(--color-text);
  }}
  .guide-block h3 {{
    font-family: var(--font-mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-text-muted);
    margin: 18px 0 8px;
  }}
  .guide-block p, .guide-block li {{
    font-size: 15px;
    line-height: 1.65;
    color: var(--color-text);
    margin: 0 0 10px;
  }}
  .guide-block ul {{ margin: 0 0 12px; padding-left: 1.25rem; }}
  .guide-block li {{ margin-bottom: 6px; }}
  .guide-callout {{
    border-left: 3px solid var(--color-navy);
    background: var(--color-slate);
    padding: 12px 14px;
    margin: 14px 0;
  }}
  .guide-callout p {{ margin: 0; font-size: 14px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 22px; }}
  @media (min-width: 700px) {{ .summary-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
  .stat-card {{
    background: var(--color-slate);
    border: 2px solid var(--color-border);
    border-radius: 0;
    padding: 16px 10px;
    text-align: center;
  }}
  .stat-val {{
    font-family: var(--font-serif);
    font-size: 28px;
    font-weight: 500;
    color: var(--color-text);
    line-height: 1.1;
  }}
  .stat-label {{
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--color-text-muted);
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    flex-wrap: wrap;
  }}
  .stat-tip {{ margin-left: 2px; }}
  .stage-record-label {{ display: inline-flex; align-items: center; gap: 4px; }}
  .section-label {{
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: var(--color-text);
    text-transform: uppercase;
    margin: 24px 0 12px;
  }}
  .section-toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 8px; flex-wrap: wrap; }}
  .section-toolbar-title {{ margin: 0; font-size: 9px; }}
  .csv-btn {{
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 7px 12px;
    border-radius: 0;
    cursor: pointer;
    white-space: nowrap;
  }}
  .csv-btn:hover {{ background: var(--color-bg-soft); }}
  .play-card {{
    background: var(--color-bg);
    border: 1px solid #e5e5e5;
    border-left: 3px solid var(--color-border);
    border-radius: 0;
    padding: 18px 16px;
    margin-bottom: 12px;
    position: relative;
    overflow: hidden;
  }}
  .play-card::before {{ content: none; }}
  .sharp-play {{ border-left-color: var(--color-win); }}
  .sharp-lean {{ border-left-color: #ca8a04; }}
  .candidate {{ border-left-color: #6b7280; }}
  .card-top {{ display: flex; justify-content: space-between; gap: 8px; }}
  .tier-badge {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 4px 8px;
    border-radius: 0;
    margin-bottom: 6px;
    border: 1px solid var(--color-border);
  }}
  .badge-play {{ background: var(--color-text); color: #fff; border-color: var(--color-text); }}
  .badge-lean {{ background: #fff; color: var(--color-text); }}
  .badge-cand {{ background: var(--color-bg-soft); color: var(--color-text-muted); }}
  .play-title {{
    font-family: var(--font-serif);
    font-size: 24px;
    font-weight: 600;
    color: var(--color-text);
    line-height: 1.15;
  }}
  .play-subtitle {{ font-size: 12px; color: var(--color-text-muted); margin-top: 4px; font-weight: 300; }}
  .units-badge {{
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: 12px;
    letter-spacing: 0.06em;
    padding: 6px 12px;
    border-radius: 0;
    font-weight: 600;
    height: fit-content;
  }}
  .card-result {{ display: inline-block; font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 8px; border-radius: 0; margin-top: 10px; }}
  .card-result.win {{ background: #ecfdf5; border: 1px solid var(--color-win); color: var(--color-win); }}
  .card-result.loss {{ background: #fef2f2; border: 1px solid var(--color-loss); color: var(--color-loss); }}
  .card-result.pending {{ background: var(--color-bg-soft); border: 1px solid #d1d5db; color: var(--color-text-muted); }}
  .play-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin-top: 12px; font-size: 12px; }}
  .meta-label {{ color: var(--color-text-muted); font-weight: 300; }}
  .meta-val {{ font-weight: 600; color: var(--color-text); }}
  .conf-track {{ background: #e5e7eb; border-radius: 4px; height: 5px; margin-top: 10px; }}
  .conf-fill {{ height: 5px; border-radius: 4px; }}
  .rationale-toggle {{ margin-top: 12px; color: var(--color-text-muted); font-size: 12px; cursor: pointer; display: flex; gap: 6px; align-items: center; }}
  .rationale-toggle.open .arrow {{ transform: rotate(90deg); }}
  .rationale-body {{ display: none; font-size: 13px; color: var(--color-text-muted); margin-top: 8px; line-height: 1.7; border-top: 1px solid #ececec; padding-top: 10px; }}
  .rationale-body.open {{ display: block; }}
  .rationale-cell {{ font-size: 12px; color: var(--color-text-muted); line-height: 1.55; max-width: 320px; }}
  .stage-why {{ font-size: 12px; color: var(--color-text-muted); line-height: 1.55; max-width: 420px; }}
  .splits-summary {{ color: var(--color-text); margin-bottom: 8px; }}
  .table-wrap {{ overflow-x: auto; border: 2px solid var(--color-border); border-radius: 0; background: var(--color-bg); }}
  .stage-table-wrap {{ margin-bottom: 8px; }}
  .stage-table {{ min-width: 980px; font-size: 11px; }}
  .stage-table th, .stage-table td {{ white-space: nowrap; padding: 6px 7px; }}
  .stage-table th:nth-child(1), .stage-table td:nth-child(1) {{ white-space: nowrap; min-width: 150px; }}
  .stage-table th:nth-child(2), .stage-table td:nth-child(2) {{ white-space: nowrap; min-width: 0; max-width: 108px; }}
  .stage-table th.hybrid-col, .stage-table td.hybrid-cell {{
    background: #f4faf6;
    border-left: 1px solid #b7e4c7;
    border-right: 1px solid #b7e4c7;
    font-weight: 600;
    color: var(--color-hybrid);
  }}
  .stage-table th.hybrid-col {{ background: var(--color-hybrid); color: #fff; border-left: 1px solid var(--color-border); border-right: 1px solid var(--color-border); }}
  .stage-table th:nth-child(11), .stage-table td:nth-child(11) {{
    white-space: normal; min-width: 72px; max-width: 120px; font-size: 11px; color: #4b5563;
  }}
  .stage-scroll-hint {{ margin: 8px 2px 0; font-size: 11px; color: #4b5563; }}
  .stage-th {{ white-space: nowrap; }}
  .th-tip {{
    display: inline-flex;
    align-items: center;
    margin-left: 4px;
    cursor: pointer;
    vertical-align: middle;
    color: #9ca3af;
    line-height: 0;
    position: relative;
  }}
  .th-tip:hover, .th-tip:focus {{ color: var(--color-text); outline: none; }}
  .th-tip:focus-visible {{ box-shadow: 0 0 0 1px var(--color-border); border-radius: 0; }}
  .th-tip-icon {{ display: block; pointer-events: none; }}
  .th-tip-float {{
    position: fixed;
    z-index: 10000;
    display: none;
    max-width: min(280px, calc(100vw - 16px));
    padding: 8px 10px;
    background: #fff;
    border: 2px solid #000;
    border-radius: 6px;
    color: #111827;
    font-size: 12px;
    font-weight: 400;
    line-height: 1.45;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    pointer-events: none;
    white-space: normal;
    text-transform: none;
    letter-spacing: normal;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; min-width: 520px; font-family: var(--font-sans); }}
  th {{
    background: var(--color-border);
    color: #fff;
    font-family: var(--font-mono);
    font-weight: 600;
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    text-align: left;
    padding: 11px 10px;
    border-bottom: 1px solid var(--color-border);
  }}
  .stage-table th {{ background: var(--color-border); color: #fff; }}
  .stage-table th .th-tip {{ color: #d1d5db; }}
  .stage-table th .th-tip:hover, .stage-table th .th-tip:focus {{ color: #fff; }}
  .stage-table th.hybrid-col {{ background: var(--color-hybrid); color: #fff; }}
  td {{ padding: 10px; border-bottom: 1px solid #ececec; color: var(--color-text); }}
  tr:last-child td {{ border-bottom: none; }}
  .lean-row-sharp-play td {{
    background: #fef9c3;
    font-weight: 700;
    border-bottom-color: #fde047;
  }}
  .lean-row-sharp-play td.pos {{
    color: #854d0e;
    font-weight: 800;
  }}
  .weekly-score-sharp-play td {{
    background: #fef9c3;
    font-weight: 700;
    border-bottom-color: #fde047;
  }}
  .win {{ color: var(--color-win); font-weight: 600; }}
  .loss {{ color: var(--color-loss); font-weight: 600; }}
  .pending {{ color: var(--color-text-muted); font-weight: 500; }}
  .pos {{ color: var(--color-win); font-weight: 600; }}
  .neg {{ color: var(--color-loss); font-weight: 600; }}
  .empty {{ color: var(--color-text-muted); text-align: center; padding: 36px 8px; font-weight: 300; }}
  .game-card {{ background: var(--color-bg); border: 1px solid #e5e5e5; border-radius: 0; padding: 18px; margin-bottom: 16px; }}
  .game-head {{ margin-bottom: 10px; }}
  .game-title {{ font-family: var(--font-serif); font-size: 24px; font-weight: 600; color: var(--color-text); }}
  .game-kick {{ font-size: 11px; color: var(--color-text-muted); margin-top: 4px; font-family: var(--font-mono); letter-spacing: 0.06em; text-transform: uppercase; }}
  .phase-block {{ margin-top: 14px; border-top: 1px solid #ececec; padding-top: 12px; }}
  .phase-label {{
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--color-text);
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .phase-note {{ font-size: 13px; color: var(--color-text-muted); margin: 4px 0; line-height: 1.65; font-weight: 300; }}
  .phase-sub {{ font-family: var(--font-mono); font-size: 10px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-text-muted); margin: 8px 0 4px; }}
  .footer {{ color: var(--color-text-muted); font-size: 11px; padding: 32px 16px; text-align: center; line-height: 1.7; font-weight: 300; }}
  @media (max-width: 640px) {{
    .ssq-logo {{ width: 56px; height: 56px; }}
    .header h1 {{ font-size: 28px; }}
  }}
</style>
</head>
<body>
<div class="header">
  <div class="header-inner">
    <div class="header-logo">
      {ssq_logo}
    </div>
    <div class="header-text">
      <h1>Sharp Scout Quant</h1>
      <p>NFL + NCAAF quant model · ratings → Monte Carlo → sharp EV → split filter</p>
      <span class="pill">NFL {nfl_record} · {nfl_pnl}u · CFB {ncaaf_record} · {ncaaf_pnl}u · {ncaaf_demo_note}</span>
    </div>
  </div>
</div>
<div class="board-nav">
  <div class="board-updated-bar" role="status" aria-live="polite">
    <span class="board-updated-label">Picks &amp; prices updated</span>
    <span class="board-updated-time">{board_updated}</span>
  </div>
<div class="tabs">
  <div class="tab active" onclick="showTab('plays', this)">NFL</div>
  <div class="tab" onclick="showTab('nfl-historical', this)">NFL Historical</div>
  <div class="tab" onclick="showTab('games', this)">Games</div>
  <div class="tab" onclick="showTab('stages', this)">Stages</div>
  <div class="tab" onclick="showTab('ratings', this)">Ratings</div>
  <div class="tab" onclick="showTab('cfb', this)">CFB</div>
  <div class="tab" onclick="showTab('cfb-historical', this)">CFB Historical</div>
  <div class="tab" onclick="showTab('guide', this)">How to use</div>
</div>
</div>

<div id="tab-plays" class="content active">
  <div class="summary-grid">{nfl_top_stats_html}</div>
  <div class="section-label">Closing Line Value</div>
  {nfl_clv_banner_html}
  <div class="section-label">This Week's Plays · {nfl_signal_count} validated</div>
  {plays_html}
  <div class="section-label">This Week — Pregame Stage Winners</div>
  <p class="phase-note" style="padding:4px 0 10px">Current NFL week only (Wed–Tue ET; advances to the next slate when this week is empty). Prior weeks are on <b>NFL Historical</b>. Three rows per game (spread, ML, total). <b>Quant Pick</b> (green column) matches Sharp Plays above when validated.</p>
  {nfl_stage_weeks_html}
  <div class="section-label">NFL Stage Records (season)</div>
  <p class="phase-note" style="padding:4px 0 10px">{stage_record_section_note}</p>
  <div class="summary-grid">{stage_alarm_stats_html}</div>
  <div class="table-wrap"><table>
    {stage_records_thead}
    <tbody>{stage_record_rows}</tbody>
  </table></div>
  <div class="section-label">NFL Ledger · {nfl_pending} pending · {nfl_n_plays} total</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Kickoff</th><th>Game</th><th>Play</th><th>Units</th><th>Result</th><th>Score</th><th>CLV</th><th>PnL</th></tr></thead>
    <tbody>{nfl_ledger_rows}</tbody>
  </table></div>
  <div class="section-label">This Week — Quant Pick Leans</div>
  {nfl_leans_html}
</div>

<div id="tab-nfl-historical" class="content">
  <p class="phase-note" style="padding:8px 0">Archive of completed NFL weeks. Each Wednesday ET, the prior week's stage winners and quant pick leans move here from the NFL tab. Use <b>Download CSV</b> on each table to export.</p>
  {nfl_historical_html}
</div>

<div id="tab-games" class="content">
  <p class="phase-note" style="padding:12px 0">Per-game pipeline output: EPA model → Monte Carlo → market EV → money/ticket splits → stage picks.</p>
  {games_html}
</div>

<div id="tab-stages" class="content">
  <div class="summary-grid">{stage_alarm_stats_html}</div>
  {stage_highlights_html}
  <div class="section-label">Stage Records (settled)</div>
  <p class="phase-note" style="padding:4px 0 10px">{stage_record_section_note}</p>
  <div class="table-wrap"><table>
    {stage_records_thead}
    <tbody>{stage_record_rows}</tbody>
  </table></div>
  <div class="section-label">Why Is Our Model Wrong? (disagreement log)</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Category</th><th>Count</th><th>Record · Hit %</th></tr></thead>
    <tbody>{disagreement_rows}</tbody>
  </table></div>
  <div class="section-label">Per-Game Stage Winners</div>
  <div class="table-wrap stage-table-wrap"><table class="stage-table">
    {stage_table_head}
    <tbody>{stage_rows}</tbody>
  </table></div>
  <p class="footer" style="padding:12px 0">Each column is an independent lens. <b>Quant Pick</b> is the system pick per market — Sharp Plays come from validated quant pick ML/spread/total rows.</p>
</div>

<div id="tab-ratings" class="content">
  <p class="phase-note" style="padding:8px 0">Power ratings from nflverse play-by-play (EPA per play), opponent-adjusted via ridge regression with recency weighting. Updated each pipeline run from the latest PBP data.</p>
  <div class="section-label">Power Ratings</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Team</th><th>Power</th><th>Off EPA</th><th>Def EPA</th></tr></thead>
    <tbody>{ratings_rows}</tbody>
  </table></div>
</div>

<div id="tab-cfb" class="content">
  <div class="summary-grid">{ncaaf_top_stats_html}</div>
  <div class="section-label">Closing Line Value</div>
  {ncaaf_clv_banner_html}
  <div class="section-label">This Week's Plays · {ncaaf_week_play_count} validated</div>
  {ncaaf_plays_html}
  <div class="section-label">This Week — Pregame Stage Winners</div>
  <p class="phase-note" style="padding:4px 0 10px">Current college week only (Mon–Sun ET). Prior weeks are on <b>CFB Historical</b>. Three rows per game (spread, ML, total). <b>Quant Pick</b> (green column) matches Sharp Plays above when validated.</p>
  {ncaaf_stage_weeks_html}
  <div class="section-label">NCAAF Stage Records (season)</div>
  <p class="phase-note" style="padding:4px 0 10px">{stage_record_section_note}</p>
  <div class="summary-grid">{ncaaf_alarm_stats_html}</div>
  <div class="table-wrap"><table>
    {stage_records_thead}
    <tbody>{ncaaf_stage_record_rows}</tbody>
  </table></div>
  <div class="section-label">NCAAF Ledger · {ncaaf_pending} pending · {ncaaf_n_plays} total</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Kickoff</th><th>Game</th><th>Play</th><th>Units</th><th>Result</th><th>Score</th><th>CLV</th><th>PnL</th></tr></thead>
    <tbody>{ncaaf_ledger_rows}</tbody>
  </table></div>
  <div class="section-label">This Week — Quant Pick Leans</div>
  {ncaaf_leans_html}
</div>

<div id="tab-cfb-historical" class="content">
  <p class="phase-note" style="padding:8px 0">Archive of completed college weeks. Each Monday ET, the prior week's stage winners and quant pick leans move here from the CFB tab. Use <b>Download CSV</b> on each table to export.</p>
  {ncaaf_historical_html}
</div>

<div id="tab-guide" class="content">
  {guide_html}
</div>

<p class="footer">Signals only — no auto-betting. Data: nflverse · cfbfastR · The Odds API · Action Network.<br>
Source: ledger.json · record.json · ncaaf_ledger.json · ncaaf_record.json · latest signals</p>
<script>
function showTab(name, el) {{
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
  if (typeof gtag === 'function') {{
    gtag('event', 'page_view', {{
      page_title: 'Sharp Scout Quant — ' + name,
      page_location: window.location.href.split('#')[0] + '#' + name,
      page_path: window.location.pathname + '#' + name
    }});
  }}
}}

function downloadTableCsv(tableId, filename) {{
  var table = document.getElementById(tableId);
  if (!table) return;
  var rows = [];
  table.querySelectorAll('tr').forEach(function (tr) {{
    var cells = [];
    tr.querySelectorAll('th, td').forEach(function (cell) {{
      var text = (cell.innerText || '').replace(/\\s+/g, ' ').trim();
      if (text.indexOf('"') >= 0 || text.indexOf(',') >= 0 || text.indexOf('\\n') >= 0) {{
        text = '"' + text.replace(/"/g, '""') + '"';
      }}
      cells.push(text);
    }});
    if (cells.length) rows.push(cells.join(','));
  }});
  var blob = new Blob([rows.join('\\n')], {{ type: 'text/csv;charset=utf-8;' }});
  var link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename || 'export.csv';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}}

(function () {{
  var floatTip = null;

  function ensureTip() {{
    if (!floatTip) {{
      floatTip = document.createElement('div');
      floatTip.className = 'th-tip-float';
      floatTip.setAttribute('role', 'tooltip');
      document.body.appendChild(floatTip);
    }}
    return floatTip;
  }}

  function hideTip() {{
    if (floatTip) floatTip.style.display = 'none';
  }}

  function showTip(anchor) {{
    var text = anchor.getAttribute('data-tip');
    if (!text) return hideTip();
    var tip = ensureTip();
    tip.textContent = text;
    tip.style.display = 'block';
    var r = anchor.getBoundingClientRect();
    var pad = 8;
    var left = r.left + (r.width / 2) - (tip.offsetWidth / 2);
    left = Math.max(pad, Math.min(left, window.innerWidth - tip.offsetWidth - pad));
    var top = r.bottom + 6;
    if (top + tip.offsetHeight > window.innerHeight - pad) {{
      top = r.top - tip.offsetHeight - 6;
    }}
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }}

  document.addEventListener('mouseover', function (e) {{
    var el = e.target.closest && e.target.closest('.th-tip');
    if (el) showTip(el);
  }});
  document.addEventListener('mouseout', function (e) {{
    var el = e.target.closest && e.target.closest('.th-tip');
    if (el && (!e.relatedTarget || !el.contains(e.relatedTarget))) hideTip();
  }});
  document.addEventListener('focusin', function (e) {{
    var el = e.target.closest && e.target.closest('.th-tip');
    if (el) showTip(el);
  }});
  document.addEventListener('focusout', function (e) {{
    var el = e.target.closest && e.target.closest('.th-tip');
    if (el && (!e.relatedTarget || !el.contains(e.relatedTarget))) hideTip();
  }});
  window.addEventListener('scroll', hideTip, true);
  window.addEventListener('resize', hideTip);
}})();
</script>
</body>
</html>
"""