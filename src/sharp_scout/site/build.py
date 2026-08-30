"""Build static GitHub Pages site from ledger + latest signals."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, DATA_DIR, ROOT
from sharp_scout.copy.explain import (
    BOARD_STAT_TIPS,
    collapse_best_signals,
    describe_splits_board,
    describe_stage_pick,
    format_kickoff_et,
    format_kickoff_compact,
    format_kickoff_date_et,
    format_kickoff_time_et,
    format_play_rationale,
    kickoff_sort_key,
    STAGE_COLUMN_TIPS,
    STAGE_LABELS,
    STAGE_RECORD_SECTION_NOTE,
    STAGE_RECORD_TIPS,
)
from sharp_scout.ledger.tracker import compute_record, load_ledger
from sharp_scout.sports import NCAAF
from sharp_scout.utils.slate import (
    college_week_label,
    filter_plays_college_week,
    filter_plays_nfl_week,
    filter_stage_cards_current_slate,
    group_stage_cards_by_college_week,
    parse_commence,
)
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


def _pick_ncaaf_signals() -> dict[str, Any]:
    """Prefer the signals file with the fullest current slate (avoids stale demo artifacts)."""
    best: dict[str, Any] = {}
    best_n = -1
    for path in (ARTIFACTS_DIR / NCAAF.artifact_name, DOCS_DIR / "latest_ncaaf_signals.json"):
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


def build_site(
    *,
    docs_dir: Path | None = None,
    signals_path: Path | None = None,
) -> Path:
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    ledger = load_ledger()
    record = compute_record(ledger)
    signals: dict[str, Any] = {}
    sp = signals_path or (ARTIFACTS_DIR / "latest_signals.json")
    if sp.exists():
        signals = json.loads(sp.read_text())

    # Copy data for client-side refresh / debugging
    (out / "ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
    (out / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    if signals:
        (out / "latest_signals.json").write_text(json.dumps(signals, indent=2, default=str) + "\n")

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
    nfl_week_plays = filter_plays_nfl_week(pending)
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

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    nfl_signal_count = len(nfl_week_plays_sorted)
    demo_note = "DEMO data" if signals.get("demo") else "Live pipeline"
    ratings_rows = _render_ratings(signals.get("ratings") or [])
    stage_cards = signals.get("stage_picks") or []
    disagreement_rows = _render_disagreement_rows(record.get("disagreements"))
    stage_rows = _render_stage_rows(stage_cards)
    stage_record_rows = _render_stage_record_rows(record.get("stage_records") or {})
    stage_summary = signals.get("stage_summary") or {}
    fade_n = stage_summary.get("fade_public_games", "—")
    rlm_n = stage_summary.get("rlm_games", "—")
    stage_highlights_html = _render_stage_highlight_lists(stage_summary)

    games_html = _render_games_pipeline(
        signals.get("games") or [],
        signals.get("split_boards") or [],
        stage_cards,
        signals.get("signals") or [],
        signals.get("ratings") or [],
    )

    ncaaf_pending = [p for p in ncaaf_ledger["plays"] if (p.get("status") or "pending") == "pending"]
    ncaaf_week_plays = filter_plays_college_week(ncaaf_pending)
    ncaaf_week_plays_sorted = sorted(
        collapse_best_signals(ncaaf_week_plays),
        key=lambda p: kickoff_sort_key(p.get("kickoff") or p.get("commence_time")),
    )
    ncaaf_plays_html = _render_play_cards(ncaaf_week_plays_sorted, live_fallback=[])
    ncaaf_stage_cards = _merge_stage_cards(
        ncaaf_ledger.get("stage_cards") or [],
        ncaaf_signals.get("stage_picks") or [],
        games=ncaaf_signals.get("games") or [],
        plays=ncaaf_ledger.get("plays") or [],
    )
    ncaaf_stage_cards = filter_stage_cards_current_slate(
        ncaaf_stage_cards,
        games=ncaaf_signals.get("games") or [],
    )
    ncaaf_stage_weeks_html = _render_stage_weeks_html(ncaaf_stage_cards)
    ncaaf_stage_record_rows = _render_stage_record_rows(ncaaf_record.get("stage_records") or {})
    ncaaf_stage_summary = ncaaf_signals.get("stage_summary") or {}
    ncaaf_fade_n = ncaaf_stage_summary.get("fade_public_games", "—")
    ncaaf_rlm_n = ncaaf_stage_summary.get("rlm_games", "—")
    ncaaf_ratings_rows = _render_ratings(ncaaf_signals.get("ratings") or [])
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

    html = SITE_TEMPLATE.format(
        generated=generated,
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
        ncaaf_ratings_rows=ncaaf_ratings_rows,
        ncaaf_demo_note="DEMO data" if ncaaf_signals.get("demo") else "Live pipeline",
        ncaaf_clv_banner_html=ncaaf_clv_banner_html,
        ncaaf_ledger_rows=ncaaf_ledger_rows,
        nfl_top_stats_html=nfl_top_stats_html,
        ncaaf_top_stats_html=ncaaf_top_stats_html,
        stage_alarm_stats_html=stage_alarm_stats_html,
        ncaaf_alarm_stats_html=ncaaf_alarm_stats_html,
        stage_records_thead=stage_records_thead,
        stage_record_section_note=_esc(STAGE_RECORD_SECTION_NOTE),
    )
    (out / "index.html").write_text(html)

    # CNAME placeholder not needed; add .nojekyll for GH Pages
    (out / ".nojekyll").write_text("")
    return out


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
        color = "#f4820a" if tier == "play" else "#facc15" if tier == "lean" else "#60a5fa"
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
    for p in sorted(plays, key=lambda x: x.get("created_at") or "", reverse=True):
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
        rows.append(
            f"<tr>"
            f"<td>{_esc((p.get('created_at') or '')[:10])}</td>"
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
        ("Hybrid", STAGE_COLUMN_TIPS.get("Hybrid")),
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
        if label == "Hybrid":
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


def _render_stage_weeks_html(cards: list[dict]) -> str:
    if not cards:
        return '<div class="empty">No stage picks yet. Run the NCAAF pipeline.</div>'
    parts: list[str] = []
    for week_start, week_cards in group_stage_cards_by_college_week(cards):
        label = college_week_label(week_start)
        sorted_cards = sorted(
            week_cards,
            key=lambda c: (
                kickoff_sort_key(c.get("kickoff") or c.get("commence_time") or c.get("created_at")),
                str(c.get("event_id") or ""),
                _STAGE_MARKET_ORDER.get(str(c.get("market") or "spread"), 9),
            ),
        )
        n_games = len({c.get("event_id") for c in sorted_cards})
        rows = _render_stage_rows(sorted_cards, sport="ncaaf")
        parts.append(
            f'<div class="week-block">'
            f'<div class="phase-sub" style="font-size:13px;margin-top:14px">{_esc(label)} · {n_games} games · {len(sorted_cards)} market rows</div>'
            f'<div class="table-wrap stage-table-wrap"><table class="stage-table">'
            f"{_render_stage_table_head()}<tbody>{rows}</tbody></table></div>"
            f'<p class="phase-note stage-scroll-hint">Three rows per game (spread, ML, total). '
            f"<b>Hybrid</b> is the system pick for that market — it can disagree with Model/Sharp/Public "
            f"when <b>Diff</b> (money vs tickets) confirms sharp action.</p></div>"
        )
    return "".join(parts)


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
<title>Sharp Scout — NFL</title>
<meta name="description" content="Sharp Scout NFL hybrid model plays and record">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }}
  .header {{ background: linear-gradient(135deg, #0d1b3e 0%, #1a2f5e 100%); padding: 20px 16px 16px; border-bottom: 3px solid #f4820a; }}
  .header h1 {{ font-size: 22px; font-weight: 800; color: #fff; }}
  .header p {{ color: #94a3b8; font-size: 13px; margin-top: 6px; }}
  .pill {{ display: inline-block; margin-top: 8px; background: #0d2a1a; border: 1px solid #4ade80; color: #4ade80; font-weight: 700; font-size: 12px; padding: 3px 10px; border-radius: 20px; }}
  .tabs {{ position: sticky; top: 0; z-index: 10; display: flex; background: #161b22; border-bottom: 1px solid #30363d; }}
  .tab {{ flex: 1; padding: 14px; text-align: center; cursor: pointer; color: #8b949e; font-size: 13px; font-weight: 600; border-bottom: 3px solid transparent; }}
  .tab.active {{ color: #f4820a; border-bottom-color: #f4820a; }}
  .content {{ display: none; padding: 16px; max-width: 900px; margin: 0 auto; }}
  .content.active {{ display: block; }}
  #tab-cfb.content {{ max-width: 1240px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 18px; }}
  @media (min-width: 700px) {{ .summary-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
  .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px 10px; text-align: center; }}
  .stat-val {{ font-size: 22px; font-weight: 800; }}
  .stat-label {{ font-size: 10px; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; display: inline-flex; align-items: center; justify-content: center; gap: 4px; flex-wrap: wrap; }}
  .stat-tip {{ margin-left: 2px; }}
  .stage-record-label {{ display: inline-flex; align-items: center; gap: 4px; }}
  .section-label {{ font-size: 10px; font-weight: 700; letter-spacing: 1.5px; color: #f4820a; text-transform: uppercase; margin: 18px 0 10px; }}
  .play-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 14px; margin-bottom: 10px; position: relative; overflow: hidden; }}
  .play-card::before {{ content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }}
  .sharp-play::before {{ background: #f4820a; }}
  .sharp-lean::before {{ background: #facc15; }}
  .candidate::before {{ background: #60a5fa; }}
  .card-top {{ display: flex; justify-content: space-between; gap: 8px; }}
  .tier-badge {{ display: inline-block; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 20px; margin-bottom: 4px; }}
  .badge-play {{ background: #f4820a; color: #fff; }}
  .badge-lean {{ background: #facc15; color: #000; }}
  .badge-cand {{ background: #60a5fa; color: #fff; }}
  .play-title {{ font-size: 18px; font-weight: 800; }}
  .play-subtitle {{ font-size: 11px; color: #8b949e; margin-top: 2px; }}
  .units-badge {{ background: #0d1b3e; border: 1px solid #f4820a; color: #f4820a; padding: 6px 12px; border-radius: 8px; font-weight: 800; height: fit-content; }}
  .card-result {{ display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; margin-top: 8px; }}
  .card-result.win {{ background: #0d2a1a; border: 1px solid #4ade80; color: #4ade80; }}
  .card-result.loss {{ background: #2a0d0d; border: 1px solid #f87171; color: #f87171; }}
  .card-result.pending {{ background: #1e2040; border: 1px solid #2d3a5c; color: #93c5fd; }}
  .play-meta {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin-top: 10px; font-size: 12px; }}
  .meta-label {{ color: #8b949e; }}
  .meta-val {{ font-weight: 600; }}
  .conf-track {{ background: #21262d; border-radius: 4px; height: 5px; margin-top: 10px; }}
  .conf-fill {{ height: 5px; border-radius: 4px; }}
  .rationale-toggle {{ margin-top: 10px; color: #8b949e; font-size: 12px; cursor: pointer; display: flex; gap: 6px; align-items: center; }}
  .rationale-toggle.open .arrow {{ transform: rotate(90deg); }}
  .rationale-body {{ display: none; font-size: 12px; color: #cbd5e1; margin-top: 8px; line-height: 1.65; border-top: 1px solid #21262d; padding-top: 8px; }}
  .rationale-body.open {{ display: block; }}
  .rationale-cell {{ font-size: 11px; color: #94a3b8; line-height: 1.5; max-width: 320px; }}
  .stage-why {{ font-size: 11px; color: #94a3b8; line-height: 1.5; max-width: 420px; }}
  .splits-summary {{ color: #e2e8f0; margin-bottom: 8px; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; }}
  .stage-table-wrap {{ margin-bottom: 8px; }}
  .stage-table {{ min-width: 880px; font-size: 11px; }}
  .stage-table th, .stage-table td {{ white-space: nowrap; padding: 6px 7px; }}
  .stage-table th:nth-child(2), .stage-table td:nth-child(2) {{ white-space: nowrap; min-width: 0; max-width: 108px; }}
  .stage-table th.hybrid-col, .stage-table td.hybrid-cell {{
    background: rgba(74, 222, 128, 0.08);
    border-left: 2px solid rgba(74, 222, 128, 0.35);
    border-right: 2px solid rgba(74, 222, 128, 0.35);
  }}
  .stage-table th:nth-child(11), .stage-table td:nth-child(11) {{
    white-space: normal; min-width: 72px; max-width: 120px; font-size: 11px; color: #94a3b8;
  }}
  .stage-scroll-hint {{ margin: 8px 2px 0; font-size: 11px; }}
  .stage-th {{ white-space: nowrap; }}
  .th-tip {{
    display: inline-flex;
    align-items: center;
    margin-left: 4px;
    cursor: pointer;
    vertical-align: middle;
    color: #6b7280;
    line-height: 0;
    position: relative;
  }}
  .th-tip:hover, .th-tip:focus {{ color: #93c5fd; outline: none; }}
  .th-tip:focus-visible {{ box-shadow: 0 0 0 2px #1d4ed8; border-radius: 4px; }}
  .th-tip-icon {{ display: block; pointer-events: none; }}
  .th-tip-float {{
    position: fixed;
    z-index: 10000;
    display: none;
    max-width: min(280px, calc(100vw - 16px));
    padding: 8px 10px;
    background: #1f2937;
    border: 1px solid #475569;
    border-radius: 8px;
    color: #e2e8f0;
    font-size: 12px;
    font-weight: 400;
    line-height: 1.45;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    pointer-events: none;
    white-space: normal;
    text-transform: none;
    letter-spacing: normal;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; min-width: 520px; }}
  th {{ background: #161b22; color: #8b949e; text-align: left; padding: 10px; border-bottom: 1px solid #30363d; }}
  td {{ padding: 9px 10px; border-bottom: 1px solid #21262d; }}
  .win {{ color: #4ade80; font-weight: 700; }}
  .loss {{ color: #f87171; font-weight: 700; }}
  .pending {{ color: #94a3b8; }}
  .pos {{ color: #4ade80; font-weight: 600; }}
  .neg {{ color: #f87171; font-weight: 600; }}
  .empty {{ color: #8b949e; text-align: center; padding: 28px 8px; }}
  .game-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 14px; margin-bottom: 14px; }}
  .game-head {{ margin-bottom: 10px; }}
  .game-title {{ font-size: 18px; font-weight: 800; }}
  .game-kick {{ font-size: 11px; color: #8b949e; margin-top: 4px; }}
  .phase-block {{ margin-top: 12px; border-top: 1px solid #21262d; padding-top: 10px; }}
  .phase-label {{ font-size: 10px; font-weight: 700; letter-spacing: 1px; color: #f4820a; text-transform: uppercase; margin-bottom: 6px; }}
  .phase-note {{ font-size: 12px; color: #94a3b8; margin: 4px 0; line-height: 1.5; }}
  .phase-sub {{ font-size: 11px; font-weight: 700; color: #8b949e; margin: 8px 0 4px; }}
  .footer {{ color: #4b5563; font-size: 11px; padding: 24px 16px; text-align: center; line-height: 1.6; }}
</style>
</head>
<body>
<div class="header">
  <h1>Sharp Scout</h1>
  <p>NFL + NCAAF hybrid model · ratings → Monte Carlo → sharp EV → split filter</p>
  <span class="pill">NFL {nfl_record} · {nfl_pnl}u · CFB {ncaaf_record} · {ncaaf_pnl}u · {ncaaf_demo_note}</span>
  <p style="margin-top:8px">Updated {generated}</p>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('plays', this)">NFL</div>
  <div class="tab" onclick="showTab('games', this)">Games</div>
  <div class="tab" onclick="showTab('stages', this)">Stages</div>
  <div class="tab" onclick="showTab('ratings', this)">Ratings</div>
  <div class="tab" onclick="showTab('cfb', this)">CFB</div>
</div>

<div id="tab-plays" class="content active">
  <div class="summary-grid">{nfl_top_stats_html}</div>
  <div class="section-label">Closing Line Value</div>
  {nfl_clv_banner_html}
  <div class="section-label">This Week's Plays · {nfl_signal_count} validated</div>
  {plays_html}
  <div class="section-label">NFL Ledger · {nfl_pending} pending · {nfl_n_plays} total</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Date</th><th>Game</th><th>Play</th><th>Units</th><th>Result</th><th>Score</th><th>CLV</th><th>PnL</th></tr></thead>
    <tbody>{nfl_ledger_rows}</tbody>
  </table></div>
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
  <p class="footer" style="padding:12px 0">Each column is an independent lens. <b>Hybrid</b> is the system pick per market — Sharp Plays come from validated Hybrid ML/spread/total rows.</p>
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
  <div class="section-label">NCAAF Pregame Stage Winners</div>
  <p class="phase-note" style="padding:4px 0 10px">Every game on the slate — three rows per game (spread, ML, total). <b>Hybrid</b> (green) is the system pick and matches Sharp Plays above when validated.</p>
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
    <thead><tr><th>Date</th><th>Game</th><th>Play</th><th>Units</th><th>Result</th><th>Score</th><th>CLV</th><th>PnL</th></tr></thead>
    <tbody>{ncaaf_ledger_rows}</tbody>
  </table></div>
  <div class="section-label">NCAAF Power Ratings</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Team</th><th>Power</th><th>Off EPA</th><th>Def EPA</th></tr></thead>
    <tbody>{ncaaf_ratings_rows}</tbody>
  </table></div>
</div>

<p class="footer">Signals only — no auto-betting. Data: nflverse · cfbfastR · The Odds API · Action Network.<br>
Source: ledger.json · record.json · ncaaf_ledger.json · ncaaf_record.json · latest signals</p>
<script>
function showTab(name, el) {{
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
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