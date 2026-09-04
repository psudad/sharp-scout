"""Per-game stage picks — independent winners from each data lens.

For every game we produce a pick from:
  - model     : Monte Carlo / fundamental fair side
  - sharp     : Pinnacle (or Circa) no-vig favorite
  - public    : ticket-% majority
  - money     : handle-% majority (sharp-money proxy)
  - rlm       : reverse line movement side (when present)
  - hybrid    : full system (validated edge), else model-vs-market lean

These are compared to each other so we can track which stage is right
independently of the hybrid filter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sharp_scout.config import get_settings
from sharp_scout.phase2.monte_carlo import GameSimResult
from sharp_scout.phase3.market import sharp_consensus
from sharp_scout.phase4.filters import _find_split_game, reverse_line_movement
from sharp_scout.utils.odds import american_to_implied_prob

Side = Literal["home", "away", "over", "under"]
MarketFocus = Literal["spread", "h2h", "total"]

STAGES = ("model", "sharp", "public", "money", "sharp_edge", "rlm", "hybrid")
STAGE_MARKETS: tuple[MarketFocus, ...] = ("spread", "h2h", "total")

_MARKET_ODDS_KEY = {"spread": "spreads", "h2h": "h2h", "total": "totals"}
_MARKET_SPLIT_KEY = {"spread": "spread", "h2h": "moneyline", "total": "total"}


@dataclass
class StagePick:
    stage: str
    market: str  # spread | h2h
    side: Side | None
    team: str | None
    line: float | None = None
    confidence: float | None = None  # 0-1 strength / probability
    reason: str = ""
    available: bool = True


@dataclass
class GameStageCard:
    event_id: str
    home_team: str
    away_team: str
    market: str
    picks: dict[str, StagePick] = field(default_factory=dict)
    agreement: dict[str, Any] = field(default_factory=dict)
    consensus_side: Side | None = None
    consensus_team: str | None = None
    hybrid_agrees_with: list[str] = field(default_factory=list)
    conflict_stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "market": self.market,
            "picks": {
                k: {
                    "stage": p.stage,
                    "market": p.market,
                    "side": p.side,
                    "team": p.team,
                    "line": p.line,
                    "confidence": round(p.confidence, 4) if p.confidence is not None else None,
                    "reason": p.reason,
                    "available": p.available,
                }
                for k, p in self.picks.items()
            },
            "agreement": self.agreement,
            "consensus_side": self.consensus_side,
            "consensus_team": self.consensus_team,
            "hybrid_agrees_with": self.hybrid_agrees_with,
            "conflict_stages": self.conflict_stages,
            "line_perspective": "team",
        }


def _team(side: Side | None, home: str, away: str) -> str | None:
    if side == "home":
        return home
    if side == "away":
        return away
    if side == "over":
        return "Over"
    if side == "under":
        return "Under"
    return None


def _line_for_side(market: str, side: Side | None, home_or_total_line: float | None) -> float | None:
    """Attach the line from the picked side's perspective.

    Action Network ``current_line`` and model spreads are home-perspective for ATS.
    Display and settlement expect the number you'd bet on the chosen team (away flips sign).
    Totals are unchanged.
    """
    if home_or_total_line is None:
        return None
    value = float(home_or_total_line)
    if market == "spread" and side == "away":
        return -value
    return value


def _home_spread_line(side: str | None, line: float) -> float:
    """Convert a team-perspective spread line back to home perspective for grading."""
    if side == "away":
        return -float(line)
    return float(line)


def _consensus_total_line(event: dict[str, Any]) -> float | None:
    sharp = sharp_consensus(event, "totals")
    if sharp:
        line = sharp.get("line")
        if line is not None:
            return float(line)
        for o in sharp.get("outcomes") or []:
            if o.get("point") is not None:
                return float(o["point"])
    for bm in (event.get("bookmakers") or {}).values():
        for o in (bm.get("markets") or {}).get("totals") or []:
            if o.get("point") is not None:
                return float(o["point"])
    return None


def _spread_line_from_split(split_game: dict[str, Any] | None) -> float | None:
    """Action Network spread in home perspective (neg => home favored)."""
    if not split_game:
        return None
    block = (split_game.get("markets") or {}).get("spread") or {}
    line = block.get("current_line")
    if line is None:
        return None
    return float(line)


def _consensus_spread_line(
    event: dict[str, Any],
    split_game: dict[str, Any] | None = None,
) -> float | None:
    """Market spread in home perspective (neg => home favored).

  Preference order: sharp consensus → any posted book → Action Network line.
  Many CFB slates (especially early-week / lower-tier) have splits but no
  Odds API bookmakers on the event row.
    """
    sharp = sharp_consensus(event, "spreads")
    outcomes = (sharp or {}).get("outcomes") or []
    for o in outcomes:
        if o.get("side") == "home" and o.get("point") is not None:
            return float(o["point"])
    for o in outcomes:
        if o.get("side") == "away" and o.get("point") is not None:
            return -float(o["point"])
    for bm in (event.get("bookmakers") or {}).values():
        spreads = (bm.get("markets") or {}).get("spreads") or []
        for o in spreads:
            if o.get("side") == "home" and o.get("point") is not None:
                return float(o["point"])
        for o in spreads:
            if o.get("side") == "away" and o.get("point") is not None:
                return -float(o["point"])
    return _spread_line_from_split(split_game)


def pick_model(
    sim: GameSimResult,
    home: str,
    away: str,
    market: str = "spread",
    event: dict[str, Any] | None = None,
    split_game: dict[str, Any] | None = None,
) -> StagePick:
    if market == "h2h":
        side: Side = "home" if sim.p_home_win >= sim.p_away_win else "away"
        conf = max(sim.p_home_win, sim.p_away_win)
        return StagePick(
            "model",
            "h2h",
            side,
            _team(side, home, away),
            None,
            conf,
            f"P_true win home={sim.p_home_win:.1%} away={sim.p_away_win:.1%}",
        )
    if market == "total":
        line = _consensus_total_line(event or {})
        if line is None:
            return StagePick("model", "total", None, None, reason="no market total line", available=False)
        from sharp_scout.phase2.monte_carlo import p_true_for_market

        side = "over" if sim.model_total >= line else "under"
        conf = p_true_for_market(sim, "totals", side, line)
        return StagePick(
            "model",
            "total",
            side,
            _team(side, home, away),
            line,
            conf,
            f"T_mod={sim.model_total:.1f} vs market {line:.1f}",
        )
    # ATS: model_spread and the market line are home-perspective (neg => home favored).
    # The model's lean is which side COVERS the market number, not who wins outright.
    # Home covers iff the model's projected home margin beats the market spread, i.e.
    # model_spread < market_line (e.g. model -3 vs market -29 => home doesn't cover).
    mkt = _consensus_spread_line(event or {}, split_game)
    if mkt is None:
        # No market line to bet against — fall back to the raw model lean.
        side = "home" if sim.model_spread <= 0 else "away"
        conf = sim.p_home_win if side == "home" else sim.p_away_win
        return StagePick(
            "model",
            "spread",
            side,
            _team(side, home, away),
            _line_for_side("spread", side, float(sim.model_spread)),
            conf,
            f"S_mod={sim.model_spread:+.2f} (home perspective; no market line)",
        )

    side = "home" if sim.model_spread < mkt else "away"
    disp_line = _line_for_side("spread", side, float(mkt))
    from sharp_scout.phase2.monte_carlo import p_true_for_market

    conf = p_true_for_market(sim, "spreads", side, disp_line)
    return StagePick(
        "model",
        "spread",
        side,
        _team(side, home, away),
        disp_line,
        conf,
        f"S_mod={sim.model_spread:+.2f} vs mkt {mkt:+.2f} (home persp) → {_team(side, home, away)} covers",
    )


def pick_sharp(event: dict[str, Any], home: str, away: str, market: str = "spread") -> StagePick:
    mkey = _MARKET_ODDS_KEY.get(market, "spreads")
    sharp = sharp_consensus(event, mkey)
    if not sharp:
        return StagePick("sharp", market, None, None, reason="no sharp book line", available=False)
    # Highest no-vig p_mkt wins
    best = max(sharp["outcomes"], key=lambda o: o.get("p_mkt") or 0.0)
    side = best.get("side")
    if side not in ("home", "away", "over", "under"):
        return StagePick("sharp", market, None, None, reason="unparsed sharp side", available=False)
    return StagePick(
        "sharp",
        market,
        side,  # type: ignore[arg-type]
        _team(side, home, away),  # type: ignore[arg-type]
        best.get("point") if market in ("spread", "total") else None,
        float(best.get("p_mkt") or 0.5),
        f"{sharp['book']} no-vig {best.get('p_mkt', 0):.1%} @ {best.get('price')}",
    )


def pick_public(split_game: dict[str, Any] | None, home: str, away: str, market: str = "spread") -> StagePick:
    if not split_game:
        return StagePick("public", market, None, None, reason="no Action Network row", available=False)
    split_key = _MARKET_SPLIT_KEY.get(market, "spread")
    block = (split_game.get("markets") or {}).get(split_key) or {}
    if market == "total":
        ob, ub = block.get("over_bet_pct"), block.get("under_bet_pct")
        if ob is None or ub is None:
            return StagePick("public", market, None, None, reason="ticket % missing", available=False)
        side: Side = "over" if ob >= ub else "under"
        return StagePick(
            "public",
            market,
            side,
            _team(side, home, away),
            _line_for_side(market, side, block.get("current_line")),
            max(ob, ub),
            f"tickets over={ob:.0%} under={ub:.0%}",
        )
    hb, ab = block.get("home_bet_pct"), block.get("away_bet_pct")
    if hb is None or ab is None:
        return StagePick("public", market, None, None, reason="ticket % missing", available=False)
    side = "home" if hb >= ab else "away"
    return StagePick(
        "public",
        market,
        side,
        _team(side, home, away),
        _line_for_side(market, side, block.get("current_line")),
        max(hb, ab),
        f"tickets home={hb:.0%} away={ab:.0%}",
    )


def pick_money(split_game: dict[str, Any] | None, home: str, away: str, market: str = "spread") -> StagePick:
    if not split_game:
        return StagePick("money", market, None, None, reason="no Action Network row", available=False)
    split_key = _MARKET_SPLIT_KEY.get(market, "spread")
    block = (split_game.get("markets") or {}).get(split_key) or {}
    if market == "total":
        om, um = block.get("over_money_pct"), block.get("under_money_pct")
        if om is None or um is None:
            return StagePick("money", market, None, None, reason="money % missing", available=False)
        side: Side = "over" if om >= um else "under"
        ob, ub = block.get("over_bet_pct"), block.get("under_bet_pct")
        gap = None
        if ob is not None and ub is not None:
            gap = (om - ob) if side == "over" else (um - ub)
        reason = f"money over={om:.0%} under={um:.0%}"
        if gap is not None:
            reason += f" (gap vs tickets {gap:+.0%} on {side})"
        return StagePick(
            "money",
            market,
            side,
            _team(side, home, away),
            _line_for_side(market, side, block.get("current_line")),
            max(om, um),
            reason,
        )
    hm, am = block.get("home_money_pct"), block.get("away_money_pct")
    if hm is None or am is None:
        return StagePick("money", market, None, None, reason="money % missing", available=False)
    side = "home" if hm >= am else "away"
    hb, ab = block.get("home_bet_pct"), block.get("away_bet_pct")
    gap = None
    if hb is not None and ab is not None:
        gap = (hm - hb) if side == "home" else (am - ab)
    reason = f"money home={hm:.0%} away={am:.0%}"
    if gap is not None:
        reason += f" (gap vs tickets {gap:+.0%} on {side})"
    return StagePick(
        "money",
        market,
        side,
        _team(side, home, away),
        _line_for_side(market, side, block.get("current_line")),
        max(hm, am),
        reason,
    )


def pick_sharp_edge(
    split_game: dict[str, Any] | None,
    home: str,
    away: str,
    market: str = "spread",
) -> StagePick:
    """Action Network Diff: side with the largest positive money − ticket %."""
    from sharp_scout.data.splits_board import build_market_board

    if not split_game:
        return StagePick("sharp_edge", market, None, None, reason="no Action Network row", available=False)
    mkey = _MARKET_SPLIT_KEY.get(market, "spread")
    if mkey not in ("spread", "moneyline", "total"):
        mkey = "spread"
    block = (split_game.get("markets") or {}).get(mkey) or {}
    board = build_market_board(block, market=mkey, home_team=home, away_team=away)  # type: ignore[arg-type]
    edge = board.get("sharp_edge") or {}
    if not edge.get("available"):
        return StagePick(
            "sharp_edge",
            market,
            None,
            None,
            reason=edge.get("reason") or "no sharp-edge diff",
            available=False,
        )
    side = edge.get("side")
    if side not in ("home", "away", "over", "under"):
        return StagePick("sharp_edge", market, None, None, reason="unparsed sharp-edge side", available=False)
    team = edge.get("team")
    if side in ("home", "away"):
        team = _team(side, home, away)
    conf = min(0.99, 0.5 + float(edge.get("diff_pct") or 0))
    return StagePick(
        "sharp_edge",
        market,
        side,  # type: ignore[arg-type]
        team,
        _line_for_side(market, side, block.get("current_line")),
        conf,
        edge.get("reason") or "",
    )


def pick_rlm(split_game: dict[str, Any] | None, home: str, away: str, market: str = "spread") -> StagePick:
    if market == "h2h":
        return StagePick("rlm", market, None, None, reason="RLM is spread/total only", available=False)
    if not split_game:
        return StagePick("rlm", market, None, None, reason="no Action Network row", available=False)
    split_key = _MARKET_SPLIT_KEY.get(market, "spread")
    odds_market = _MARKET_ODDS_KEY.get(market, "spreads")
    block = (split_game.get("markets") or {}).get(split_key) or {}
    sides: tuple[str, ...] = ("over", "under") if market == "total" else ("home", "away")
    for side in sides:
        ok, note = reverse_line_movement(block, side, odds_market)
        if ok:
            return StagePick(
                "rlm",
                market,
                side,  # type: ignore[arg-type]
                _team(side, home, away),  # type: ignore[arg-type]
                _line_for_side(market, side, block.get("current_line")),
                0.6,
                note,
            )
    _, note = reverse_line_movement(block, sides[0], odds_market)
    return StagePick("rlm", market, None, None, reason=note or "no RLM", available=False)


def pick_hybrid(
    *,
    home: str,
    away: str,
    model: StagePick,
    sharp: StagePick,
    money: StagePick,
    rlm: StagePick,
    validated_signals: list[dict[str, Any]],
    market: str = "spread",
) -> StagePick:
    """Prefer a validated system play on this game; else model when it disagrees with sharp."""
    odds_market = _MARKET_ODDS_KEY.get(market, "spreads")
    plays = [
        s
        for s in validated_signals
        if s.get("home_team") == home
        and s.get("away_team") == away
        and s.get("filter_passed")
        and s.get("market") == odds_market
    ]
    if plays:
        best = max(plays, key=lambda s: s.get("edge") or 0)
        side = best.get("side")
        if side in ("home", "away", "over", "under"):
            return StagePick(
                "hybrid",
                market,
                side,  # type: ignore[arg-type]
                _team(side, home, away),  # type: ignore[arg-type]
                best.get("line"),
                float(best.get("p_true") or 0.55),
                f"validated {best.get('tier')} EV={best.get('edge', 0):.1%} @ {best.get('book')}",
            )

    # Soft hybrid: model side when it disagrees with public AND (agrees with money or RLM or sharp)
    if not model.available or model.side is None:
        return StagePick("hybrid", market, None, None, reason="no model pick", available=False)

    allies = []
    for name, p in (("money", money), ("rlm", rlm), ("sharp", sharp)):
        if p.available and p.side == model.side:
            allies.append(name)
    if allies:
        return StagePick(
            "hybrid",
            market,
            model.side,
            model.team,
            model.line,
            model.confidence,
            "model aligned with " + "+".join(allies) + " (no validated edge)",
        )
    return StagePick(
        "hybrid",
        market,
        model.side,
        model.team,
        model.line,
        (model.confidence or 0.5) * 0.8,
        "model lean only — no confirming market stage",
        available=True,
    )


def build_game_stage_card(
    event: dict[str, Any],
    sim: GameSimResult,
    splits: list[dict[str, Any]],
    validated_signals: list[dict[str, Any]],
    *,
    market: str = "spread",
) -> GameStageCard:
    home, away = event["home_team"], event["away_team"]
    split = _find_split_game(splits, home, away, sport=str(event.get("sport") or "nfl"))
    model = pick_model(sim, home, away, market=market, event=event, split_game=split)
    sharp = pick_sharp(event, home, away, market=market)
    public = pick_public(split, home, away, market=market)
    money = pick_money(split, home, away, market=market)
    sharp_edge = pick_sharp_edge(split, home, away, market=market)
    rlm = pick_rlm(split, home, away, market=market)
    hybrid = pick_hybrid(
        home=home,
        away=away,
        model=model,
        sharp=sharp,
        money=money,
        rlm=rlm,
        validated_signals=validated_signals,
        market=market,
    )
    picks = {
        "model": model,
        "sharp": sharp,
        "public": public,
        "money": money,
        "sharp_edge": sharp_edge,
        "rlm": rlm,
        "hybrid": hybrid,
    }
    card = GameStageCard(
        event_id=str(event.get("event_id")),
        home_team=home,
        away_team=away,
        market=market,
        picks=picks,
    )
    _annotate_agreement(card)
    return card


def _annotate_agreement(card: GameStageCard) -> None:
    available = {k: p for k, p in card.picks.items() if p.available and p.side}
    if not available:
        card.agreement = {"n_available": 0}
        return

    # Majority vote among non-hybrid stages; hybrid compared separately
    voters = {k: p for k, p in available.items() if k != "hybrid"}
    if card.market == "total":
        over_votes = sum(1 for p in voters.values() if p.side == "over")
        under_votes = sum(1 for p in voters.values() if p.side == "under")
        card.consensus_side = "over" if over_votes > under_votes else "under" if under_votes > over_votes else None  # type: ignore[assignment]
        card.consensus_team = _team(card.consensus_side, card.home_team, card.away_team)  # type: ignore[arg-type]
        home_votes, away_votes = over_votes, under_votes
    else:
        home_votes = sum(1 for p in voters.values() if p.side == "home")
        away_votes = sum(1 for p in voters.values() if p.side == "away")
        if home_votes > away_votes:
            card.consensus_side = "home"
        elif away_votes > home_votes:
            card.consensus_side = "away"
        else:
            card.consensus_side = None
        card.consensus_team = _team(card.consensus_side, card.home_team, card.away_team)

    hybrid = card.picks.get("hybrid")
    if hybrid and hybrid.side:
        card.hybrid_agrees_with = [
            k for k, p in voters.items() if p.side == hybrid.side
        ]
        card.conflict_stages = [
            k for k, p in voters.items() if p.side and p.side != hybrid.side
        ]

    # Sharp vs public classic signal
    sharp_vs_public = None
    if "sharp" in voters and "public" in voters:
        if voters["sharp"].side != voters["public"].side:
            sharp_vs_public = {
                "sharp": voters["sharp"].team,
                "public": voters["public"].team,
                "fade_public": True,
            }
        else:
            sharp_vs_public = {"fade_public": False, "side": voters["sharp"].team}

    money_vs_public = None
    if "money" in voters and "public" in voters:
        money_vs_public = {
            "aligned": voters["money"].side == voters["public"].side,
            "money": voters["money"].team,
            "public": voters["public"].team,
        }

    card.agreement = {
        "n_available": len(available),
        "home_votes": home_votes,
        "away_votes": away_votes,
        "unanimous": home_votes == 0 or away_votes == 0,
        "sharp_vs_public": sharp_vs_public,
        "money_vs_public": money_vs_public,
        "rlm_active": bool(card.picks.get("rlm") and card.picks["rlm"].available),
    }


def build_slate_stage_picks(
    events: list[dict[str, Any]],
    sims: dict[str, GameSimResult],
    splits: list[dict[str, Any]],
    validated_signals: list[dict[str, Any]],
    *,
    market: str = "spread",
    markets: tuple[str, ...] | None = None,
    sport: str = "nfl",
) -> list[dict[str, Any]]:
    mkts = markets or (STAGE_MARKETS if market == "all" else (market,))
    cards = []
    for ev in events:
        eid = str(ev.get("event_id"))
        sim = sims.get(eid)
        if sim is None:
            continue
        ev_sport = str(ev.get("sport") or sport)
        ev_row = {**ev, "sport": ev_sport}
        for mkt in mkts:
            row = build_game_stage_card(ev_row, sim, splits, validated_signals, market=mkt).to_dict()
            row["kickoff"] = ev.get("commence_time")
            row["commence_time"] = ev.get("commence_time")
            cards.append(row)
    return cards


def summarize_stage_slate(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate how often hybrid agrees with each stage on this slate."""
    agree = {s: 0 for s in STAGES if s != "hybrid"}
    total = {s: 0 for s in STAGES if s != "hybrid"}
    fade_public = 0
    rlm_games = 0
    fade_public_list: list[dict[str, Any]] = []
    rlm_list: list[dict[str, Any]] = []
    for c in cards:
        matchup = f"{c.get('away_team')}@{c.get('home_team')}"
        for s in agree:
            p = (c.get("picks") or {}).get(s) or {}
            h = (c.get("picks") or {}).get("hybrid") or {}
            if p.get("available") and h.get("side"):
                total[s] += 1
                if p.get("side") == h.get("side"):
                    agree[s] += 1
        svp = (c.get("agreement") or {}).get("sharp_vs_public") or {}
        if svp.get("fade_public"):
            fade_public += 1
            fade_public_list.append(
                {
                    "matchup": matchup,
                    "away_team": c.get("away_team"),
                    "home_team": c.get("home_team"),
                    "sharp_team": svp.get("sharp"),
                    "public_team": svp.get("public"),
                }
            )
        if (c.get("agreement") or {}).get("rlm_active"):
            rlm_games += 1
            rlm_pick = (c.get("picks") or {}).get("rlm") or {}
            rlm_list.append(
                {
                    "matchup": matchup,
                    "away_team": c.get("away_team"),
                    "home_team": c.get("home_team"),
                    "rlm_team": rlm_pick.get("team"),
                    "reason": rlm_pick.get("reason"),
                }
            )
    return {
        "n_games": len({c.get("event_id") for c in cards}),
        "n_rows": len(cards),
        "hybrid_agreement_rate": {
            s: (agree[s] / total[s] if total[s] else None) for s in agree
        },
        "fade_public_games": fade_public,
        "fade_public_matchups": fade_public_list,
        "rlm_games": rlm_games,
        "rlm_matchups": rlm_list,
    }


def settle_stage_pick(
    side: str | None,
    *,
    home_score: int,
    away_score: int,
    market: str = "spread",
    line: float | None = None,
) -> str | None:
    """Return win/loss/push for a stage side vs final score. None if no side."""
    if side not in ("home", "away", "over", "under"):
        return None
    if market == "h2h":
        if home_score == away_score:
            return "push"
        won_home = home_score > away_score
        return "win" if (side == "home") == won_home else "loss"
    if market == "total":
        if line is None:
            return None
        total_pts = home_score + away_score
        if abs(total_pts - float(line)) < 1e-9:
            return "push"
        over_won = total_pts > float(line)
        return "win" if (side == "over") == over_won else "loss"
    # ATS using home line if provided, else pick favorite ML-style margin
    if line is None:
        margin = home_score - away_score
        if margin == 0:
            return "push"
        return "win" if (side == "home" and margin > 0) or (side == "away" and margin < 0) else "loss"
    # ATS: stage pick lines are team-perspective (Odds API point / bet slip number).
    home_line = _home_spread_line(side, float(line))
    covered = (home_score + home_line) - away_score
    if abs(covered) < 1e-9:
        return "push"
    home_covers = covered > 0
    if side == "home":
        return "win" if home_covers else "loss"
    return "win" if not home_covers else "loss"


_HOME_PERSPECTIVE_STAGES = frozenset({"model", "public", "money", "sharp_edge", "rlm"})


def _should_flip_legacy_home_line(stage: str, pick: dict[str, Any]) -> bool:
    if stage in _HOME_PERSPECTIVE_STAGES:
        return True
    if stage != "hybrid":
        return False
    reason = str(pick.get("reason") or "").lower()
    return reason.startswith("model aligned") or reason.startswith("model lean")


def normalize_stage_card_team_lines(card: dict[str, Any]) -> dict[str, Any]:
    """Flip legacy home-perspective spread lines to team-perspective (idempotent via marker)."""
    if str(card.get("market") or "") != "spread":
        return card
    if card.get("line_perspective") == "team":
        return card
    picks = card.get("picks") or {}
    out_picks: dict[str, Any] = {}
    changed = False
    for stage, pick in picks.items():
        row = dict(pick or {})
        if (
            _should_flip_legacy_home_line(str(stage), row)
            and row.get("side") == "away"
            and row.get("line") is not None
        ):
            row["line"] = -float(row["line"])
            changed = True
        out_picks[str(stage)] = row
    if not changed and not picks:
        out = dict(card)
        out["line_perspective"] = "team"
        return out
    out = dict(card)
    out["picks"] = out_picks
    out["line_perspective"] = "team"
    return out


def normalize_stage_cards_team_lines(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_stage_card_team_lines(c) for c in cards]