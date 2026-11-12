"""Shadow logging for pace-scaled margin SD (no official picks)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sharp_scout.config import DATA_DIR
from sharp_scout.ncaam.margin_sd_pace import (
    DEFAULT_PACE_SHADOW,
    LIVE_MARGIN_SD,
    margin_sd_for_model,
)
from sharp_scout.ncaam.rules import RULES, candidate_ev
from sharp_scout.phase3.market import anchor_probability, shift_prob_to_line
from sharp_scout.utils.odds import win_prob_to_conditional

logger = logging.getLogger(__name__)

SHADOW_PATH = DATA_DIR / "shadow" / "ncaam_margin_sd_pace.json"
PARAMS_PATH = DATA_DIR / "shadow" / "ncaam_margin_sd_pace_params.json"


def load_params() -> dict[str, Any]:
    if PARAMS_PATH.exists():
        try:
            return json.loads(PARAMS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "model": "sqrt_pace",
        "base": DEFAULT_PACE_SHADOW.base,
        "ref_poss": DEFAULT_PACE_SHADOW.ref_poss,
        "live_margin_sd": LIVE_MARGIN_SD,
        "fit_note": "default from Nov 2026 holdout backtest; see reports/ncaam_margin_sd_pace_backtest.md",
    }


def pace_shadow_sd(expected_poss: float) -> float:
    p = load_params()
    model = str(p.get("model", DEFAULT_PACE_SHADOW.model))
    return margin_sd_for_model(
        model,
        expected_poss,
        base=float(p.get("base", DEFAULT_PACE_SHADOW.base)),
        ref_poss=float(p.get("ref_poss", DEFAULT_PACE_SHADOW.ref_poss)),
    )


def enrich_candidate_shadow(
    candidate: dict[str, Any],
    *,
    expected_poss: float,
    p_mod_live: float,
    p_push: float,
    p_home_fair_pin: float | None,
    home_spread_pin: float | None,
    k: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach shadow fields; does not mutate official EV / p_true."""
    sd_shadow = pace_shadow_sd(expected_poss)
    sd_live = LIVE_MARGIN_SD
    side = str(candidate.get("side"))
    market = str(candidate.get("market"))
    line = candidate.get("line")
    price = float(candidate.get("price") or 0)

    shadow: dict[str, Any] = {
        "expected_poss": round(float(expected_poss), 3),
        "margin_sd_live": sd_live,
        "margin_sd_pace": round(sd_shadow, 4),
    }

    from sharp_scout.ncaam.margin_sd_pace import p_cover_spread_normal, p_ml_normal

    margin_mu = float(candidate.get("model_margin") or 0.0)
    if market == "spreads" and line is not None:
        p_mod_s, p_push_s = p_cover_spread_normal(margin_mu, float(line), side, sd_shadow)
    elif market == "h2h":
        p_mod_s, p_push_s = p_ml_normal(margin_mu, side, sd_shadow)
    else:
        p_mod_s, p_push_s = p_mod_live, p_push

    p_fair_s = candidate.get("p_fair")
    if (
        market == "spreads"
        and p_home_fair_pin is not None
        and home_spread_pin is not None
        and line is not None
    ):
        ref = float(home_spread_pin) if side == "home" else -float(home_spread_pin)
        p_ref = float(p_home_fair_pin) if side == "home" else 1.0 - float(p_home_fair_pin)
        p_fair_s, _ = shift_prob_to_line(
            p_ref,
            market="spreads",
            side=side,
            ref_line=ref,
            line=float(line),
            sd=sd_shadow,
        )

    p_true_s = anchor_probability(p_mod_s, p_fair_s, k, RULES.anchor_tilt_cap)
    p_cond_s = win_prob_to_conditional(p_true_s, p_push_s)
    ev_s = candidate_ev(p_cond_s, price, p_push_s)

    shadow.update(
        {
            "p_model_live": round(float(p_mod_live), 4),
            "p_model_pace": round(float(p_mod_s), 4),
            "p_fair_pace": round(float(p_fair_s), 4) if p_fair_s is not None else None,
            "p_true_pace": round(float(p_true_s), 4),
            "ev_pace": round(float(ev_s), 4),
            "ev_live": round(float(candidate.get("ev") or 0), 4),
            "would_qualify_pace": bool(ev_s >= RULES.ev_min),
        }
    )
    candidate["margin_sd_shadow"] = shadow
    return candidate


def record_shadow_rows(rows: list[dict[str, Any]], *, generated_at: str | None = None) -> None:
    if not rows:
        return
    SHADOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    store: dict[str, Any] = {"version": 1, "plays": []}
    if SHADOW_PATH.exists():
        try:
            store = json.loads(SHADOW_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            store = {"version": 1, "plays": []}
    store.setdefault("plays", [])
    store["params"] = load_params()
    store["updated_at"] = generated_at or datetime.now(timezone.utc).isoformat()
    seen = {str(r.get("espn_id")) + str(r.get("book")) + str(r.get("line")): r for r in store["plays"]}
    for row in rows:
        key = str(row.get("espn_id")) + str(row.get("book")) + str(row.get("line"))
        entry = {k: v for k, v in row.items() if k != "margin_sd_shadow"}
        sh = row.get("margin_sd_shadow") or {}
        entry["shadow"] = sh
        seen[key] = entry
    store["plays"] = list(seen.values())
    SHADOW_PATH.write_text(json.dumps(store, indent=2, default=str) + "\n")
    logger.info("Wrote %d NCAAM pace-SD shadow rows to %s", len(rows), SHADOW_PATH)
