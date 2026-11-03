"""NBA moneyline anchor guard: placeholder prices, side matching, source labels, voids."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from sharp_scout.nba import fair
from sharp_scout.nba.demo import mock_nba_events
from sharp_scout.nba.game_lines import discover_game_line_edges, scan_game_line_opportunities
from sharp_scout.phase3.market import fair_probs_from_two_way


def _ml(home: float | None, away: float | None, *, home_first: bool = True) -> list[dict[str, Any]]:
    h = {"side": "home", "name": "Boston Celtics", "price": home, "point": None}
    a = {"side": "away", "name": "Milwaukee Bucks", "price": away, "point": None}
    return [h, a] if home_first else [a, h]


def _event(books: dict[str, list[dict[str, Any]]], **extra_markets: Any) -> dict[str, Any]:
    bms: dict[str, Any] = {}
    for key, outcomes in books.items():
        markets: dict[str, Any] = {"h2h": outcomes}
        markets.update(extra_markets.get(key) or {})
        bms[key] = {
            "key": key,
            "markets": markets,
            "is_sharp": key in ("pinnacle", "circa", "circa_sports", "betfair_ex_eu"),
        }
    return {
        "event_id": "evt-test",
        "home_team": "BOS",
        "away_team": "MIL",
        "kickoff": "2026-11-05T00:40:00+00:00",
        "bookmakers": bms,
    }


def _h2h_rows(event: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in scan_game_line_opportunities(event) if r["market"] == "h2h"]


# --- Betfair placeholders --------------------------------------------------------------


def test_betfair_placeholder_minus_10000_logs_nothing():
    """The Nov 4 bug: Betfair -10000/-10000 must not become a ~50% fair price."""
    ev = _event(
        {
            "betfair_ex_eu": _ml(-10000, -10000),
            "draftkings": _ml(-1100, 660),
        }
    )
    assert fair.fair_reference(ev, "h2h", min_books=2) is None
    assert fair.sharp_two_way_fair(ev, "h2h") is None
    assert _h2h_rows(ev) == []
    assert not [e for e in discover_game_line_edges(ev) if e.market == "h2h"]


def test_betfair_never_used_even_with_sane_prices():
    ev = _event({"betfair_ex_eu": _ml(-150, 140), "draftkings": _ml(-160, 135)})
    assert fair.h2h_sharp_anchor(ev) is None
    # Only one non-exchange book: consensus needs two.
    assert fair.fair_reference(ev, "h2h", min_books=2) is None


def test_betfair_placeholder_falls_through_to_pinnacle():
    ev = _event(
        {
            "betfair_ex_eu": _ml(-10000, -10000),
            "pinnacle": _ml(-800, 560),
            "draftkings": _ml(-1100, 660),
        }
    )
    ref = fair.fair_reference(ev, "h2h", min_books=2)
    assert ref is not None
    assert ref["book"] == "pinnacle" and ref["source"] == "pinnacle"
    by = {o["side"]: o["p_fair"] for o in ref["outcomes"]}
    assert by["away"] < 0.2  # real long dog, not 50%


# --- Extreme prices and overround ------------------------------------------------------


@pytest.mark.parametrize(
    "home,away",
    [(-2000, 1200), (-1500, 2000), (-5000, 2500), (150, 150), (-300, -300), (None, 200), (50, -120)],
)
def test_bad_pinnacle_prices_rejected(home, away):
    ev = _event({"pinnacle": _ml(home, away)})
    assert fair.h2h_sharp_anchor(ev) is None


def test_bad_pinnacle_falls_through_to_circa_with_real_label():
    ev = _event({"pinnacle": _ml(-10000, 3000), "circa": _ml(-200, 175), "fanduel": _ml(-210, 180)})
    ref = fair.fair_reference(ev, "h2h", min_books=2)
    assert ref["book"] == "circa"
    assert ref["source"] == "circa"


def test_consensus_median_when_no_valid_sharp_book():
    ev = _event(
        {
            "betfair_ex_eu": _ml(-10000, -10000),
            "pinnacle": _ml(-10000, -10000),
            "draftkings": _ml(-200, 170),
            "fanduel": _ml(-190, 160),
            "betmgm": _ml(-210, 175),
        }
    )
    ref = fair.fair_reference(ev, "h2h", min_books=2)
    assert ref["book"] == "consensus" and ref["source"] == "consensus"
    assert ref["books"] == ["betmgm", "draftkings", "fanduel"]
    homes = sorted(
        fair_probs_from_two_way(h, a)[0] for h, a in ((-200, 170), (-190, 160), (-210, 175))
    )
    by = {o["side"]: o["p_fair"] for o in ref["outcomes"]}
    assert by["home"] == pytest.approx(homes[1])
    assert by["home"] + by["away"] == pytest.approx(1.0)


# --- Side matching ---------------------------------------------------------------------


def test_sides_matched_regardless_of_outcome_order():
    a = fair.h2h_sharp_anchor(_event({"pinnacle": _ml(-300, 250, home_first=True)}))
    b = fair.h2h_sharp_anchor(_event({"pinnacle": _ml(-300, 250, home_first=False)}))
    pa = {o["side"]: o["p_fair"] for o in a["outcomes"]}
    pb = {o["side"]: o["p_fair"] for o in b["outcomes"]}
    assert pa == pytest.approx(pb)
    assert pa["home"] > 0.7 and pa["away"] < 0.3
    # Home price belongs to home side.
    assert {o["side"]: o["price"] for o in b["outcomes"]} == {"home": -300.0, "away": 250.0}


def test_sides_matched_by_team_name_when_side_missing():
    outs = [
        {"side": "Milwaukee Bucks", "name": "Milwaukee Bucks", "price": 250},
        {"side": "Boston Celtics", "name": "Boston Celtics", "price": -300},
    ]
    ref = fair.h2h_sharp_anchor(_event({"pinnacle": outs}))
    assert ref is not None
    prices = {o["side"]: o["price"] for o in ref["outcomes"]}
    assert prices == {"home": -300.0, "away": 250.0}


def test_duplicate_or_unknown_sides_rejected():
    dup = [{"side": "home", "price": -300}, {"side": "home", "price": 250}]
    assert fair.h2h_sharp_anchor(_event({"pinnacle": dup})) is None
    unknown = [{"side": "home", "price": -300}, {"side": "Draw", "name": "Draw", "price": 250}]
    assert fair.h2h_sharp_anchor(_event({"pinnacle": unknown})) is None


def test_scan_rows_carry_real_source_book():
    ev = _event({"circa": _ml(-150, 130), "draftkings": _ml(-160, 150)})
    rows = _h2h_rows(ev)
    assert rows, "expected a +EV away moneyline vs Circa"
    for r in rows:
        assert r["fair_source"] == "circa"
        assert r["sharp_book"] == "circa"


# --- Spreads, totals and the Pace card are unchanged -----------------------------------


def _legacy_sharp_two_way_fair(event: dict[str, Any], market: str) -> dict[str, Any] | None:
    """Exact copy of fair.sharp_two_way_fair before the moneyline guard (main 56da200d)."""
    books = event.get("bookmakers") or {}
    preference = ["pinnacle", "circa", "circa_sports", "betfair_ex_eu"]
    chosen = None
    for key in preference:
        if key in books and market in (books[key].get("markets") or {}):
            chosen = (key, books[key]["markets"][market])
            break
    if chosen is None:
        for key, bm in books.items():
            if bm.get("is_sharp") and market in (bm.get("markets") or {}):
                chosen = (key, bm["markets"][market])
                break
    if chosen is None:
        return None
    book, outcomes = chosen
    if len(outcomes) < 2:
        return None
    a, b = outcomes[0], outcomes[1]
    if a.get("price") is None or b.get("price") is None:
        return None
    pa, pb = fair_probs_from_two_way(float(a["price"]), float(b["price"]))
    return {"book": book, "source": "pinnacle", "outcomes": [{**a, "p_fair": pa}, {**b, "p_fair": pb}]}


def _spread_total_events() -> list[dict[str, Any]]:
    evs = [copy.deepcopy(e) for e in mock_nba_events()]
    # Betfair-only spreads/totals (legacy behaviour must be kept for these markets).
    bf = _event(
        {"betfair_ex_eu": _ml(-10000, -10000), "draftkings": _ml(-200, 170)},
        betfair_ex_eu={
            "spreads": [
                {"side": "home", "price": -105, "point": -4.5},
                {"side": "away", "price": -115, "point": 4.5},
            ],
            "totals": [
                {"side": "over", "price": -110, "point": 221.5},
                {"side": "under", "price": -110, "point": 221.5},
            ],
        },
        draftkings={
            "spreads": [
                {"side": "home", "price": -110, "point": -3.5},
                {"side": "away", "price": -110, "point": 3.5},
            ],
            "totals": [
                {"side": "over", "price": -110, "point": 223.5},
                {"side": "under", "price": -110, "point": 223.5},
            ],
        },
    )
    evs.append(bf)
    return evs


@pytest.mark.parametrize("market", ["spreads", "totals"])
def test_spreads_totals_sharp_fair_unchanged(market):
    for ev in _spread_total_events():
        assert fair.sharp_two_way_fair(ev, market) == _legacy_sharp_two_way_fair(ev, market)


def test_spreads_totals_scan_rows_unchanged():
    """Spread/total opportunities equal what the legacy anchor would produce."""
    from sharp_scout.nba import game_lines

    for ev in _spread_total_events():
        new_rows = [r for r in scan_game_line_opportunities(ev) if r["market"] != "h2h"]

        def legacy_ref(event, market, *, min_books=None):
            if market == "h2h":
                return None
            return _legacy_sharp_two_way_fair(event, market) or fair.consensus_two_way_fair(
                event, market, min_books=min_books
            )

        orig = game_lines.fair_reference
        game_lines.fair_reference = legacy_ref
        try:
            old_rows = [r for r in scan_game_line_opportunities(ev) if r["market"] != "h2h"]
        finally:
            game_lines.fair_reference = orig
        assert new_rows == old_rows


def test_pace_snapshot_lines_unchanged():
    from sharp_scout.nba.score_model import lines

    for ev in _spread_total_events():
        new = lines.snapshot_game_lines(ev)
        orig = lines.sharp_two_way_fair
        lines.sharp_two_way_fair = _legacy_sharp_two_way_fair
        try:
            old = lines.snapshot_game_lines(ev)
        finally:
            lines.sharp_two_way_fair = orig
        assert new == old


# --- Void overrides --------------------------------------------------------------------


def _isolated_shadow(tmp_path, monkeypatch):
    from sharp_scout.nba import paths as nba_paths

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    monkeypatch.setattr(nba_paths, "SHADOW_DIR", shadow)
    monkeypatch.setattr(nba_paths, "NBA_LEDGER_PATH", shadow / "nba_ledger.json")
    return shadow


def test_void_override_applied_and_blocks_relog(tmp_path, monkeypatch):
    from sharp_scout.nba.ledger import append_nba_signals, load_nba_ledger, save_nba_ledger
    from sharp_scout.nba.overrides import apply_nba_ledger_overrides, drop_voided_signals

    shadow = _isolated_shadow(tmp_path, monkeypatch)
    (shadow / "nba_ledger_overrides.json").write_text(
        json.dumps(
            {
                "voids": [
                    {"id": "abc12345", "event_id": "e1", "market": "h2h", "side": "away",
                     "reason": "placeholder anchor price bug"}
                ]
            }
        )
    )
    save_nba_ledger(
        {
            "plays": [
                {"id": "abc12345", "event_id": "e1", "market": "h2h", "side": "away", "book": "draftkings",
                 "status": "win", "units": 1.5, "pnl_units": 1.36, "clv_prob": 0.01},
                {"id": "keep0001", "event_id": "e2", "market": "h2h", "side": "away", "book": "fanduel",
                 "status": "win", "units": 0.27, "pnl_units": 0.79},
            ]
        }
    )
    led = load_nba_ledger()
    assert apply_nba_ledger_overrides(led) == 1
    assert apply_nba_ledger_overrides(led) == 0  # idempotent
    v, k = led["plays"]
    assert (v["status"], v["units"], v["pnl_units"]) == ("void", 0.0, 0.0)
    assert v["void_reason"] == "placeholder anchor price bug"
    assert v["pre_void_status"] == "win" and v["pre_void_pnl_units"] == 1.36
    assert "clv_prob" not in v
    assert (k["status"], k["pnl_units"]) == ("win", 0.79)

    # A later scan cannot log the same bet again, from any book.
    sig = {"event_id": "e1", "market": "h2h", "side": "away", "book": "fanduel", "price": 450,
           "kickoff": "2099-01-01T00:00:00+00:00", "demo": True}
    res = append_nba_signals([sig])
    assert res["added"] == 0
    assert drop_voided_signals([sig, {"event_id": "e9", "market": "h2h", "side": "home"}]) == [
        {"event_id": "e9", "market": "h2h", "side": "home"}
    ]


def test_repo_overrides_cover_the_nine_bad_moneylines():
    from pathlib import Path

    from sharp_scout.nba.overrides import load_nba_overrides

    root = Path(__file__).resolve().parents[1]
    ovs = load_nba_overrides(root / "data" / "shadow" / "nba_ledger_overrides.json")
    games = sorted(o["game"] for o in ovs)
    assert games == sorted(
        [
            "MIN @ HOU", "MIL @ BOS", "DAL @ SAS", "CHI @ NYK", "TOR @ DEN", "PHI @ DET",
            "CHI @ BOS", "NYK @ PHI", "DEN @ PHX",
        ]
    )
    assert all(o["market"] == "h2h" and o["reason"] == "placeholder anchor price bug" for o in ovs)
    ledger = json.loads((root / "data" / "shadow" / "nba_ledger.json").read_text())
    by_id = {p["id"]: p for p in ledger["plays"]}
    for o in ovs:
        assert by_id[o["id"]]["status"] == "void"
        assert by_id[o["id"]]["pnl_units"] == 0.0
    # SAC +290 (real Pinnacle anchor) stays a win.
    assert by_id["124e1eee"]["status"] == "win"
