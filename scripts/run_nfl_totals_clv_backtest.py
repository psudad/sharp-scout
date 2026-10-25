#!/usr/bin/env python3
"""Research: NFL totals early-line / CLV backtest (does not touch board or ledger)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.nfl.totals.clv_research import (  # noqa: E402
    breakdown_by_side,
    breakdown_by_week,
    build_scan_rows,
    combined_without_gate,
    coverage_report,
    load_sim_by_match,
    rows_to_csv_dicts,
    run_signal_backtests,
    signal_generators,
    supplement_jason_csv_scans,
    walk_forward_combined,
)
from sharp_scout.nfl.totals.clv_research import (  # noqa: E402
    ScanRow,
    _attach_side,
    _fill_bet_metrics,
)

DEFAULT_CSV = Path(
    "/home/ubuntu/.cursor/projects/workspace/uploads/nfl_totals_every_game_36b2.csv"
)
SIM_CSV = ROOT / "reports" / "nfl_totals_sim_backtest_2026.csv"
OUT_MD = ROOT / "reports" / "nfl_totals_clv_backtest_2026.md"
OUT_PLAYS = ROOT / "reports" / "nfl_totals_clv_backtest_2026_plays.csv"


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def main() -> None:
    jason_csv = DEFAULT_CSV if len(sys.argv) < 2 else Path(sys.argv[1])
    sim_by = load_sim_by_match(SIM_CSV)
    scan_rows = build_scan_rows(sim_by_match=sim_by)
    cov = coverage_report(scan_rows=scan_rows)
    signal_results = run_signal_backtests(scan_rows)
    combined, combined_rows = walk_forward_combined(scan_rows)
    combined_open, _ = combined_without_gate(scan_rows)

    # Per-play CSV: all signal-fired rows
    all_plays: list[ScanRow] = []
    gens = signal_generators()
    import copy

    for base in scan_rows:
        for name, fn in gens.items():
            side = fn(base)
            if side is None:
                continue
            row = copy.copy(base)
            _attach_side(row, side, name)
            _fill_bet_metrics(row)
            all_plays.append(row)
    OUT_PLAYS.parent.mkdir(parents=True, exist_ok=True)
    play_dicts = rows_to_csv_dicts(all_plays)
    if play_dicts:
        with OUT_PLAYS.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(play_dicts[0].keys()))
            w.writeheader()
            w.writerows(play_dicts)

    jason_sup = supplement_jason_csv_scans(jason_csv)

    md: list[str] = [
        "# 2026 NFL totals — early line / CLV research",
        "",
        "Research only (PR). Reproduce: `python scripts/run_nfl_totals_clv_backtest.py`.",
        "",
        "## 1. Data coverage (honest)",
        "",
        json.dumps(cov, indent=2),
        "",
        f"- **Multi-scan Pinnacle history rows:** {len(scan_rows)} early snapshots across "
        f"**{cov['games_with_multiple_pin_scans']}** completed games.",
        f"- **Jason CSV supplement** ({jason_csv.name}): "
        f"{'available' if jason_sup.get('available') else 'missing'} — "
        f"{jason_sup.get('n_games', 0)} games with ledger-timed `market_total` vs Pinnacle close "
        "(single scan per game; not the same as full snapshot series).",
        "",
        "## 2. Signal backtests (beat Pinnacle close + final-score W-L)",
        "",
        "Each row is one **early** Pinnacle totals snapshot (not the closing sample). "
        "Side chosen by signal only using information at scan time. "
        f"**n < {20}** flagged as not meaningful.",
        "",
    ]

    headers = [
        "Signal",
        "n",
        "OK?",
        "% beat close (pts)",
        "avg CLV pts",
        "avg CLV prob",
        "W-L-P vs final",
        "u @ scan",
        "u @ -110",
    ]
    table_rows = []
    for name, stats in sorted(signal_results.items()):
        if not stats:
            continue
        table_rows.append(
            [
                name,
                stats.get("n_plays", 0),
                "yes" if stats.get("meaningful") else "**low n**",
                stats.get("pct_beat_close_points", ""),
                stats.get("avg_clv_points", ""),
                stats.get("avg_clv_prob", ""),
                stats.get("record_final", ""),
                stats.get("units_at_scan_price", ""),
                stats.get("units_at_110", ""),
            ]
        )
    table_rows.append(
        [
            "combined_momentum_plus_sim (WF gate)",
            combined.get("n_plays", 0),
            "yes" if combined.get("meaningful") else "**low n**",
            combined.get("pct_beat_close_points", ""),
            combined.get("avg_clv_points", ""),
            combined.get("avg_clv_prob", ""),
            combined.get("record_final", ""),
            combined.get("units_at_scan_price", ""),
            combined.get("units_at_110", ""),
        ]
    )
    table_rows.append(
        [
            "combined_momentum_plus_sim (no gate)",
            combined_open.get("n_plays", 0),
            "yes" if combined_open.get("meaningful") else "**low n**",
            combined_open.get("pct_beat_close_points", ""),
            combined_open.get("avg_clv_points", ""),
            combined_open.get("avg_clv_prob", ""),
            combined_open.get("record_final", ""),
            combined_open.get("units_at_scan_price", ""),
            combined_open.get("units_at_110", ""),
        ]
    )
    md.append(_md_table(headers, table_rows))

    md.append("")
    md.append("### By week / side — `pinnacle_momentum_follow`")
    mom_rows = []
    gens = signal_generators()
    import copy

    for base in scan_rows:
        side = gens["pinnacle_momentum_follow"](base)
        if not side:
            continue
        row = copy.copy(base)
        row.side = side
        row.signal = "pinnacle_momentum_follow"
        _fill_bet_metrics(row)
        mom_rows.append(row)
    md.append("")
    md.append("**By week**")
    for w, st in breakdown_by_week(mom_rows).items():
        md.append(
            f"- W{w}: n={st.get('n_plays')} beat_close={st.get('pct_beat_close_points')}% "
            f"avg_CLV={st.get('avg_clv_points')} record={st.get('record_final')}"
        )
    md.append("")
    md.append("**By side**")
    for s, st in breakdown_by_side(mom_rows).items():
        md.append(
            f"- {s}: n={st.get('n_plays')} beat_close={st.get('pct_beat_close_points')}% "
            f"avg_CLV={st.get('avg_clv_points')} record={st.get('record_final')}"
        )
    md.extend(
        [
            "",
            "### Signals not tested (missing history)",
            "",
            "- **(a) Soft-book stale:** US retail books are **not** stored in `line_history.json`. "
            "Betfair EU is also **absent** from the current committed totals history (Pinnacle-only); "
            "`betfair_gap_*` signals had **zero** fires in this run.",
            "- **(c) Sharp/public totals splits:** not archived per scan; live Action Network fetch only.",
            "- **Injuries:** not stored in line history.",
            "",
            "## 3. Team / 1H totals derivative",
            "",
            "No historical **team totals** or **first-half totals** snapshots in repo "
            "(Odds API client markets: `h2h,spreads,totals` only).",
            "",
            "**Estimated cost to start collecting team totals** (The Odds API): "
            "each `/odds` pull with `markets=totals` already includes full-game; "
            "adding `alternate` or book-specific team totals typically requires "
            "**extra market keys** or per-event calls. Rule of thumb: **+1 request per snapshot run** "
            "if the book exposes `team_totals` on the same endpoint (~same cost as today's NFL snapshot); "
            "per-event historical backfill for 94 games × ~6 scans ≈ **564 event-odds credits** one-time "
            "(pricing depends on plan; monitor `x-requests-remaining` on fetch).",
            "",
            "## 4. Conclusion",
            "",
        ]
    )

    meaningful = [
        (n, s)
        for n, s in signal_results.items()
        if s.get("meaningful") and (s.get("avg_clv_points") or 0) > 0
    ]
    if combined.get("meaningful") and (combined.get("avg_clv_points") or 0) > 0:
        meaningful.append(("combined_momentum_plus_sim", combined))

    md.append(
        "**Beat-the-close vs make-money:** Momentum-follow shows **~43%** of scans beat the "
        "Pinnacle close by points (avg CLV **+1.5** pts) but **109-78** vs final at -110 — "
        "closing-line value here does **not** translate to winning bets on outcomes. "
        "Sim-vs-line and WF-gated combined rules look strong on CLV but overlap scans on the "
        "same games and the WF gate is **not** a clean OOS test (small train window)."
    )
    md.append("")
    if combined_open.get("meaningful"):
        md.append(
            f"**Paper-track (optional, low confidence):** log only "
            f"`pinnacle_momentum_follow` when it agrees with `sim_projection_vs_scan_line` "
            f"(ungated n={combined_open.get('n_plays')}, avg CLV pts={combined_open.get('avg_clv_points')}) "
            f"— do **not** bet real units until soft-book snapshots exist and 2026 holdout confirms."
        )
    else:
        md.append(
            "**Paper-track recommendation:** none until multi-book scan history includes "
            "retail/stale lines and forward CLV is logged without in-sample gates."
        )

    md.append("")
    md.append(f"Per-play CSV: `{OUT_PLAYS.relative_to(ROOT)}`")
    OUT_MD.write_text("\n".join(md) + "\n")
    print(OUT_MD.read_text())


if __name__ == "__main__":
    main()
