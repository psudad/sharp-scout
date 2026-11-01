"""Sharp 3, Sharp 3.5 and the unlisted three-system page."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from sharp_scout.ncaam import sharp3, sharp35
from sharp_scout.ncaam.credits import pass_interval_min, record_spend, should_skip_snapshot
from sharp_scout.ncaam.shin import implied, shin_two_way
from sharp_scout.ncaam.splits import has_splits, match_to_slate, parse_game
from sharp_scout.ncaam.systems import ledger_path, pick_status, run_systems, state_path, top_slots

ROOT = Path(__file__).resolve().parents[1]


# ---- Sharp 3 gate table ------------------------------------------------------
GATE_CASES = [
    # line, price, money, ticket, mid, road, ml, expect market, line, price, tier, units, flags
    (4.5, -110, 58, 40, False, True, None, "spreads", 4.5, -110, "DIAMOND", 4.0, []),
    (4.5, -110, 50, 40, False, False, None, "spreads", 4.5, -110, "GOLD", 2.0, []),
    (4.5, -110, 80, 40, False, False, None, "spreads", 4.5, -110, "DOUBLE_DIAMOND", 10.0, []),
    (-4.5, -110, 58, 40, False, False, -140, "h2h", None, -140, "DIAMOND", 4.0, ["PIVOT_TO_ML"]),
    (-4.5, -110, 58, 40, False, False, -160, "h2h", None, -160, "TRAP", 0.0, ["PIVOT_TO_ML", "JUICE_TRAP"]),
    (-4.5, -110, 58, 40, False, False, -200, "spreads", -4.0, -130, "DIAMOND", 4.0, ["BUY_POINT"]),
    (-8.0, -110, 58, 40, False, True, None, "spreads", -8.0, -110, "TRAP", 0.0, ["ROAD_7_TRAP"]),
    (-8.0, -110, 58, 40, True, True, None, "spreads", -8.0, -110, "DIAMOND", 4.0, []),
    (-8.0, -110, 58, 40, False, False, None, "spreads", -8.0, -110, "DIAMOND", 4.0, []),
    (-3.0, -160, 58, 40, False, False, None, "spreads", -3.0, -160, "TRAP", 0.0, ["JUICE_TRAP"]),
    (-3.0, -160, 58, 40, True, False, None, "spreads", -3.0, -160, "DIAMOND", 4.0, []),
]


@pytest.mark.parametrize("line,price,money,ticket,mid,road,ml,mkt,bl,bp,tier,units,flags", GATE_CASES)
def test_sharp3_gate_table(line, price, money, ticket, mid, road, ml, mkt, bl, bp, tier, units, flags):
    r = sharp3.logic_gates(
        line=line, price=price, money_pct=money, ticket_pct=ticket, is_mid_major=mid, is_road=road, ml_price=ml
    )
    assert r["market"] == mkt
    assert r["line"] == bl
    assert r["price"] == bp
    assert r["tier"] == tier
    assert r["units"] == units
    assert r["flags"] == flags
    assert r["price_estimated"] == ("BUY_POINT" in flags)


def test_sharp3_confidence_formula():
    assert sharp3.confidence(70, 40) == pytest.approx(0.72 + 0.15 + 0.05)
    assert sharp3.confidence(55, 60) == pytest.approx(0.72)


# ---- Shin --------------------------------------------------------------------
def test_shin_even_market():
    p1, p2, z = shin_two_way(implied(-110), implied(-110))
    assert p1 == pytest.approx(0.5, abs=1e-9)
    assert p1 + p2 == pytest.approx(1.0, abs=1e-9)
    assert z == pytest.approx(0.047619, abs=1e-5)


def test_shin_known_example():
    p1, p2, z = shin_two_way(implied(-200), implied(170))
    assert p1 + p2 == pytest.approx(1.0, abs=1e-9)
    assert p1 == pytest.approx(0.64815, abs=1e-4)
    # Shin gives the favourite more than proportional normalisation does.
    q1, q2 = implied(-200), implied(170)
    assert p1 > q1 / (q1 + q2)


# ---- Sharp 3.5 tiers ----------------------------------------------------------
@pytest.mark.parametrize(
    "edge,tier,units",
    [
        (2.49, "LEAN", 0.0),
        (2.5, "GOLD", 1.0),
        (2.9, "GOLD", 1.4),
        (3.49, "GOLD", 2.0),
        (3.5, "DIAMOND", 2.0),
        (4.8, "DIAMOND", 3.7),
        (4.99, "DIAMOND", 4.0),
        (5.0, "DOUBLE_DIAMOND", 5.0),
        (8.6, "DOUBLE_DIAMOND", 8.6),
        (15.0, "DOUBLE_DIAMOND", 10.0),
        (15.01, None, 0.0),
    ],
)
def test_sharp35_tier_boundaries(edge, tier, units):
    assert sharp35.tier_and_units(edge) == (tier, units)


def _splits(hm, ht, am, at, hline=-3.5, open_home=None):
    rec = {
        "spread": {
            "home": {"money_pct": hm, "ticket_pct": ht, "line": hline, "price": -110.0},
            "away": {"money_pct": am, "ticket_pct": at, "line": -hline, "price": -110.0},
        },
        "ml": {},
        "open_line": {},
        "splits_source": "actionnetwork:book15",
    }
    if open_home is not None:
        rec["open_line"] = {"home": open_home, "away": -open_home}
    return rec


def test_sharp35_phase1_whale_and_rlm():
    game = {"espn_id": "1", "home_team": "Duke", "away_team": "Army"}
    # Public (70% tickets) on home; home line moved from -5.5 to -3.5 => RLM for away.
    sp = _splits(30, 70, 70, 30, hline=-3.5, open_home=-5.5)
    p1 = sharp35.phase1(game, sp, None, is_mid_major_by_side={"home": False, "away": False}, situational=None)
    assert p1["signals"]["away"] == ["WHALE_GAP", "RLM"]
    assert p1["shortlisted"] and p1["side"] == "away"
    # Line moved toward the public: no RLM, one signal only.
    sp2 = _splits(30, 70, 70, 30, hline=-6.5, open_home=-5.5)
    p2 = sharp35.phase1(game, sp2, None, is_mid_major_by_side={"home": False, "away": False}, situational=None)
    assert p2["signals"]["away"] == ["WHALE_GAP"] and not p2["shortlisted"]


def test_sharp35_mid_major_whale_threshold():
    game = {"espn_id": "1", "home_team": "A", "away_team": "B"}
    sp = _splits(34, 50, 66, 50)
    p = sharp35.phase1(game, sp, None, is_mid_major_by_side={"home": True, "away": True}, situational=None)
    assert "WHALE_GAP" in p["signals"]["away"]
    p = sharp35.phase1(game, sp, None, is_mid_major_by_side={"home": False, "away": False}, situational=None)
    assert "WHALE_GAP" not in p["signals"]["away"]


def test_sharp35_phase2_is_deterministic_and_uses_verifying_book():
    ratings = {
        "Duke": {"adjoe": 120.0, "adjde": 92.0, "adjt": 68.0, "lg_adjt": 68.0, "lg_eff": 106.0},
        "Army": {"adjoe": 100.0, "adjde": 108.0, "adjt": 66.0, "lg_adjt": 68.0, "lg_eff": 106.0},
    }
    game = {"espn_id": "42", "home_team": "Duke", "away_team": "Army", "conference_game": False}
    event = {
        "bookmakers": {
            "fanduel": {"markets": {"spreads": [
                {"side": "home", "point": -20.5, "price": -110},
                {"side": "away", "point": 20.5, "price": -110},
            ]}}
        }
    }
    market = sharp35._verify_market(event, None)
    assert market["book"] == "fanduel"
    a = sharp35.phase2(game, "home", market, ratings, hostile=False)
    b = sharp35.phase2(game, "home", market, ratings, hostile=False)
    assert a == b
    assert a["novig"] == pytest.approx(0.5, abs=1e-6)
    star = sharp35.phase2(game, "home", market, ratings, hostile=False, star_out={"home": ["X"]})
    assert star["margin_model"] == pytest.approx(a["margin_model"] - 2.5, abs=1e-6)


# ---- Throttle, status, credit guard -----------------------------------------
def test_top_slots_keeps_ten_largest_gaps():
    entries = [(f"g{i}", float(i)) for i in range(15)]
    assert top_slots(entries) == {f"g{i}" for i in range(5, 15)}
    assert len(top_slots(entries[:4])) == 4


def test_pick_status():
    ranks = sharp3.TIER_RANK
    assert pick_status(None, "GOLD", ranks) == "NEW"
    assert pick_status("GOLD", "DIAMOND", ranks) == "UPGRD"
    assert pick_status("DIAMOND", "DIAMOND", ranks) == "HOLD"


def test_credit_guard_at_100_and_120(tmp_path, monkeypatch):
    from sharp_scout.ncaam import credits as mod

    monkeypatch.setattr(mod, "NCAAM_DATA", tmp_path)
    record_spend(98)
    assert pass_interval_min(15) == 15
    record_spend(2)
    assert pass_interval_min(15) == 30
    assert should_skip_snapshot(remaining_header=None) == (False, "")
    record_spend(20)
    skip, reason = should_skip_snapshot(remaining_header=None)
    assert skip and reason == "ncaam_daily_cap"


# ---- Splits parsing / matching ------------------------------------------------
def _an_game(hm, ht):
    return {
        "id": 9,
        "start_time": "2026-11-04T00:00:00.000Z",
        "home_team_id": 1,
        "away_team_id": 2,
        "teams": [
            {"id": 1, "location": "Duke", "display_name": "Duke Blue Devils", "conference_type": "ACC"},
            {"id": 2, "location": "Army", "display_name": "Army Black Knights", "conference_type": "PATRIOT"},
        ],
        "markets": {
            "15": {"event": {"spread": [
                {"side": "home", "team_id": 1, "value": -20.5, "odds": -110,
                 "bet_info": {"money": {"percent": hm}, "tickets": {"percent": ht}}},
                {"side": "away", "team_id": 2, "value": 20.5, "odds": -110,
                 "bet_info": {"money": {"percent": 100 - hm}, "tickets": {"percent": 100 - ht}}},
            ]}},
            "30": {"event": {"spread": [
                {"side": "home", "team_id": 1, "value": -19.5, "odds": -110},
                {"side": "away", "team_id": 2, "value": 19.5, "odds": -110},
            ]}},
        },
    }


def test_parse_game_keeps_percent_scale_and_opener():
    rec = parse_game(_an_game(1, 2))
    assert rec["spread"]["home"]["money_pct"] == 1.0  # 1%, not 100%
    assert rec["open_line"] == {"home": -19.5, "away": 19.5}
    assert has_splits(rec)


def test_zero_splits_are_not_splits():
    g = _an_game(0, 0)
    for o in g["markets"]["15"]["event"]["spread"]:
        o["bet_info"] = {"money": {"percent": 0}, "tickets": {"percent": 0}}
    assert not has_splits(parse_game(g))


def test_match_swapped_neutral_site():
    rec = parse_game(_an_game(70, 40))
    slate = [{
        "espn_id": "e1", "home_team": "Army", "away_team": "Duke",
        "commence_time": datetime(2026, 11, 4, tzinfo=timezone.utc),
    }]
    m = match_to_slate(slate, [rec])
    assert m["e1"]["spread"]["away"]["money_pct"] == 70.0
    assert m["e1"]["home_conf"] == "PATRIOT"


# ---- End to end: locks into separate ledgers, never the New System one ---------
def _odds_event(home_line=4.5):
    sp = [
        {"side": "home", "point": home_line, "price": -110},
        {"side": "away", "point": -home_line, "price": -110},
    ]
    return {"bookmakers": {
        "draftkings": {"markets": {"spreads": sp, "h2h": [{"side": "home", "price": 160}, {"side": "away", "price": -190}]}},
        "fanduel": {"markets": {"spreads": sp}},
    }}


def test_run_systems_locks_separately(tmp_path):
    now = datetime.now(timezone.utc)
    tip = now + timedelta(minutes=60)
    games, an, odds = [], [], {}
    for i in range(12):
        games.append({
            "espn_id": f"g{i}", "odds_event_id": f"o{i}", "home_team": "Duke", "away_team": "Army",
            "commence_time": tip, "neutral_site": False, "home_conference_id": "2", "away_conference_id": "",
        })
        rec = parse_game(_an_game(60 + i, 40))
        rec["an_id"] = f"a{i}"
        rec["start_time"] = tip.isoformat()
        an.append(rec)
        odds[f"o{i}"] = _odds_event(-4.0)
    # match_to_slate pairs each slate row with an unused AN record in order.
    res = run_systems(now=now, slate=games, odds_by_id=odds, ratings={}, splits_result={"games": an}, data_dir=tmp_path)
    s3 = json.loads(ledger_path("sharp3", tmp_path).read_text())["plays"]
    assert len(s3) == 10  # 10-game throttle
    assert all(p["engine"] == "sharp3" and p["model_version"] == "sharp3-v1" for p in s3)
    assert all(p["units"] > 0 for p in s3)
    assert len(res["locked"]) == 10
    st = json.loads(state_path(tip.astimezone(sharp3_et()).date(), tmp_path).read_text())
    vol = [g for g in st["games"].values() if (g.get("sharp3") or {}).get("volume")]
    assert len(vol) == 2
    # A second pass never re-locks or adds beyond 10.
    run_systems(now=now, slate=games, odds_by_id=odds, ratings={}, splits_result={"games": an}, data_dir=tmp_path)
    assert len(json.loads(ledger_path("sharp3", tmp_path).read_text())["plays"]) == 10


def sharp3_et():
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/New_York")


# ---- Unlisted page --------------------------------------------------------------
def _load_builder():
    spec = importlib.util.spec_from_file_location("build_ncaam_lab", ROOT / "scripts" / "build_ncaam_lab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FORBIDDEN = re.compile(r"Gem\b|Gemini|Model B|\b3\.0\b|\b5\.0\b|4\.11|\u2014", re.I)


def test_lab_page_names_and_noindex(tmp_path, monkeypatch):
    mod = _load_builder()
    data = tmp_path / "data"
    (data / "ncaam").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(sharp3_et()).date()
    state = {
        "updated_at": now.isoformat(),
        "splits": {"n_with_money": 1, "n_games": 1},
        "games": {"g1": {
            "tip": (now + timedelta(hours=3)).isoformat(), "home_team": "Duke", "away_team": "Army",
            "has_splits": True,
            "sharp3": {"result": "play", "locked": True, "side": "home", "market": "spreads", "line": -3.0,
                        "price": -130, "tier": "DOUBLE_DIAMOND", "units": 10.0, "pick_status": "NEW",
                        "price_estimated": True},
            "sharp35": {"result": "lean", "side": "away"},
        }},
    }
    (data / "ncaam" / f"systems_{day.strftime('%Y%m%d')}.json").write_text(json.dumps(state))
    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "SYSTEMS", (
        ("sharp3", "Sharp 3", data / "ncaam" / "sharp3_ledger.json"),
        ("sharp35", "Sharp 3.5", data / "ncaam" / "sharp35_ledger.json"),
        ("new", "New System", data / "ncaam_ledger.json"),
    ))
    out = mod.build(tmp_path / "out" / "index.html", now=now)
    page = out.read_text()
    for name in ("Sharp 3", "Sharp 3.5", "New System"):
        assert name in page
    assert 'name="robots" content="noindex, nofollow' in page
    assert "Duke -3" in page and "10u" in page
    assert not FORBIDDEN.search(page)


def test_lab_page_waiting_on_splits(tmp_path, monkeypatch):
    mod = _load_builder()
    data = tmp_path / "data"
    (data / "ncaam").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    day = now.astimezone(sharp3_et()).date()
    (data / "ncaam" / f"systems_{day.strftime('%Y%m%d')}.json").write_text(json.dumps({
        "splits": {"n_with_money": 0}, "games": {"g1": {"tip": now.isoformat(), "home_team": "A", "away_team": "B",
                                                        "has_splits": False}}}))
    (data / "ncaam_ledger.json").write_text(json.dumps({"plays": [{"espn_id": "g1", "status": "no_play"}]}))
    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "SYSTEMS", (
        ("sharp3", "Sharp 3", data / "ncaam" / "sharp3_ledger.json"),
        ("sharp35", "Sharp 3.5", data / "ncaam" / "sharp35_ledger.json"),
        ("new", "New System", data / "ncaam_ledger.json"),
    ))
    page = mod.build(tmp_path / "x.html", now=now).read_text()
    assert page.count("Waiting on splits data") == 2


def test_lab_builder_skips_without_slug(monkeypatch, capsys):
    mod = _load_builder()
    monkeypatch.delenv("NCAAM_LAB_SLUG", raising=False)
    monkeypatch.setattr("sys.argv", ["x"])
    assert mod.main() == 0
    assert "skipping" in capsys.readouterr().out


def test_public_site_never_mentions_sharp_systems():
    """The public NCAAM page and the rest of docs/ must not link to or name the unlisted systems."""
    for p in (ROOT / "docs").rglob("*.html"):
        txt = p.read_text(errors="ignore")
        assert "Sharp 3.5" not in txt, p
        assert "Sharp 3<" not in txt and "Sharp 3 " not in txt, p
    src = (ROOT / "src" / "sharp_scout" / "site" / "ncaam_page.py").read_text()
    assert "sharp3" not in src and "Sharp 3" not in src
