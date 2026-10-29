"""Isolated helpers for NBA Pace original-vs-live backtest (research only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MIN_GAP = 3.0

# Git anchor for pre–#116 / pre–#117 card rules (injury-adj, no raw-gap gate, DTD 0.45).
ORIGINAL_POST_INJURY_COMMIT = "b913bcb253115489c118c190aa96c418aa8f89d8"

# Last main before Oct 25–26 winning slates (#107 injury Pace not merged until Oct 27).
ORIGINAL_PRE_INJURY_COMMIT = "e45945aa2f0141ebd12d9621c4df16c1fbe77570"


def gap_bucket(gap: float | None) -> str:
    if gap is None:
        return "—"
    g = float(gap)
    if g < 3.0:
        return "<3"
    if g < 5.0:
        return "3-5"
    if g < 8.0:
        return "5-8"
    return "8+"


def units_at_110(result: str | None) -> float:
    if result == "win":
        return round(100.0 / 110.0, 4)
    if result == "loss":
        return -1.0
    if result == "push":
        return 0.0
    return 0.0


def _format_spread_pick(home: str, away: str, spread_home: float, margin_edge: float) -> str:
    side = "home" if margin_edge > 0 else "away"
    team = home if side == "home" else away
    line = float(spread_home) if side == "home" else -float(spread_home)
    sign = "+" if line > 0 else ""
    return f"{team} {sign}{line:g}"


def picks_from_edges(
    *,
    home: str,
    away: str,
    lines: dict[str, Any],
    margin: float,
    total: float,
    min_gap: float = MIN_GAP,
) -> list[dict[str, Any]]:
    """Oct 25–26 era: raw stage-3 margin/total vs consensus; each market independent."""
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    picks: list[dict[str, Any]] = []
    if cs is not None:
        edge = float(margin) + float(cs)
        if abs(edge) >= min_gap:
            side = "home" if edge > 0 else "away"
            picks.append(
                {
                    "kind": "spread",
                    "pick": _format_spread_pick(home, away, float(cs), edge),
                    "side": side,
                    "line": float(cs) if side == "home" else -float(cs),
                    "gap": abs(edge),
                    "signed_gap": edge,
                    "raw_signed_gap": edge,
                }
            )
    if ct is not None:
        edge_t = float(total) - float(ct)
        if abs(edge_t) >= min_gap:
            side = "over" if edge_t > 0 else "under"
            label = "Over" if edge_t > 0 else "Under"
            picks.append(
                {
                    "kind": "total",
                    "pick": f"{away} @ {home}: {label} {float(ct):g}",
                    "side": side,
                    "line": float(ct),
                    "gap": abs(edge_t),
                    "signed_gap": edge_t,
                    "raw_signed_gap": edge_t,
                }
            )
    return picks


def pick_from_edges(**kwargs: Any) -> dict[str, Any] | None:
    picks = picks_from_edges(**kwargs)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


def picks_original_pre_injury(snap: dict[str, Any], *, home: str, away: str) -> list[dict[str, Any]]:
    lines = snap.get("lines") or {}
    margin = float(snap.get("margin") or 0)
    total = float(snap.get("total") or 0)
    return picks_from_edges(home=home, away=away, lines=lines, margin=margin, total=total)


def picks_original_b913bcb(snap: dict[str, Any], *, home: str, away: str) -> list[dict[str, Any]]:
    """Injury-adj gap ≥3, no raw-gap gate (``official_pace.py`` at b913bcb)."""
    lines = snap.get("lines") or {}
    cs, ct = lines.get("consensus_spread_home"), lines.get("consensus_total")
    pm_i = float(snap.get("injury_margin") if snap.get("injury_margin") is not None else snap.get("margin") or 0)
    pt_i = float(snap.get("injury_total") if snap.get("injury_total") is not None else snap.get("total") or 0)
    picks: list[dict[str, Any]] = []
    if cs is not None:
        edge = pm_i + float(cs)
        if abs(edge) >= MIN_GAP:
            side = "home" if edge > 0 else "away"
            picks.append(
                {
                    "kind": "spread",
                    "pick": _format_spread_pick(home, away, float(cs), edge),
                    "side": side,
                    "line": float(cs) if side == "home" else -float(cs),
                    "gap": abs(edge),
                    "signed_gap": edge,
                    "raw_signed_gap": float(snap.get("margin") or 0) + float(cs),
                }
            )
    if ct is not None:
        edge_t = pt_i - float(ct)
        if abs(edge_t) >= MIN_GAP:
            side = "over" if edge_t > 0 else "under"
            label = "Over" if edge_t > 0 else "Under"
            picks.append(
                {
                    "kind": "total",
                    "pick": f"{away} @ {home}: {label} {float(ct):g}",
                    "side": side,
                    "line": float(ct),
                    "gap": abs(edge_t),
                    "signed_gap": edge_t,
                    "raw_signed_gap": float(snap.get("total") or 0) - float(ct),
                }
            )
    return picks


def pick_original_pre_injury(snap: dict[str, Any], *, home: str, away: str) -> dict[str, Any] | None:
    picks = picks_original_pre_injury(snap, home=home, away=away)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


def pick_original_b913bcb(snap: dict[str, Any], *, home: str, away: str) -> dict[str, Any] | None:
    picks = picks_original_b913bcb(snap, home=home, away=away)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


def picks_current_raw(snap: dict[str, Any], *, home: str, away: str) -> list[dict[str, Any]]:
    return picks_from_edges(
        home=home,
        away=away,
        lines=snap.get("lines") or {},
        margin=float(snap.get("margin") or 0),
        total=float(snap.get("total") or 0),
    )


def pick_current_raw(snap: dict[str, Any], *, home: str, away: str) -> dict[str, Any] | None:
    picks = picks_current_raw(snap, home=home, away=away)
    if not picks:
        return None
    return max(picks, key=lambda x: float(x.get("gap") or 0))


@dataclass
class Record:
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    units: float = 0.0

    def add(self, result: str | None) -> None:
        if result == "win":
            self.wins += 1
            self.units += units_at_110("win")
        elif result == "loss":
            self.losses += 1
            self.units -= 1.0
        elif result == "push":
            self.pushes += 1

    @property
    def n(self) -> int:
        return self.wins + self.losses + self.pushes

    def wl(self) -> str:
        s = f"{self.wins}-{self.losses}"
        if self.pushes:
            s += f"-{self.pushes}"
        return s


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def n_needed_for_break_even(p_hat: float, p0: float = 0.524, alpha: float = 0.05) -> int | None:
    """Approximate one-sided n to reject H0: p=p0 when true p=p_hat (normal approx)."""
    if p_hat <= p0:
        return None
    z = 1.645 if alpha == 0.05 else 1.96
    num = (z * math.sqrt(p0 * (1 - p0))) ** 2
    den = (p_hat - p0) ** 2
    if den <= 0:
        return None
    return int(math.ceil(num / den))
