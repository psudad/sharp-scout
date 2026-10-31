#!/usr/bin/env python3
"""Compare push-aware EV before/after fix for NCAAF whole-number pending plays."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sharp_scout.ledger.tracker import load_ledger  # noqa: E402
from sharp_scout.phase2.monte_carlo import _is_whole  # noqa: E402
from sharp_scout.utils.odds import expected_value, expected_value_with_push  # noqa: E402


def _edge_after_fix(market: str, side: str, line: float | None, p_true: float, price: float, p_push: float) -> float:
    if market == "spreads" and _is_whole(line) and side == "home":
        return expected_value(p_true, price)
    if market in ("spreads", "totals") and _is_whole(line):
        return expected_value_with_push(p_true, price, p_push)
    return expected_value(p_true, price)


def _edge_before_fix(p_true: float, price: float, p_push: float, *, market: str, line: float | None) -> float:
    if market in ("spreads", "totals") and _is_whole(line):
        return expected_value(p_true, price) + p_push
    return expected_value(p_true, price)


def main() -> None:
    ledger = load_ledger(ROOT / "data" / "ncaaf_ledger.json")
    rows: list[dict] = []
    for p in ledger.get("plays") or []:
        if (p.get("status") or "") != "pending":
            continue
        if p.get("sport") not in (None, "ncaaf"):
            continue
        market = p.get("market")
        line = p.get("line")
        if market not in ("spreads", "totals") or not _is_whole(line):
            continue
        p_true = p.get("p_true")
        if p_true is None:
            continue
        price = float(p.get("price") or -110)
        side = p.get("side")
        # Reconstruct push from stored edge if possible: old = ev(p_true)+p_push on whole lines
        ledger_ev = float(p.get("edge") or 0)
        ev_before = _edge_before_fix(float(p_true), price, max(0.0, ledger_ev - expected_value(float(p_true), price)), market=market, line=line)
        if market in ("spreads", "totals") and _is_whole(line):
            p_push = max(0.0, ledger_ev - expected_value(float(p_true), price))
        else:
            p_push = 0.0
        ev_before = expected_value(float(p_true), price) + p_push
        ev_after = _edge_after_fix(market, side, line, float(p_true), price, p_push)
        if abs(ev_after - ev_before) < 0.0005:
            continue
        cert_before = ev_before >= 0.04
        cert_after = ev_after >= 0.04
        rows.append(
            {
                "game": f"{p.get('away_team')} @ {p.get('home_team')}",
                "pick": f"{p.get('side')} {line} ({market}) @ {p.get('book')}",
                "p_true": round(float(p_true), 4),
                "p_push_est": round(p_push, 4),
                "ev_before": f"{ev_before * 100:.2f}%",
                "ev_after": f"{ev_after * 100:.2f}%",
                "cert_before": cert_before,
                "cert_after": cert_after,
            }
        )

    print(json.dumps(rows, indent=2))
    print(f"\n{len(rows)} play(s) with EV change", file=sys.stderr)


if __name__ == "__main__":
    main()
