"""Phase 4 — News / weather / inactive filter for player props."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sharp_scout.config import get_settings
from sharp_scout.data.situational import weather_adjustment
from sharp_scout.props.markets import PropEdge


@dataclass
class PropFilterResult:
    passed: bool
    notes: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    tier: str = "candidate"


def apply_weather_to_usage_mult(
    *,
    wind_mph: float | None,
    precip: bool = False,
) -> dict[str, float]:
    """Return multipliers for pass/rec vs rush props under weather thresholds."""
    wx = weather_adjustment(wind_mph, precip)
    wind = wind_mph or 0.0
    pass_mult = 1.0
    rush_mult = 1.0
    if wind >= 15:
        pass_mult *= 0.92
        rush_mult *= 1.03
    if wind >= 20:
        pass_mult *= 0.90
    if precip:
        pass_mult *= 0.94
        rush_mult *= 1.02
    return {
        "pass_mult": pass_mult,
        "rush_mult": rush_mult,
        "total_adj": wx["total_adj"],
        "wind": wind,
        "precip": precip,
    }


def validate_prop_edge(
    edge: PropEdge,
    *,
    inactive: list[str] | None = None,
    wind_mph: float | None = None,
    precip: bool = False,
    news_ok: bool = True,
) -> PropFilterResult:
    settings = get_settings()
    notes: list[str] = []
    flags = {
        "ev_ok": edge.edge >= settings.ev_threshold,
        "weather_ok": True,
        "active": True,
        "news_ok": news_ok,
        "alternate": edge.is_alternate,
    }
    notes.append(f"EV={edge.edge:.2%} mean={edge.model_mean:.1f} vs line={edge.line}")

    inactive = inactive or []
    inact_l = {n.lower() for n in inactive}
    if edge.player_name.lower() in inact_l:
        flags["active"] = False
        notes.append(f"{edge.player_name} listed inactive — reject")
        return PropFilterResult(False, notes, flags, "rejected")

    wx = apply_weather_to_usage_mult(wind_mph=wind_mph, precip=precip)
    if wx["wind"] >= 15 and edge.market in (
        "player_pass_yds",
        "player_reception_yds",
        "player_pass_tds",
        "player_receptions",
    ):
        if edge.side == "over":
            flags["weather_ok"] = False
            notes.append(f"wind {wx['wind']:.0f} mph — downgrade pass/rec overs")
        else:
            notes.append(f"wind {wx['wind']:.0f} mph supports under")

    if not flags["ev_ok"] or not flags["active"] or not flags["news_ok"]:
        return PropFilterResult(False, notes, flags, "rejected")

    if not flags["weather_ok"]:
        return PropFilterResult(False, notes, flags, "rejected")

    if edge.is_alternate and edge.edge >= 0.04:
        tier = "play"
        notes.append("alternate/tail line edge")
    elif edge.edge >= 0.03:
        tier = "play"
    else:
        tier = "lean"

    return PropFilterResult(True, notes, flags, tier)


def attach_prop_filters(
    edges: list[PropEdge],
    *,
    inactive: list[str] | None = None,
    wind_mph: float | None = None,
    precip: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for e in edges:
        fr = validate_prop_edge(e, inactive=inactive, wind_mph=wind_mph, precip=precip)
        out.append(
            {
                "event_id": e.event_id,
                "home_team": e.home_team,
                "away_team": e.away_team,
                "player_name": e.player_name,
                "team": e.team,
                "market": e.market,
                "side": e.side,
                "line": e.line,
                "book": e.book,
                "price": e.price,
                "p_true": round(e.p_true, 4),
                "p_mkt": round(e.p_mkt, 4) if e.p_mkt is not None else None,
                "edge": round(e.edge, 4),
                "model_mean": round(e.model_mean, 2),
                "model_median": round(e.model_median, 2),
                "is_alternate": e.is_alternate,
                "filter_passed": fr.passed,
                "tier": fr.tier,
                "flags": fr.flags,
                "filter_notes": fr.notes,
                "rationale": "; ".join(fr.notes),
                "play_type": "prop",
            }
        )
    return out