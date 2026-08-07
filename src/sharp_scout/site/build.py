"""Build static GitHub Pages site from ledger + latest signals."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import ARTIFACTS_DIR, ROOT
from sharp_scout.ledger.tracker import compute_record, load_ledger

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


def _side_label(p: dict[str, Any]) -> str:
    line = p.get("line")
    line_s = ""
    if line is not None:
        line_s = f" {float(line):+g}" if float(line) != 0 else " 0"
    m = {"spreads": "spread", "totals": "total", "h2h": "ML"}.get(p.get("market"), p.get("market"))
    return f"{str(p.get('side', '')).upper()}{line_s} ({m}) {_price(p.get('price'))}"


def _status_badge(status: str) -> str:
    st = status or "pending"
    cls = {"win": "win", "loss": "loss", "push": "pending", "pending": "pending", "void": "pending"}.get(st, "pending")
    label = {"win": "WIN", "loss": "LOSS", "push": "PUSH", "pending": "PENDING", "void": "VOID"}.get(st, st.upper())
    return f'<span class="card-result {cls}">{label}</span>'


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

    pending = [p for p in ledger["plays"] if (p.get("status") or "pending") == "pending"]
    settled = [p for p in ledger["plays"] if (p.get("status") or "pending") != "pending"]
    settled_sorted = sorted(settled, key=lambda p: p.get("settled_at") or p.get("created_at") or "", reverse=True)
    pending_sorted = sorted(pending, key=lambda p: p.get("created_at") or "", reverse=True)

    # Prefer live validated signals for "this week" board if present
    live_plays = signals.get("plays") or []

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    win_pct = f"{record['win_pct'] * 100:.1f}%" if record["win_pct"] is not None else "—"
    pnl = record["pnl_units"]
    pnl_cls = "pos" if pnl >= 0 else "neg"
    pnl_s = f"+{pnl}" if pnl >= 0 else str(pnl)

    plays_html = _render_play_cards(pending_sorted, live_fallback=live_plays)
    ledger_rows = _render_ledger_rows(settled_sorted + pending_sorted)
    week_rows = _render_week_rows(record.get("by_week") or {})
    ratings_rows = _render_ratings(signals.get("ratings") or [])

    html = SITE_TEMPLATE.format(
        generated=generated,
        record=record["record"],
        win_pct=win_pct,
        pnl=pnl_s,
        pnl_cls=pnl_cls,
        bankroll=record["bankroll_units"],
        pending=record["pending"],
        n_plays=record["n_plays"],
        plays_html=plays_html,
        ledger_rows=ledger_rows,
        week_rows=week_rows,
        ratings_rows=ratings_rows,
        demo_note="DEMO data" if signals.get("demo") else "Live pipeline",
    )
    (out / "index.html").write_text(html)

    # CNAME placeholder not needed; add .nojekyll for GH Pages
    (out / ".nojekyll").write_text("")
    return out


def _render_play_cards(pending: list[dict], live_fallback: list[dict]) -> str:
    source = pending if pending else live_fallback
    if not source:
        return '<div class="empty">No open plays. Run the pipeline to generate signals.</div>'

    # If using live_fallback (not yet in ledger), shape lightly
    cards = []
    for p in source:
        if "filter_passed" in p and not p.get("status"):
            # live signal shape
            tier = p.get("tier") or "lean"
            status_html = '<span class="card-result pending">OPEN</span>'
            title = _side_label(p)
            sub = f"{p.get('away_team')} @ {p.get('home_team')} · {p.get('book')}"
            edge = p.get("edge")
            units = {"play": 1.5, "lean": 1.0}.get(tier, 0.5)
            rationale = p.get("rationale") or ""
            meta_edge = f"{(edge or 0) * 100:.1f}%" if edge is not None else "—"
        else:
            tier = p.get("tier") or "lean"
            status_html = _status_badge(p.get("status") or "pending")
            title = _side_label(p)
            sub = f"{p.get('away_team')} @ {p.get('home_team')} · {p.get('book')}"
            if p.get("home_score") is not None:
                sub += f" · Final {p.get('away_team')} {p.get('away_score')}, {p.get('home_team')} {p.get('home_score')}"
            edge = p.get("edge")
            units = p.get("units") or 1
            rationale = p.get("rationale") or ""
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
        <div class="rationale-body">{_esc(rationale)}</div>
      </div>"""
        )
    return "\n".join(cards)


def _render_ledger_rows(plays: list[dict]) -> str:
    if not plays:
        return "<tr><td colspan='7'>No plays in ledger yet.</td></tr>"
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
            f"<td class='{pnl_cls}'>{pnl_s}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


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
  .summary-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 18px; }}
  @media (min-width: 700px) {{ .summary-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
  .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 14px 10px; text-align: center; }}
  .stat-val {{ font-size: 22px; font-weight: 800; }}
  .stat-label {{ font-size: 10px; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
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
  .rationale-body {{ display: none; font-size: 12px; color: #94a3b8; margin-top: 8px; line-height: 1.6; border-top: 1px solid #21262d; padding-top: 8px; }}
  .rationale-body.open {{ display: block; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; min-width: 520px; }}
  th {{ background: #161b22; color: #8b949e; text-align: left; padding: 10px; border-bottom: 1px solid #30363d; }}
  td {{ padding: 9px 10px; border-bottom: 1px solid #21262d; }}
  .win {{ color: #4ade80; font-weight: 700; }}
  .loss {{ color: #f87171; font-weight: 700; }}
  .pending {{ color: #94a3b8; }}
  .pos {{ color: #4ade80; font-weight: 600; }}
  .neg {{ color: #f87171; font-weight: 600; }}
  .empty {{ color: #8b949e; text-align: center; padding: 28px 8px; }}
  .footer {{ color: #4b5563; font-size: 11px; padding: 24px 16px; text-align: center; line-height: 1.6; }}
</style>
</head>
<body>
<div class="header">
  <h1>Sharp Scout</h1>
  <p>NFL hybrid model · ratings → Monte Carlo → sharp EV → split filter</p>
  <span class="pill">{record} · {pnl}u · {demo_note}</span>
  <p style="margin-top:8px">Updated {generated}</p>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('plays', this)">Plays</div>
  <div class="tab" onclick="showTab('ledger', this)">Ledger</div>
  <div class="tab" onclick="showTab('ratings', this)">Ratings</div>
</div>

<div id="tab-plays" class="content active">
  <div class="summary-grid">
    <div class="stat-card"><div class="stat-val">{record}</div><div class="stat-label">Record</div></div>
    <div class="stat-card"><div class="stat-val">{win_pct}</div><div class="stat-label">Win %</div></div>
    <div class="stat-card"><div class="stat-val {pnl_cls}">{pnl}u</div><div class="stat-label">Profit</div></div>
    <div class="stat-card"><div class="stat-val">{bankroll}u</div><div class="stat-label">Bankroll</div></div>
  </div>
  <div class="section-label">Open / Latest Plays · {pending} pending · {n_plays} total</div>
  {plays_html}
</div>

<div id="tab-ledger" class="content">
  <div class="section-label">By Week</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Week</th><th>Record</th><th>Pending</th><th>PnL</th></tr></thead>
    <tbody>{week_rows}</tbody>
  </table></div>
  <div class="section-label">All Plays</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Date</th><th>Game</th><th>Play</th><th>Units</th><th>Result</th><th>Score</th><th>PnL</th></tr></thead>
    <tbody>{ledger_rows}</tbody>
  </table></div>
</div>

<div id="tab-ratings" class="content">
  <div class="section-label">Power Ratings</div>
  <div class="table-wrap"><table>
    <thead><tr><th>Team</th><th>Power</th><th>Off EPA</th><th>Def EPA</th></tr></thead>
    <tbody>{ratings_rows}</tbody>
  </table></div>
</div>

<p class="footer">Signals only — no auto-betting. Data: nflverse · The Odds API · Action Network.<br>
Source: ledger.json · record.json</p>
<script>
function showTab(name, el) {{
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
}}
</script>
</body>
</html>
"""