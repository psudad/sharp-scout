"""Plain-English spread / margin labels (home-perspective model_spread)."""

from __future__ import annotations

import re
from typing import Any

# model_spread = mu_away - mu_home (negative => home favored).
_S_MOD_RE = re.compile(r"S_mod=([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)


def home_line_from_play(side: str, line: float | int | None) -> float | None:
    if line is None:
        return None
    side_l = (side or "").lower()
    if side_l == "home":
        return float(line)
    if side_l == "away":
        return -float(line)
    return None


def parse_s_mod_from_reason(reason: str | None) -> float | None:
    if not reason:
        return None
    m = _S_MOD_RE.search(reason)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def format_model_margin(model_spread: float, home: str, away: str) -> str:
    """Human margin from home-perspective model_spread."""
    spread = float(model_spread)
    if abs(spread) < 0.15:
        return f"pick'em (slight lean {away if spread > 0 else home})"
    if spread > 0:
        return f"{away} by {spread:.1f}"
    return f"{home} by {abs(spread):.1f}"


def format_market_home_line(home_line: float, home: str, away: str) -> str:
    """Market spread in home-line notation plus who the number favors."""
    hl = float(home_line)
    if abs(hl) < 0.05:
        return f"pick'em ({home} {hl:+.1f})"
    if hl > 0:
        return f"{home} +{hl:g} ({away} by {hl:g})"
    return f"{home} {hl:+.1f} ({home} by {abs(hl):g})"


def spread_line_gap_message(
    *,
    model_spread: float,
    home_line: float,
    home: str,
    away: str,
    line_gap: float,
    gap_limit: float | None = None,
) -> str:
    model_s = format_model_margin(model_spread, home, away)
    market_s = format_market_home_line(home_line, home, away)
    tail = (
        f" — exceeds {gap_limit:.0f} pt QA band"
        if gap_limit is not None
        else " — implausible line disagreement"
    )
    return (
        f"Model margin: {model_s} · Market: {market_s} · "
        f"Gap {line_gap:.1f} pts{tail}"
    )


def spread_prob_gap_message(
    *,
    p_true: float,
    p_mkt: float,
    prob_gap: float,
    home: str,
    away: str,
    side: str,
    line: float | None,
) -> str:
    team = home if (side or "").lower() == "home" else away
    line_s = f" {team} {line:+.1f}" if line is not None else f" {team}"
    return (
        f"Cover prob at this line{line_s}: model {p_true:.1%} vs sharp {p_mkt:.1%} "
        f"(Δ{prob_gap:.0%}) — much higher than market price implies"
    )


def sync_play_sim_from_game(play: dict[str, Any], game: dict[str, Any] | None) -> None:
    """Refresh model_spread/total on a ledger row from the latest pipeline game snapshot."""
    if not game:
        return
    if game.get("model_spread") is not None:
        play["model_spread"] = round(float(game["model_spread"]), 2)
    if game.get("model_total") is not None:
        play["model_total"] = round(float(game["model_total"]), 2)
