"""Backtest how the model-agreement gate would have treated graded NCAAM plays."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.certification_gates import certification_block_reason
from sharp_scout.ncaam.price_edge_backtest import _agg, _is_official_pick
LEDGER_PATH = DATA_DIR / "ncaam_ledger.json"
LINE_HISTORY_PATH = DATA_DIR / "ncaam" / "line_history.json"


def _would_block(play: dict[str, Any]) -> bool:
    return certification_block_reason(play) is not None


def run_model_agreement_backtest(
    *,
    ledger_path: Path | None = None,
    history_path: Path | None = None,
) -> dict[str, Any]:
    ledger_path = ledger_path or LEDGER_PATH
    history_path = history_path or LINE_HISTORY_PATH
    ledger = json.loads(ledger_path.read_text())
    try:
        history = json.loads(history_path.read_text())
    except OSError:
        history = {}
    picks = [p for p in ledger.get("plays") or [] if _is_official_pick(p)]
    blocked = [p for p in picks if _would_block(p)]
    allowed = [p for p in picks if not _would_block(p)]
    return {
        "blocked_plays": _agg(blocked, history=history),
        "allowed_plays": _agg(allowed, history=history),
        "blocked_examples": [
            {
                "selection": p.get("selection"),
                "market": p.get("market"),
                "price": p.get("price"),
                "status": p.get("status"),
                "pnl_units": p.get("pnl_units"),
                "reason": certification_block_reason(p),
            }
            for p in blocked
        ],
        "n_blocked": len(blocked),
        "n_allowed": len(allowed),
    }


def format_backtest_markdown(result: dict[str, Any]) -> str:
    b = result["blocked_plays"]
    a = result["allowed_plays"]
    lines = [
        "### NCAAM model-agreement gate backtest (graded season)",
        "",
        "| Cohort | n | W-L | Units | ROI |",
        "|---|---|---:|---:|---:|",
        f"| Would still post | {a['n']} | {a['w']}-{a['l']} | {a['units']:+.2f} | {a['roi_pct']:+.1f}% |",
        f"| Would have blocked | {b['n']} | {b['w']}-{b['l']} | {b['units']:+.2f} | {b['roi_pct']:+.1f}% |",
        "",
        f"**Blocked {result['n_blocked']}** graded play(s).",
    ]
    if result.get("blocked_examples"):
        lines.append("")
        lines.append("Blocked plays:")
        for ex in result["blocked_examples"]:
            lines.append(
                f"- {ex.get('selection')} {ex.get('market')} {ex.get('price'):+.0f} "
                f"→ {ex.get('status')} ({float(ex.get('pnl_units') or 0):+.1f}u): {ex.get('reason')}"
            )
    return "\n".join(lines)