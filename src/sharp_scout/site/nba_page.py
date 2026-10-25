"""Public GitHub Pages slice for NBA shadow / paper-trading (testing only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ROOT, get_settings
from sharp_scout.copy.explain import format_kickoff_compact, kickoff_sort_key
from sharp_scout.nba import paths as nba_paths
from sharp_scout.utils.slate import parse_commence

DOCS_DIR = ROOT / "docs"

NO_LIVE_SCAN_MESSAGE = (
    "No live NBA scan yet. Test plays will appear after the next scan."
)

NBA_PROP_LABELS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "3PM",
    "player_points_rebounds_assists": "PRA",
}

NBA_BOOK_LABELS = {
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
}


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


def _pct(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v * 100:.1f}%"


def _book_label(book: str | None) -> str:
    if not book:
        return "—"
    return NBA_BOOK_LABELS.get(str(book).lower(), str(book).replace("_", " ").title())


def _bet_type_label(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        market = str(play.get("market") or "prop")
        return NBA_PROP_LABELS.get(market, market.replace("player_", "").replace("_", " ").title())
    market = str(play.get("market") or "side")
    if market == "spreads":
        return "Spreads"
    if market == "totals":
        return "Totals"
    return market.title()


def _game_pick(play: dict[str, Any]) -> str:
    side = str(play.get("side") or "").lower()
    line = play.get("line")
    market = str(play.get("market") or "")
    away = str(play.get("away_team") or "")
    home = str(play.get("home_team") or "")
    if market == "spreads":
        team = away if side == "away" else home
        if isinstance(line, (int, float)):
            sign = "+" if float(line) > 0 else ""
            return f"{team} {sign}{line:g}"
        return team
    if market == "totals":
        label = "Over" if side == "over" else "Under"
        if isinstance(line, (int, float)):
            return f"{label} {line:g}"
        return label
    return side.title()


def _prop_pick(play: dict[str, Any]) -> str:
    side = str(play.get("side") or "").title()
    line = play.get("line")
    market = NBA_PROP_LABELS.get(str(play.get("market")), "Prop")
    if isinstance(line, (int, float)):
        return f"{side[0]} {line:g} {market}"
    return f"{side} {market}"


def _possible_lean_line(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        pick = _prop_pick(play)
    else:
        pick = _game_pick(play)
    book = _book_label(play.get("book"))
    price = _price(play.get("price"))
    return f"After more testing, we'd pick: {pick} ({book} {price})"


def _model_alignment_tag(play: dict[str, Any]) -> str:
    al = str(play.get("model_alignment") or "").lower()
    if al == "agree":
        return '<span class="nba-model-tag nba-model-agree">Agrees</span>'
    if al == "disagree":
        return '<span class="nba-model-tag nba-model-disagree">Disagrees</span>'
    if al == "neutral":
        return '<span class="nba-model-tag nba-model-neutral">Neutral</span>'
    return '<span class="nba-model-tag">—</span>'


def _render_score_model_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">No score-model projections yet (logged on live scans).</p>'
    body = []
    for r in rows:
        game = f"{r.get('away', '')} @ {r.get('home', '')}"
        score = f"{r.get('away_pts', '—')}-{r.get('home_pts', '—')}"
        lines = r.get("lines") or {}
        spr = lines.get("consensus_spread_home")
        tot = lines.get("consensus_total")
        body.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(r.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Proj score">{_esc(score)}</td>'
            f'<td data-label="Margin">{float(r.get("margin") or 0):+.1f}</td>'
            f'<td data-label="Total">{float(r.get("total") or 0):.1f}</td>'
            f'<td data-label="Consensus">{_esc(spr)} / {_esc(tot)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Game</th><th>Proj score</th><th>Margin</th><th>Total</th>"
        "<th>Consensus spr/tot</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_injury_lag_block(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<p class="empty">No open injury-lag leans.</p>'
    body = []
    for e in entries:
        body.append(
            "<tr>"
            f'<td data-label="When">{_esc(format_kickoff_compact(e.get("detected_at")))}</td>'
            f'<td data-label="Player">{_esc(e.get("player"))} ({_esc(e.get("team"))})</td>'
            f'<td data-label="Status">{_esc(e.get("status"))}</td>'
            f'<td data-label="Impact">{float(e.get("impact_pts") or 0):.1f} pts</td>'
            f'<td data-label="Expected move">{float(e.get("expected_move_pts") or 0):.1f}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>When</th><th>Player</th><th>Status</th><th>Impact</th><th>Expected move</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _market_label(play: dict[str, Any]) -> str:
    if play.get("play_type") == "prop":
        return NBA_PROP_LABELS.get(str(play.get("market")), str(play.get("market")))
    m = str(play.get("market") or "")
    return {"spreads": "Spread", "totals": "Total"}.get(m, m.title())


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _is_demo_play(play: dict[str, Any]) -> bool:
    from sharp_scout.nba.ledger import is_demo_nba_row

    return is_demo_nba_row(play)


def has_live_nba_scan(signals_payload: dict[str, Any] | None) -> bool:
    """True when the latest shadow scan is a non-demo live run (signals may still be empty)."""
    if not signals_payload:
        return False
    if signals_payload.get("demo"):
        return False
    return bool(signals_payload.get("ok", True))


def _empty_public_signals() -> dict[str, Any]:
    return {
        "ok": False,
        "demo": False,
        "generated_at": None,
        "n_events": 0,
        "n_signals": 0,
        "signals": [],
        "n_possible": 0,
        "possible_signals": [],
    }


def public_nba_signals(signals_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not has_live_nba_scan(signals_payload):
        return _empty_public_signals()
    out = dict(signals_payload or {})
    out["demo"] = False
    picks = [
        s
        for s in (out.get("signals") or [])
        if (s.get("pick_class") or "pick") != "possible"
        and not s.get("display_only")
        and not _is_demo_play(s)
    ]
    possible = [p for p in (out.get("possible_signals") or []) if not _is_demo_play(p)]
    from sharp_scout.nba.possible import cap_props_per_game

    picks, possible = cap_props_per_game(picks, possible)
    out["signals"] = picks
    out["n_signals"] = len(picks)
    out["possible_signals"] = possible
    out["n_possible"] = len(possible)
    return out


def public_nba_ledger(ledger: dict[str, Any] | None) -> dict[str, Any]:
    from sharp_scout.nba.ledger import empty_nba_ledger

    if not ledger:
        return empty_nba_ledger()
    plays = [p for p in ledger.get("plays") or [] if not _is_demo_play(p)]
    out = dict(ledger)
    out["plays"] = plays
    return out


def public_nba_report(
    report: dict[str, Any] | None,
    *,
    ledger: dict[str, Any] | None,
    live_scan: bool,
) -> dict[str, Any]:
    if not live_scan:
        settings = get_settings()
        return {
            "generated_at": None,
            "paper_window": {"start": settings.nba_paper_start, "end": settings.nba_paper_end},
            "in_window": False,
            "clv_summary": {},
            "calibration": [],
            "pass_fail": [],
            "n_plays": 0,
        }
    from sharp_scout.nba.report import build_paper_report

    return build_paper_report(public_nba_ledger(ledger))


def _record_by_bet_type(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    plays = (ledger or {}).get("plays") or []
    buckets: dict[str, dict[str, Any]] = {}

    def bucket(key: str) -> dict[str, Any]:
        if key not in buckets:
            buckets[key] = {
                "label": key,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "pending": 0,
                "pnl_units": 0.0,
                "clv_probs": [],
            }
        return buckets[key]

    for p in plays:
        label = _bet_type_label(p)
        b = bucket(label)
        st = str(p.get("status") or "paper").lower()
        if st == "win":
            b["wins"] += 1
        elif st == "loss":
            b["losses"] += 1
        elif st == "push":
            b["pushes"] += 1
        elif st in ("paper", "pending"):
            b["pending"] += 1
        if p.get("pnl_units") is not None:
            b["pnl_units"] += float(p["pnl_units"])
        if p.get("clv_prob") is not None:
            b["clv_probs"].append(float(p["clv_prob"]))

    out = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        graded = b["wins"] + b["losses"] + b["pushes"]
        wl = f"{b['wins']}-{b['losses']}"
        if b["pushes"]:
            wl += f"-{b['pushes']}"
        avg_clv = sum(b["clv_probs"]) / len(b["clv_probs"]) if b["clv_probs"] else None
        out.append(
            {
                "label": key,
                "record": wl if graded else "—",
                "graded": graded,
                "pending": b["pending"],
                "pnl_units": b["pnl_units"] if graded else None,
                "avg_clv_prob": avg_clv,
            }
        )
    return out


def _render_record_cards(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    cards = []
    for r in rows:
        pnl = r.get("pnl_units")
        pnl_s = "—"
        if pnl is not None:
            pnl_s = f"{pnl:+.2f}u"
        clv = r.get("avg_clv_prob")
        clv_s = _pct(clv) if clv is not None else "—"
        pending = int(r.get("pending") or 0)
        extra = f" · {pending} open" if pending else ""
        cards.append(
            '<div class="nba-rec-card">'
            f'<div class="nba-rec-lbl">{_esc(r["label"])}</div>'
            f'<div class="nba-rec-val">{_esc(r["record"])}</div>'
            f'<div class="nba-rec-sub">Units {pnl_s} · CLV {clv_s}{extra}</div>'
            "</div>"
        )
    return '<div class="nba-record-grid">' + "".join(cards) + "</div>"


def _render_possible_rows(rows: list[dict[str, Any]], *, kind: str) -> str:
    filtered = [s for s in rows if (s.get("play_type") or "side") == kind]
    filtered = sorted(filtered, key=lambda p: float(p.get("edge") or 0), reverse=True)
    if not filtered:
        return '<p class="empty">No near-miss game-line candidates right now.</p>' if kind != "prop" else (
            '<p class="empty">No near-miss prop candidates right now.</p>'
        )
    body = []
    for i, p in enumerate(filtered, 1):
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        player = str(p.get("player_name") or "—") if kind == "prop" else "—"
        lean = _possible_lean_line(p)
        reason = str(p.get("reject_reason") or "Did not qualify")
        meta = f"EV {_pct(p.get('edge'))} · {reason} · 0u (display only)"
        body.append(
            "<tr>"
            f'<td data-label="#">{i}</td>'
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Player">{_esc(player)}</td>'
            f'<td data-label="Tentative lean" class="nba-lean-cell">'
            f'<div class="nba-lean-main"><b>{_esc(lean)}</b></div>'
            f'<div class="nba-lean-meta">{_esc(meta)}</div></td>'
            "</tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Tip</th><th>Game</th><th>Player</th>"
        "<th>Tentative lean</th></tr></thead>"
    )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table nba-possible-table">'
        f"{head}<tbody>{''.join(body)}</tbody></table></div>"
    )


def _render_candidate_rows(signals: list[dict[str, Any]], *, kind: str) -> str:
    filtered = [s for s in signals if (s.get("play_type") or "side") == kind]
    filtered = sorted(filtered, key=lambda p: kickoff_sort_key(p.get("kickoff")))
    if not filtered:
        return (
            '<p class="empty">No qualifying picks right now.</p>'
            if kind != "prop"
            else '<p class="empty">No qualifying prop picks right now.</p>'
        )
    rows = []
    for i, p in enumerate(filtered, 1):
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        if kind == "prop":
            pick = _prop_pick(p)
            player = str(p.get("player_name") or "—")
        else:
            pick = _game_pick(p)
            player = "—"
        units = p.get("units")
        units_s = f"{float(units):.2f}u" if isinstance(units, (int, float)) else "—"
        fair = p.get("p_true") if p.get("p_true") is not None else p.get("p_fair")
        model_tag = _model_alignment_tag(p)
        rows.append(
            "<tr>"
            f'<td data-label="#">{i}</td>'
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Player">{_esc(player)}</td>'
            f'<td data-label="Market">{_esc(_market_label(p))}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Line">{_esc(p.get("line", "—"))}</td>'
            f'<td data-label="Book / price">{_esc(_price(p.get("price")))} '
            f'<span class="nba-book">{_esc(_book_label(p.get("book")))}</span></td>'
            f'<td data-label="EV">{_pct(p.get("edge"))}</td>'
            f'<td data-label="Fair %">{_pct(fair)}</td>'
            f'<td data-label="Units">{units_s}</td>'
            f'<td data-label="Model">{model_tag}</td>'
            "</tr>"
        )
    head = (
        "<thead><tr><th>#</th><th>Tip</th><th>Game</th><th>Player</th><th>Market</th>"
        "<th>Pick</th><th>Line</th><th>Book / price</th><th>EV</th><th>Fair %</th><th>Units</th>"
        "<th>Model</th>"
        "</tr></thead>"
    )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        f"{head}<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_ledger_rows(ledger: dict[str, Any] | None) -> str:
    plays = (ledger or {}).get("plays") or []
    graded = [p for p in plays if str(p.get("status") or "").lower() in ("win", "loss", "push")]
    graded = sorted(graded, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    if not graded:
        return '<p class="empty">No graded paper plays yet. Records appear after games finish and settle.</p>'
    rows = []
    for p in graded:
        game = f"{p.get('away_team', '')} @ {p.get('home_team', '')}"
        pick = _prop_pick(p) if p.get("play_type") == "prop" else _game_pick(p)
        pnl = p.get("pnl_units")
        pnl_s = f"{float(pnl):+.2f}u" if pnl is not None else "—"
        clv = p.get("clv_prob")
        rows.append(
            "<tr>"
            f'<td data-label="Tip">{_esc(format_kickoff_compact(p.get("kickoff")))}</td>'
            f'<td data-label="Type">{_esc(_bet_type_label(p))}</td>'
            f'<td data-label="Game">{_esc(game)}</td>'
            f'<td data-label="Pick"><b>{_esc(pick)}</b></td>'
            f'<td data-label="Result">{_esc(str(p.get("status") or "").upper())}</td>'
            f'<td data-label="P/L">{pnl_s}</td>'
            f'<td data-label="CLV">{_pct(clv) if clv is not None else "—"}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="export-table plays-table nba-table">'
        "<thead><tr><th>Tip</th><th>Type</th><th>Game</th><th>Pick</th><th>Result</th>"
        "<th>P/L</th><th>CLV</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_nba_page_html(
    *,
    signals_payload: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    report: dict[str, Any] | None,
    analytics_head: str,
    score_model_rows: list[dict[str, Any]] | None = None,
    injury_lag_rows: list[dict[str, Any]] | None = None,
) -> str:
    from sharp_scout.site.bottom_bar import BOTTOM_BAR_SCRIPT, bottom_bar_css, render_bottom_bar
    from sharp_scout.site.build import _SITE_CSS, _format_timestamp_et, _ssq_logo_svg

    live_scan = has_live_nba_scan(signals_payload)
    pub_signals = public_nba_signals(signals_payload)
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    picks = list(pub_signals.get("signals") or [])
    possible = list(pub_signals.get("possible_signals") or [])
    generated = parse_commence(pub_signals.get("generated_at"))
    updated = _format_timestamp_et(generated) if generated else "—"
    n_game = len([s for s in picks if (s.get("play_type") or "side") != "prop"])
    n_prop = len([s for s in picks if (s.get("play_type") or "") == "prop"])
    n_possible_game = len([s for s in possible if (s.get("play_type") or "side") != "prop"])
    n_possible_prop = len([s for s in possible if (s.get("play_type") or "") == "prop"])

    empty_live_notice = ""
    body_class = "ss-bottom-bar"
    if not live_scan:
        body_class = "ss-bottom-bar nba-no-live-scan"
        empty_live_notice = (
            f'<div class="nba-empty-live" role="status">{_esc(NO_LIVE_SCAN_MESSAGE)}</div>'
        )
        game_picks_table = ""
        game_possible_table = ""
        prop_picks_table = ""
        prop_possible_table = ""
        mode_note = "Awaiting live scan"
    else:
        game_picks_table = _render_candidate_rows(picks, kind="side")
        game_possible_table = _render_possible_rows(possible, kind="side")
        prop_picks_table = _render_candidate_rows(picks, kind="prop")
        prop_possible_table = _render_possible_rows(possible, kind="prop")
        mode_note = "Live shadow scan"

    record_rows = _record_by_bet_type(pub_ledger)
    record_block = _render_record_cards(record_rows)
    if not record_block:
        record_block = (
            '<p class="empty">No paper ledger yet. Run the NBA shadow scan to log test plays.</p>'
        )
    ledger_table = _render_ledger_rows(pub_ledger)
    score_block = _render_score_model_block(score_model_rows or []) if live_scan else ""
    injury_block = _render_injury_lag_block(injury_lag_rows or []) if live_scan else ""
    mf = pub_report.get("model_filter") or {}
    mf_bits = []
    for key in ("agree", "disagree", "neutral"):
        row = mf.get(key)
        if row and row.get("n"):
            mf_bits.append(f"{key}: {row.get('record')} ({row.get('units')}u)")
    model_filter_note = " · ".join(mf_bits) if mf_bits else "Model filter splits appear after graded side/total plays."

    in_window = pub_report.get("in_window")
    window = pub_report.get("paper_window") or {}
    window_s = ""
    if window.get("start") and window.get("end"):
        window_s = f"Paper window {window['start']} – {window['end']}. "
    window_flag = "In paper window." if in_window else "Outside paper window (testing only)."

    return NBA_PAGE_TEMPLATE.format(
        site_css=_SITE_CSS,
        bottom_bar_css=bottom_bar_css(),
        analytics_head=analytics_head,
        ssq_logo=_ssq_logo_svg(embedded=True),
        body_class=body_class,
        updated=_esc(updated),
        mode_note=_esc(mode_note),
        n_game=n_game,
        n_prop=n_prop,
        n_possible_game=n_possible_game,
        n_possible_prop=n_possible_prop,
        empty_live_notice=empty_live_notice,
        game_picks_table=game_picks_table,
        game_possible_table=game_possible_table,
        prop_picks_table=prop_picks_table,
        prop_possible_table=prop_possible_table,
        record_block=record_block,
        ledger_table=ledger_table,
        score_model_block=score_block,
        injury_lag_block=injury_block,
        model_filter_note=_esc(model_filter_note),
        window_note=_esc(window_s + window_flag),
        bottom_bar=render_bottom_bar(active="plays"),
        bottom_bar_script=BOTTOM_BAR_SCRIPT,
    )


def build_nba_page(*, docs_dir: Path | None = None) -> Path | None:
    """Write docs/nba.html and shadow JSON copies. Does not touch football artifacts."""
    out = docs_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    signals_payload = _load_json(nba_paths.NBA_LATEST_SIGNALS_PATH)
    ledger = _load_json(nba_paths.NBA_LEDGER_PATH)
    report = _load_json(nba_paths.NBA_REPORT_PATH)
    live_scan = has_live_nba_scan(signals_payload)

    pub_signals = public_nba_signals(signals_payload)
    pub_ledger = public_nba_ledger(ledger)
    pub_report = public_nba_report(report, ledger=ledger, live_scan=live_scan)

    (out / "nba_latest_signals.json").write_text(
        json.dumps(pub_signals, indent=2, default=str) + "\n"
    )
    (out / "nba_ledger.json").write_text(json.dumps(pub_ledger, indent=2, default=str) + "\n")
    (out / "nba_paper_report.json").write_text(
        json.dumps(pub_report, indent=2, default=str) + "\n"
    )
    for src_name in ("nba_score_model.json", "nba_injury_lag.json"):
        src = nba_paths.PAPER_DIR / src_name
        if src.exists():
            (out / src_name).write_text(src.read_text())

    from sharp_scout.site.build import _render_analytics_head

    score_model_rows: list[dict[str, Any]] = []
    injury_lag_rows: list[dict[str, Any]] = []
    if live_scan:
        try:
            from sharp_scout.nba.score_model.injury_lag import open_entries_for_page
            from sharp_scout.nba.score_model.paper import slate_projections_for_page

            score_model_rows = slate_projections_for_page()
            injury_lag_rows = open_entries_for_page()
        except Exception:  # noqa: BLE001
            pass

    html = render_nba_page_html(
        signals_payload=signals_payload,
        ledger=ledger,
        report=report,
        analytics_head=_render_analytics_head(get_settings().ga_measurement_id),
        score_model_rows=score_model_rows,
        injury_lag_rows=injury_lag_rows,
    )
    (out / "nba.html").write_text(html)
    return out / "nba.html"


NBA_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NBA (testing) · Sharp Scout Quant</title>
<meta name="description" content="NBA game lines and player props — paper testing only">
<link rel="icon" type="image/svg+xml" href="assets/ssq-logo.svg">
<link rel="apple-touch-icon" href="assets/ssq-logo.svg">
{analytics_head}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Inconsolata:wght@400;500;600&family=Karla:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{site_css}
{bottom_bar_css}
  .nba-wrap {{ max-width: 1200px; margin: 0 auto; padding: 0 20px 48px; }}
  .nba-test-banner {{
    background: #fef3c7; border: 2px solid #d97706; color: #92400e;
    text-align: center; font-weight: 800; font-size: 16px; padding: 14px 16px; margin: 0;
  }}
  .nba-hero {{ text-align: center; padding: 24px 16px 8px; }}
  .nba-hero h1 {{ font-family: var(--font-serif); font-size: 38px; font-weight: 500; margin: 10px 0 4px; }}
  .nba-hero p {{ color: var(--color-text-muted); font-size: 14px; font-weight: 300; }}
  .nba-note {{ font-size: 13px; color: var(--color-text-muted); margin: 8px 0 20px; line-height: 1.55; }}
  .nba-h2 {{ font-family: var(--font-serif); font-size: 24px; font-weight: 500; margin: 28px 0 8px; }}
  .nba-h3 {{ font-family: var(--font-mono); font-size: 12px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: var(--color-text-muted); margin: 18px 0 8px; }}
  .nba-section-note {{ font-size: 12.5px; color: var(--color-text-muted); margin: 0 0 10px; line-height: 1.5; }}
  .nba-display-only {{ color: var(--color-text-muted); font-size: 12px; font-weight: 600; }}
  .nba-lean-cell {{ max-width: 520px; }}
  .nba-lean-main {{ font-size: 14px; line-height: 1.45; margin-bottom: 4px; }}
  .nba-lean-meta {{ font-size: 12px; color: var(--color-text-muted); line-height: 1.4; }}
  .nba-book {{ font-family: var(--font-mono); font-size: 11px; color: var(--color-text-muted); }}
  .nba-record-grid {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; margin: 16px 0; }}
  .nba-rec-card {{ border: 1px solid var(--color-border); border-radius: 8px; padding: 12px 16px; min-width: 140px; text-align: center; }}
  .nba-rec-lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--color-text-muted); }}
  .nba-rec-val {{ font-size: 22px; font-weight: 800; margin: 4px 0; }}
  .nba-rec-sub {{ font-size: 11px; color: var(--color-text-muted); }}
  .nba-wrap .table-wrap {{ overflow-x: auto; }}
  .nba-empty-live {{
    border: 2px solid var(--color-border); background: var(--color-bg);
    text-align: center; font-size: 15px; font-weight: 600; padding: 20px 16px; margin: 16px 0;
  }}
  .nba-no-live-scan .nba-candidates {{ display: none; }}
  .nba-model-tag {{ font-size: 11px; font-weight: 700; padding: 2px 6px; border-radius: 4px; }}
  .nba-model-agree {{ background: #dcfce7; color: #166534; }}
  .nba-model-disagree {{ background: #fee2e2; color: #991b1b; }}
  .nba-model-neutral {{ background: #f3f4f6; color: #374151; }}
  @media (max-width: 640px) {{ .nba-hero h1 {{ font-size: 29px; }} }}
</style>
</head>
<body class="{body_class}">
<div class="nba-test-banner" role="alert">This is just for testing.</div>
<div class="tabs" role="navigation" aria-label="Sections">
  <a class="tab tab-home" href="index.html">Today's plays</a>
  <a class="tab" href="board.html#tab-plays">Results</a>
  <a class="tab" href="board.html#tab-guide">How it works</a>
  <a class="tab tab-aux" href="comments.html">Comments</a>
  <a class="tab tab-aux" href="props.html">NFL Props</a>
  <span class="tab active">NBA (test)</span>
</div>
<div class="nba-wrap">
  <div class="nba-hero">
    {ssq_logo}
    <h1>NBA — paper testing</h1>
    <p>{mode_note} · {n_game} line picks · {n_prop} prop picks · {n_possible_game}+{n_possible_prop} possible · updated {updated}</p>
  </div>
  <p class="nba-note">
    Paper/test plays only — not Sharp Plays, not on the NFL card, and not graded on football records.
    {window_note}
    EV uses quarter-Kelly staking with caps ($10/unit). Retail books: FanDuel first, then DraftKings.
  </p>
  {empty_live_notice}
  <h2 class="nba-h2">Paper record by bet type</h2>
  {record_block}
  <p class="nba-section-note">Price-gap plays vs score model (side-by-side): {model_filter_note}</p>
  <h2 class="nba-h2">Score model paper track</h2>
  <p class="nba-section-note">Stage-3 possession ridge projections vs consensus/Pinnacle — frozen at tip, graded after ESPN finals.</p>
  {score_model_block}
  <h2 class="nba-h2">Injury lag (paper)</h2>
  <p class="nba-section-note">ESPN Out/Doubtful changes where the line may not have fully adjusted yet.</p>
  {injury_lag_block}
  <div class="nba-candidates">
  <h2 class="nba-h2">Game lines</h2>
  <h3 class="nba-h3">Picks</h3>
  <p class="nba-section-note">Qualifying paper plays (EV floor, sharp fair, Kelly sizing, and portfolio caps).</p>
  {game_picks_table}
  <h3 class="nba-h3">Possible picks</h3>
  <p class="nba-section-note">Tentative leans with positive EV that did not fully qualify yet. Not logged or graded.</p>
  {game_possible_table}
  <h2 class="nba-h2">Player props</h2>
  <h3 class="nba-h3">Picks</h3>
  <p class="nba-section-note">Qualifying paper props that pass model, consensus, and staking rules.</p>
  {prop_picks_table}
  <h3 class="nba-h3">Possible picks</h3>
  <p class="nba-section-note">Tentative prop leans — display only until they pass all rules.</p>
  {prop_possible_table}
  </div>
  <h2 class="nba-h2">Graded paper ledger</h2>
  {ledger_table}
</div>
<div class="footer">
  Sharp Scout Quant · research and entertainment only · not betting advice.
</div>
{bottom_bar}
{bottom_bar_script}
</body>
</html>
"""
