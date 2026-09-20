"""NCAAF hygiene rules + T-2h card freeze (from the 2026 Weeks 1–3 review)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sharp_scout.ledger.tracker import append_signals, empty_ledger, save_ledger
from sharp_scout.phase3.market import EdgeCandidate
from sharp_scout.phase4.filters import ncaaf_hygiene_check, validate_edge


def _edge(**kw) -> EdgeCandidate:
    base = dict(
        event_id="e1", home_team="TULSA", away_team="EAST TEXAS A AND M",
        market="spreads", side="away", line=41.5, book="fliff", price=-120,
        p_true=0.9, p_mkt=0.51, edge=0.6, sharp_book="pinnacle", sharp_price=-110,
        model_spread=-2.2, model_total=55.0,
    )
    base.update(kw)
    return EdgeCandidate(**base)


def test_ncaaf_ml_underdog_rejected():
    ok, note = ncaaf_hygiene_check(_edge(market="h2h", side="away", line=None, price=+240, p_mkt=0.3))
    assert not ok and "ML underdog" in note


def test_ncaaf_ml_favorite_allowed():
    ok, _ = ncaaf_hygiene_check(_edge(market="h2h", side="home", line=None, price=-180, p_mkt=0.62))
    assert ok


def test_ncaaf_sharp_veto_when_pinnacle_leans_other_way():
    ok, note = ncaaf_hygiene_check(_edge(p_mkt=0.47))
    assert not ok and "sharp veto" in note


def test_ncaaf_sharp_neutral_or_agreeing_allowed():
    assert ncaaf_hygiene_check(_edge(p_mkt=0.5))[0]
    assert ncaaf_hygiene_check(_edge(p_mkt=0.53))[0]
    assert ncaaf_hygiene_check(_edge(p_mkt=None))[0]


def test_validate_edge_applies_hygiene_only_for_ncaaf():
    dog = _edge(market="h2h", side="away", line=None, price=+240, p_mkt=0.3)
    ncaaf = validate_edge(dog, splits=[], sport="ncaaf")
    assert not ncaaf.passed and ncaaf.tier == "rejected"
    assert any("ML underdog" in n for n in ncaaf.notes)
    # NFL path is untouched by the NCAAF rules (it fails later for lack of split data).
    nfl = validate_edge(dog, splits=[], sport="nfl")
    assert not any("ML underdog" in n for n in nfl.notes)


def _sig(kickoff: datetime, **kw) -> dict:
    base = {
        "event_id": "g1", "away_team": "STONEHILL", "home_team": "MASSACHUSETTS",
        "market": "spreads", "side": "away", "line": 31.5, "book": "betsson", "price": -119,
        "edge": 0.8, "p_true": 0.99, "tier": "play", "filter_passed": True,
        "rationale": "t", "kickoff": kickoff.isoformat(),
    }
    base.update(kw)
    return base


def test_card_freezes_inside_t_minus_2h(tmp_path: Path):
    path = tmp_path / "ncaaf_ledger.json"
    save_ledger(empty_ledger(), path)
    kick = datetime(2026, 9, 19, 19, 30, tzinfo=timezone.utc)

    # Day-ahead run posts the play.
    append_signals([_sig(kick)], path=path, now=kick - timedelta(hours=26))
    plays = json.loads(path.read_text())["plays"]
    assert len(plays) == 1 and plays[0]["line"] == 31.5

    # T-30m rebuild: new line on the same bet, plus a brand-new ML dog. Both must be ignored.
    late = kick - timedelta(minutes=30)
    append_signals(
        [
            _sig(kick, line=30.5, book="fliff", price=-115, p_true=0.5, tier="lean"),
            _sig(kick, market="h2h", side="away", line=None, price=+900, book="fliff"),
        ],
        path=path,
        now=late,
    )
    plays = json.loads(path.read_text())["plays"]
    assert len(plays) == 1
    assert plays[0]["line"] == 31.5 and plays[0]["tier"] == "play" and plays[0]["p_true"] == 0.99


def test_card_still_updates_before_freeze(tmp_path: Path):
    path = tmp_path / "ncaaf_ledger.json"
    save_ledger(empty_ledger(), path)
    kick = datetime(2026, 9, 19, 19, 30, tzinfo=timezone.utc)
    append_signals([_sig(kick)], path=path, now=kick - timedelta(hours=26))
    append_signals([_sig(kick, line=30.5)], path=path, now=kick - timedelta(hours=3))
    plays = json.loads(path.read_text())["plays"]
    assert len(plays) == 1 and plays[0]["line"] == 30.5
